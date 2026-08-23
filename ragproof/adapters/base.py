"""Base protocol for RAG adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RAGResponse(BaseModel):
    question: str
    answer: str
    contexts: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    first_token_latency_ms: float | None = None
    output_char_count: int | None = None
    output_token_count: int | None = None
    tokens_per_second: float | None = None
    streamed: bool = False
    error: str | None = None
    error_type: str | None = None
    status_code: int | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    raw: dict | None = None


@runtime_checkable
class RAGAdapter(Protocol):
    def ask(self, question: str) -> RAGResponse: ...
