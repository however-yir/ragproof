"""Configuration models for ragproof runs."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env(text: str) -> str:
    """Expand ${VAR} references using environment variables (empty if unset)."""
    return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), text)


class AdapterConfig(BaseModel):
    """How to reach the RAG system under test."""

    type: str = "http"  # http | mock
    base_url: str = ""
    endpoint: str = ""
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: float = 60.0
    # Request mapping: how to place the question into the request.
    # query_param -> put question in a query-string param of this name
    # json_field  -> put question in a JSON body field of this name
    query_param: str | None = None
    json_field: str | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)
    extra_json: dict[str, Any] = Field(default_factory=dict)
    # Response mapping (dotted paths into the JSON response).
    answer_path: str = "answer"
    contexts_path: str | None = None  # list of retrieved context strings
    context_id_path: str | None = None  # id field within each context item
    citations_path: str | None = None  # list of citation ids/strings


class JudgeConfig(BaseModel):
    """LLM-as-judge backend (OpenAI-compatible, works with Ollama)."""

    enabled: bool = True
    base_url: str = "http://localhost:11434/v1"
    api_key_env: str = "RAGPROOF_JUDGE_API_KEY"
    model: str = "qwen2.5:7b"
    timeout: float = 60.0
    # If the judge is unreachable / no key, skip gracefully instead of failing.
    skip_on_error: bool = True


class RunConfig(BaseModel):
    """Top-level run configuration loaded from YAML."""

    name: str = "ragproof-run"
    dataset: str
    adapter: AdapterConfig
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    concurrency: int = 4
    retries: int = 1
    top_k: int = 5  # k used for recall@k / precision@k

    @classmethod
    def load(cls, path: str | Path) -> "RunConfig":
        text = _expand_env(Path(path).read_text(encoding="utf-8"))
        raw = yaml.safe_load(text)
        return cls.model_validate(raw)
