"""RAG adapters: how ragproof talks to the system under test."""

from __future__ import annotations

from ..config import AdapterConfig
from .base import RAGAdapter, RAGResponse
from .http import HTTPAdapter
from .mock import MockAdapter


def build_adapter(config: AdapterConfig) -> RAGAdapter:
    if config.type == "mock":
        return MockAdapter(config)
    if config.type == "http":
        return HTTPAdapter(config)
    raise ValueError(f"unknown adapter type: {config.type}")


__all__ = ["RAGAdapter", "RAGResponse", "HTTPAdapter", "MockAdapter", "build_adapter"]
