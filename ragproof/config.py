"""Validated configuration models for ragproof runs."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from .privacy import redact_nested

_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env(text: str) -> tuple[str, list[str]]:
    """Expand ``${VAR}`` references and retain missing names for validation."""
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = os.environ.get(name)
        if value is None:
            missing.append(name)
            return ""
        return value

    return _ENV_PATTERN.sub(replace, text), sorted(set(missing))


def _redact_value(value: Any) -> Any:
    """Redact common credential-shaped values in summaries and diagnostics."""
    if not isinstance(value, str):
        return value
    if len(value) >= 16 and any(character in value for character in ("_", "-")):
        return "***"
    return value


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
    retry_jitter: float = 0.1
    max_response_bytes: int = 10_000_000
    max_answer_chars: int = 1_000_000
    max_contexts: int = 1_000
    max_context_chars: int = 1_000_000
    # Request mapping.
    query_param: str | None = None
    json_field: str | None = None
    request_template: dict[str, Any] | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)
    extra_json: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False
    stream_token_path: str | None = None
    stream_done_markers: list[str] = Field(default_factory=lambda: ["[DONE]"])
    tokenizer: str = "heuristic"  # heuristic | whitespace | chars
    # Response mapping (dotted paths into the JSON response).
    answer_path: str = "answer"
    contexts_path: str | None = None
    context_id_path: str | None = None
    context_text_path: str | None = None
    citations_path: str | None = None
    citation_id_path: str | None = None
    citation_text_path: str | None = None
    fallback_path: str | None = None
    expected_fallback: bool | None = None

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

    @field_validator("retry_backoff", "retry_jitter")
    @classmethod
    def non_negative_backoff(cls, value: float) -> float:
        if value < 0:
            raise ValueError("retry timing values must be 0 or greater")
        return value

    @field_validator("max_response_bytes", "max_answer_chars", "max_contexts", "max_context_chars")
    @classmethod
    def positive_limits(cls, value: int) -> int:
        if value < 1:
            raise ValueError("adapter size limits must be at least 1")
        return value


class JudgeConfig(BaseModel):
    """LLM-as-judge backend (OpenAI-compatible, works with Ollama)."""

    model_config = ConfigDict(extra="forbid")

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
    prompt_version: str = "builtin-v1"
    max_failures: int | None = None
    max_concurrency: int = 4
    min_request_interval: float = 0.0
    max_prompt_chars: int = 120_000
    max_prompt_tokens: int = Field(default=30_000, ge=16)

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

    @field_validator("max_concurrency", "max_prompt_chars")
    @classmethod
    def positive_limits(cls, value: int) -> int:
        if value < 1:
            raise ValueError("judge limits must be at least 1")
        return value

    @field_validator("min_request_interval")
    @classmethod
    def non_negative_interval(cls, value: float) -> float:
        if value < 0:
            raise ValueError("min_request_interval must be 0 or greater")
        return value


class RunConfig(BaseModel):
    """Top-level run configuration loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    _dataset_label: str | None = PrivateAttr(default=None)
    _legacy_dataset_label: str | None = PrivateAttr(default=None)

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
    required_metrics: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    min_sample_count: int | None = None
    min_coverage: dict[str, float] = Field(default_factory=dict)
    stratify_by: str | None = None
    deduplicate_questions: bool = True
    redact_sensitive: bool = True
    embedding_model: str | None = None
    tokenizer: str = "heuristic"
    # These values are copied into run metadata when supplied by CI or a caller.
    git_sha: str | None = None
    config_path: str | None = Field(default=None, exclude=True)
    missing_env_vars: list[str] = Field(default_factory=list, exclude=True)

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
        expanded, missing_env_vars = _expand_env(config_path.read_text(encoding="utf-8"))
        raw = yaml.safe_load(expanded) or {}
        config = cls.model_validate(raw)
        raw_dataset = str(raw.get("dataset", config.dataset)).replace("\\", "/")
        config._legacy_dataset_label = raw_dataset
        config._dataset_label = Path(raw_dataset).name if Path(raw_dataset).is_absolute() else raw_dataset
        dataset_path = Path(config.dataset)
        if not dataset_path.is_absolute():
            relative_to_config = (config_path.parent / dataset_path).resolve()
            # Preserve the historical cwd-relative behavior when an example
            # intentionally uses a repository-root path such as examples/foo.
            config.dataset = str(relative_to_config if relative_to_config.exists() else dataset_path)
        config.config_path = str(config_path)
        config.missing_env_vars = missing_env_vars
        return config

    def effective_top_ks(self) -> list[int]:
        return sorted(set([self.top_k, *self.top_ks]))

    def summary(self) -> dict[str, Any]:
        """Return portable, recursively redacted run metadata."""
        label = self._dataset_label or (Path(self.dataset).name if Path(self.dataset).is_absolute() else self.dataset)
        summary = {
            "name": self.name,
            "dataset": label,
            "adapter": self.adapter.model_dump(exclude_none=True),
            "judge": self.judge.model_dump(exclude_none=True),
            "concurrency": self.concurrency,
            "retries": self.retries,
            "retry_backoff": self.retry_backoff,
            "top_ks": self.effective_top_ks(),
            "sample_limit": self.sample_limit,
            "include_tags": self.include_tags,
            "exclude_tags": self.exclude_tags,
            "seed": self.seed,
            "group_by": self.group_by,
            "required_fields": sorted(set(self.required_fields)),
            "min_sample_count": self.min_sample_count,
            "min_coverage": self.min_coverage,
            "stratify_by": self.stratify_by,
            "deduplicate_questions": self.deduplicate_questions,
            "redact_sensitive": self.redact_sensitive,
            "tokenizer": self.tokenizer,
            "embedding_model": self.embedding_model,
            "required_metrics": sorted(set(self.required_metrics)),
        }
        return redact_nested(summary)

    def fingerprint_summary(self) -> dict[str, Any]:
        """Return evaluation-affecting config independent of filesystem location."""
        summary = self.summary()
        summary.pop("dataset", None)
        return summary

    def legacy_fingerprint_summary(self) -> dict[str, Any]:
        """Reproduce the v0.4.1 fingerprint for comparisons with old baselines."""
        adapter = self.adapter.model_dump(
            exclude={
                "retry_jitter",
                "max_response_bytes",
                "max_answer_chars",
                "max_contexts",
                "max_context_chars",
            },
            exclude_none=True,
        )
        headers = adapter.get("headers", {})
        adapter["headers"] = {
            key: "***"
            if any(token in key.lower() for token in ("key", "token", "auth", "secret", "password"))
            else _redact_value(value)
            for key, value in headers.items()
        }
        judge = self.judge.model_dump(
            exclude={"api_key_env", "max_concurrency", "min_request_interval", "max_prompt_chars", "max_prompt_tokens"},
            exclude_none=True,
        )
        label = self._legacy_dataset_label or self.dataset
        return {
            "name": self.name,
            "dataset": label,
            "adapter": adapter,
            "judge": judge,
            "concurrency": self.concurrency,
            "retries": self.retries,
            "top_ks": self.effective_top_ks(),
            "sample_limit": self.sample_limit,
            "include_tags": self.include_tags,
            "exclude_tags": self.exclude_tags,
            "seed": self.seed,
            "group_by": self.group_by,
            "required_fields": sorted(set(self.required_fields)),
            "min_sample_count": self.min_sample_count,
            "min_coverage": self.min_coverage,
            "stratify_by": self.stratify_by,
            "tokenizer": self.tokenizer,
            "embedding_model": self.embedding_model,
            "required_metrics": sorted(set(self.required_metrics)),
        }

    def validation_errors(self) -> list[str]:
        """Return actionable, user-facing errors beyond Pydantic type checks."""
        errors: list[str] = []
        if self.missing_env_vars:
            errors.append("missing environment variables: " + ", ".join(self.missing_env_vars))
        if not Path(self.dataset).exists():
            errors.append(f"dataset does not exist: {self.dataset}")
        if self.adapter.type.lower() in {"http", "langserve", "dify", "openai", "llamaindex", "langchain"}:
            if not self.adapter.base_url:
                errors.append("adapter.base_url is required for an HTTP adapter")
            if not self.adapter.endpoint:
                errors.append("adapter.endpoint is required for an HTTP adapter")
        if self.sample_limit is not None and self.sample_limit < 1:
            errors.append("sample_limit must be at least 1 when provided")
        if self.min_sample_count is not None and self.min_sample_count < 1:
            errors.append("min_sample_count must be at least 1 when provided")
        if any(not 0 <= value <= 1 for value in self.min_coverage.values()):
            errors.append("min_coverage values must be between 0 and 1")
        return errors
