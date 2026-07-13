"""Generic HTTP adapter with configurable request/response mapping.

Works with any RAG API (e.g. knowledgeops-agent /ai/pdf/chat) by mapping:
- where the question goes (query param or JSON field)
- dotted paths to pull answer / contexts / citations out of the response
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import AdapterConfig
from .base import RAGResponse


def _dig(data: Any, path: str | None) -> Any:
    """Resolve a dotted path like 'data.result.answer' into a JSON structure."""
    if not path:
        return None
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


class HTTPAdapter:
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.client = httpx.Client(
            base_url=config.base_url,
            headers=config.headers,
            timeout=config.timeout,
        )

    def ask(self, question: str) -> RAGResponse:
        cfg = self.config
        params = dict(cfg.extra_params)
        json_body: dict[str, Any] | None = None
        if cfg.query_param:
            params[cfg.query_param] = question
        if cfg.json_field:
            json_body = dict(cfg.extra_json)
            json_body[cfg.json_field] = question

        start = time.perf_counter()
        try:
            resp = self.client.request(
                cfg.method, cfg.endpoint, params=params or None, json=json_body
            )
            latency = (time.perf_counter() - start) * 1000
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                # Plain-text answer endpoints
                return RAGResponse(
                    question=question, answer=resp.text, latency_ms=latency
                )
        except httpx.HTTPError as exc:
            latency = (time.perf_counter() - start) * 1000
            return RAGResponse(
                question=question, answer="", latency_ms=latency, error=str(exc)
            )

        answer = _dig(data, cfg.answer_path)
        raw_contexts = _dig(data, cfg.contexts_path) or []
        contexts: list[str] = []
        context_ids: list[str] = []
        for item in raw_contexts:
            if isinstance(item, str):
                contexts.append(item)
            elif isinstance(item, dict):
                contexts.append(str(item.get("text") or item.get("content") or item))
                if cfg.context_id_path:
                    cid = _dig(item, cfg.context_id_path)
                    if cid is not None:
                        context_ids.append(str(cid))
        raw_citations = _dig(data, cfg.citations_path) or []
        citations = [str(c) for c in raw_citations]

        return RAGResponse(
            question=question,
            answer=str(answer) if answer is not None else "",
            contexts=contexts,
            context_ids=context_ids,
            citations=citations,
            latency_ms=latency,
        )
