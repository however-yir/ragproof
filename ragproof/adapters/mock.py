"""Mock adapter for offline demos and tests.

Deterministically fabricates answers so that run -> compare -> report
can be exercised end-to-end without a live RAG system.
"""

from __future__ import annotations

import hashlib

from ..config import AdapterConfig
from .base import RAGResponse


class MockAdapter:
    def __init__(self, config: AdapterConfig):
        self.config = config

    def ask(self, question: str) -> RAGResponse:
        h = int(hashlib.sha256(question.encode("utf-8")).hexdigest(), 16)
        doc_ids = [f"doc{(h + i) % 7 + 1}" for i in range(3)]
        contexts = [f"[{d}] Mock context for: {question[:40]}" for d in doc_ids]
        return RAGResponse(
            question=question,
            answer=f"Mock answer to: {question}",
            contexts=contexts,
            context_ids=doc_ids,
            citations=doc_ids[:2],
            latency_ms=float(h % 200 + 20),
        )
