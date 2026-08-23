"""RAG adapters: how ragproof talks to the system under test."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from ..config import AdapterConfig
from .base import RAGAdapter, RAGResponse
from .http import HTTPAdapter
from .mock import MockAdapter

_PRESETS: dict[str, dict[str, Any]] = {
    "langserve": {"endpoint": "/invoke", "method": "POST", "json_field": "input", "answer_path": "output"},
    "langchain": {"endpoint": "/invoke", "method": "POST", "json_field": "input", "answer_path": "output"},
    "llamaindex": {"endpoint": "/query", "method": "POST", "json_field": "query", "answer_path": "response"},
    "dify": {"endpoint": "/v1/chat-messages", "method": "POST", "json_field": "query", "answer_path": "answer", "contexts_path": "metadata.retriever_resources", "context_id_path": "document_id"},
    "openai": {"endpoint": "/chat/completions", "method": "POST", "request_template": {"messages": [{"role": "user", "content": "{question}"}]}, "answer_path": "choices.0.message.content"},
}


def _with_preset(config: AdapterConfig) -> AdapterConfig:
    preset = _PRESETS.get(config.type.lower())
    if not preset:
        return config
    values: dict[str, Any] = config.model_dump()
    for key, value in preset.items():
        if not values.get(key):
            values[key] = value
    return AdapterConfig.model_validate(values)


def build_adapter(config: AdapterConfig, *, retries: int | None = None, retry_backoff: float | None = None) -> RAGAdapter:
    config = _with_preset(config)
    if retries is not None:
        config = config.model_copy(update={"retries": max(config.retries, retries)})
    if retry_backoff is not None:
        config = config.model_copy(update={"retry_backoff": retry_backoff})
    if config.type == "mock":
        return MockAdapter(config)
    if config.type in {"http", *_PRESETS}:
        return HTTPAdapter(config)
    plugins = entry_points(group="ragproof.adapters")
    for plugin in plugins:
        if plugin.name == config.type:
            return plugin.load()(config)
    raise ValueError(f"unknown adapter type: {config.type}")


__all__ = ["RAGAdapter", "RAGResponse", "HTTPAdapter", "MockAdapter", "build_adapter"]
