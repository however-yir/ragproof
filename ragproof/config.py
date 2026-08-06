"""Validated configuration models for ragproof runs."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env(text: str) -> str:
    """Expand ``${VAR}`` references using environment variables."""
    return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), text)


class AdapterConfig(BaseModel):
    """How to reach the RAG system under test.

    ``request_template`` and dotted response paths make the adapter useful for
    APIs with nested request/response schemas without introducing framework
    dependencies. ``type`` can also name an installed entry-point plugin.
    """

    model_config = ConfigDict(extra="allow")

    type: str = "http"  # http | mock | langserve | dify | openai | plugin name
    base_url: str = ""
    endpoint: str = ""
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    bearer_token_env: str | None = None
    timeout: float = 60.0
    retries: int = 0
    retry_backoff: float = 0.25
    # Request mapping.
    query_param: str | None = None
    json_field: str | None = None
    request_template: dict[str, Any] | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)
    extra_json: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False
    # Response mapping (dotted paths into the JSON response).
    answer_path: str = "answer"
    contexts_path: str | None = None
    context_id_path: str | None = None
    citations_path: str | None = None

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        method = value.upper().strip()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("method must be GET, POST, PUT, PATCH, or DELETE")
        return method

    @field_validator("timeout")
    @classmethod
    def positive_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout must be greater than 0")
        return value

    @field_validator("retries")
    @classmethod
    def non_negative_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("retries must be 0 or greater")
        return value

    @field_validator("retry_backoff")
    @classmethod
    def non_negative_backoff(cls, value: float) -> float:
        if value < 0:
            raise ValueError("retry_backoff must be 0 or greater")
        return value


class JudgeConfig(BaseModel):
    """LLM-as-judge backend (OpenAI-compatible, works with Ollama)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    base_url: str = "http://localhost:11434/v1"
    api_key_env: str = "RAGPROOF_JUDGE_API_KEY"
    model: str = "qwen2.5:7b"
    models: list[str] = Field(default_factory=list)
    vote: str = "mean"  # mean | median
    timeout: float = 60.0
    retries: int = 1
    retry_backoff: float = 0.5
    skip_on_error: bool = True
    structured_output: bool = True
    cache_enabled: bool = True
    cache_path: str | None = None
    cost_per_1k_tokens: float = 0.0
    prompt_overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("timeout")
    @classmethod
    def positive_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout must be greater than 0")
        return value

    @field_validator("retries")
    @classmethod
    def non_negative_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("retries must be 0 or greater")
        return value

    @field_validator("vote")
    @classmethod
    def supported_vote(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"mean", "median"}:
            raise ValueError("vote must be mean or median")
        return value


class RunConfig(BaseModel):
    """Top-level run configuration loaded from YAML."""

    model_config = ConfigDict(extra="allow")

    name: str = "ragproof-run"
    dataset: str
    adapter: AdapterConfig
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    concurrency: int = 4
    retries: int = 1
    retry_backoff: float = 0.25
    top_k: int = 5
    top_ks: list[int] = Field(default_factory=list)
    sample_limit: int | None = None
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    seed: int | None = None
    group_by: list[str] = Field(default_factory=lambda: ["tags", "difficulty"])
    # These values are copied into run metadata when supplied by CI or a caller.
    git_sha: str | None = None
    config_path: str | None = Field(default=None, exclude=True)

    @field_validator("concurrency")
    @classmethod
    def positive_concurrency(cls, value: int) -> int:
        if value < 1:
            raise ValueError("concurrency must be at least 1")
        return value

    @field_validator("retries")
    @classmethod
    def non_negative_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("retries must be 0 or greater")
        return value

    @field_validator("top_k")
    @classmethod
    def positive_top_k(cls, value: int) -> int:
        if value < 1:
            raise ValueError("top_k must be at least 1")
        return value

    @field_validator("top_ks")
    @classmethod
    def positive_top_ks(cls, value: list[int]) -> list[int]:
        if any(k < 1 for k in value):
            raise ValueError("all top_ks values must be at least 1")
        return sorted(set(value))

    @classmethod
    def load(cls, path: str | Path) -> "RunConfig":
        config_path = Path(path).resolve()
        raw = yaml.safe_load(_expand_env(config_path.read_text(encoding="utf-8"))) or {}
        config = cls.model_validate(raw)
        dataset_path = Path(config.dataset)
        if not dataset_path.is_absolute():
            relative_to_config = (config_path.parent / dataset_path).resolve()
            # Preserve the historical cwd-relative behavior when an example
            # intentionally uses a repository-root path such as examples/foo.
            config.dataset = str(relative_to_config if relative_to_config.exists() else dataset_path)
        config.config_path = str(config_path)
        return config

    def effective_top_ks(self) -> list[int]:
        return sorted(set([self.top_k, *self.top_ks]))

    def summary(self) -> dict[str, Any]:
        """Return reproducible metadata without exposing header secrets."""
        adapter = self.adapter.model_dump(exclude_none=True)
        headers = adapter.get("headers", {})
        adapter["headers"] = {
            key: "***" if any(token in key.lower() for token in ("key", "token", "auth", "secret")) else value
            for key, value in headers.items()
        }
        return {
            "name": self.name,
            "dataset": self.dataset,
            "adapter": adapter,
            "judge": self.judge.model_dump(exclude={"api_key_env"}, exclude_none=True),
            "concurrency": self.concurrency,
            "retries": self.retries,
            "top_ks": self.effective_top_ks(),
            "sample_limit": self.sample_limit,
            "include_tags": self.include_tags,
            "exclude_tags": self.exclude_tags,
            "seed": self.seed,
        }

    def validation_errors(self) -> list[str]:
        """Return actionable, user-facing errors beyond Pydantic type checks."""
        errors: list[str] = []
        if not Path(self.dataset).exists():
            errors.append(f"dataset does not exist: {self.dataset}")
        if self.adapter.type.lower() in {"http", "langserve", "dify", "openai", "llamaindex", "langchain"}:
            if not self.adapter.base_url:
                errors.append("adapter.base_url is required for an HTTP adapter")
            if not self.adapter.endpoint:
                errors.append("adapter.endpoint is required for an HTTP adapter")
        if self.sample_limit is not None and self.sample_limit < 1:
            errors.append("sample_limit must be at least 1 when provided")
        return errors
