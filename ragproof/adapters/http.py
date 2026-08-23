"""Generic HTTP adapter with configurable request/response mapping."""

from __future__ import annotations

import json
import os
import time
import asyncio
import datetime
import random
import re
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..config import AdapterConfig
from .base import RAGResponse


class _ResponseTooLarge(ValueError):
    pass


def _dig(data: Any, path: str | None) -> Any:
    """Resolve dotted paths, numeric list indexes, and ``*`` list wildcards."""
    if not path:
        return None
    parts = path.split(".")

    def walk(cur: Any, remaining: list[str]) -> Any:
        if not remaining:
            return cur
        part = remaining[0]
        if part == "*" and isinstance(cur, list):
            values = [walk(item, remaining[1:]) for item in cur]
            return [value for value in values if value is not None]
        if isinstance(cur, dict):
            return walk(cur.get(part), remaining[1:]) if part in cur else None
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            return walk(cur[idx], remaining[1:]) if idx < len(cur) else None
        return None

    return walk(data, parts)


def _render_template(value: Any, question: str) -> Any:
    if isinstance(value, str):
        return value.replace("{{question}}", question).replace("{question}", question)
    if isinstance(value, dict):
        return {key: _render_template(item, question) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_template(item, question) for item in value]
    return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _safe_error(exc: Exception) -> str:
    """Keep diagnostics useful without leaking query tokens or large bodies."""
    message = str(exc)[:500]
    return re.sub(r"(?i)(token|api[_-]?key|secret|password)=([^&\s]+)", r"\1=[REDACTED]", message)


class HTTPAdapter:
    def __init__(self, config: AdapterConfig):
        self.config = config
        headers = dict(config.headers)
        if config.bearer_token_env:
            token = os.environ.get(config.bearer_token_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(base_url=config.base_url, headers=headers, timeout=config.timeout)

    def close(self) -> None:
        self.client.close()

    def _request_payload(self, question: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        cfg = self.config
        params = _render_template(dict(cfg.extra_params), question)
        json_body: dict[str, Any] | None = None
        if cfg.request_template is not None:
            json_body = _render_template(dict(cfg.request_template), question)
            json_body.update(_render_template(dict(cfg.extra_json), question))
        elif cfg.extra_json or cfg.json_field:
            json_body = _render_template(dict(cfg.extra_json), question)
        if cfg.query_param:
            params[cfg.query_param] = question
        if cfg.json_field:
            if json_body is None:
                json_body = {}
            json_body[cfg.json_field] = question
        if cfg.stream and json_body is not None:
            json_body.setdefault("stream", True)
        return params, json_body

    @staticmethod
    def _stream_payload(text: str) -> tuple[str, dict[str, Any] | None]:
        answer_parts: list[str] = []
        last_payload: dict[str, Any] | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                answer_parts.append(line)
                continue
            if isinstance(payload, dict):
                last_payload = payload
                token = _dig(payload, "choices.0.delta.content") or _dig(payload, "choices.0.message.content")
                if token is not None:
                    answer_parts.append(str(token))
        return "".join(answer_parts), last_payload

    @staticmethod
    def _stream_token(payload: Any, path: str | None = None) -> str:
        if not isinstance(payload, dict):
            return ""
        token = _dig(payload, path) if path else None
        token = token or _dig(payload, "choices.0.delta.content") or _dig(payload, "choices.0.message.content")
        return "" if token is None else str(token)

    def _consume_stream(
        self, response: httpx.Response, started: float, token_path: str | None, done_markers: list[str]
    ) -> tuple[str, dict[str, Any] | None, float | None, int]:
        """Consume an SSE/OpenAI-compatible response without buffering it first."""
        answer_parts: list[str] = []
        last_payload: dict[str, Any] | None = None
        first_token_latency: float | None = None
        output_chars = 0
        response_bytes = 0
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.config.max_response_bytes:
            raise _ResponseTooLarge(f"stream Content-Length exceeded {self.config.max_response_bytes} bytes")
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
            response_bytes += len(line.encode("utf-8", errors="replace")) + 1
            if response_bytes > self.config.max_response_bytes:
                raise _ResponseTooLarge(f"stream response exceeded {self.config.max_response_bytes} bytes")
            line = line.strip()
            if not line or line.startswith(":") or line.startswith("event:"):
                continue
            if line.startswith("data:event:"):
                continue
            if line.startswith("data:data:"):
                line = line[len("data:data:"):].strip()
            elif line.startswith("data:"):
                line = line[5:].strip()
            if not line or line in done_markers:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                if line.startswith(("{", "[")):
                    raise ValueError("stream contained truncated or invalid JSON")
                token = line
                payload = None
            else:
                token = self._stream_token(payload, token_path)
                if isinstance(payload, dict):
                    last_payload = payload
            if not token:
                continue
            if first_token_latency is None:
                first_token_latency = (time.perf_counter() - started) * 1000
            answer_parts.append(token)
            output_chars += len(token)
            if output_chars > self.config.max_answer_chars:
                raise _ResponseTooLarge(f"stream answer exceeded {self.config.max_answer_chars} characters")
        return "".join(answer_parts), last_payload, first_token_latency, output_chars

    def _read_limited(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared:
            try:
                if int(declared) > self.config.max_response_bytes:
                    raise _ResponseTooLarge(f"response Content-Length exceeded {self.config.max_response_bytes} bytes")
            except ValueError as exc:
                if isinstance(exc, _ResponseTooLarge):
                    raise
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.config.max_response_bytes:
                raise _ResponseTooLarge(f"response exceeded {self.config.max_response_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                instant = parsedate_to_datetime(raw)
                now = datetime.datetime.now(instant.tzinfo or datetime.timezone.utc)
                return max(0.0, (instant - now).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def _one_request(self, question: str) -> RAGResponse:
        cfg = self.config
        params, json_body = self._request_payload(question)
        start = time.perf_counter()
        first_token_latency: float | None = None
        output_chars: int | None = None
        answer = ""
        data: dict[str, Any] | None = None
        try:
            if cfg.stream:
                with self.client.stream(cfg.method, cfg.endpoint, params=params or None, json=json_body) as response:
                    response.raise_for_status()
                    answer, data, first_token_latency, output_chars = self._consume_stream(
                        response, start, cfg.stream_token_path, cfg.stream_done_markers
                    )
            else:
                with self.client.stream(cfg.method, cfg.endpoint, params=params or None, json=json_body) as response:
                    response.raise_for_status()
                    content = self._read_limited(response)
                    text = content.decode(response.encoding or "utf-8", errors="replace")
                    content_type = response.headers.get("content-type", "").lower()
                    try:
                        parsed = json.loads(text)
                    except ValueError:
                        if "json" in content_type:
                            raise ValueError("response declared JSON but could not be parsed")
                        answer = text
                    else:
                        if not isinstance(parsed, dict):
                            raise ValueError("JSON response must be an object")
                        data = parsed
        except _ResponseTooLarge as exc:
            latency = (time.perf_counter() - start) * 1000
            return RAGResponse(question=question, answer="", latency_ms=latency, error=str(exc), error_type="response_too_large")
        except httpx.TimeoutException as exc:
            latency = (time.perf_counter() - start) * 1000
            return RAGResponse(question=question, answer="", latency_ms=latency, error=_safe_error(exc), error_type="timeout", retryable=True)
        except httpx.HTTPStatusError as exc:
            latency = (time.perf_counter() - start) * 1000
            status = exc.response.status_code
            return RAGResponse(
                question=question,
                answer="",
                latency_ms=latency,
                error=_safe_error(exc),
                error_type="http_status",
                status_code=status,
                retryable=status == 429 or status >= 500,
                retry_after_seconds=self._retry_after(exc.response),
            )
        except httpx.HTTPError as exc:
            latency = (time.perf_counter() - start) * 1000
            return RAGResponse(question=question, answer="", latency_ms=latency, error=_safe_error(exc), error_type="http_error", retryable=True)
        except (TypeError, ValueError, KeyError) as exc:
            latency = (time.perf_counter() - start) * 1000
            return RAGResponse(question=question, answer="", latency_ms=latency, error=_safe_error(exc), error_type="response_parse")

        data = data or {}
        mapped_answer = _dig(data, cfg.answer_path) if not answer else answer
        raw_contexts = _as_list(_dig(data, cfg.contexts_path))
        contexts: list[str] = []
        context_ids: list[str] = []
        for item in raw_contexts:
            if isinstance(item, str):
                contexts.append(item)
            elif isinstance(item, dict):
                mapped_text = _dig(item, cfg.context_text_path) if cfg.context_text_path else None
                contexts.append(str(mapped_text or item.get("text") or item.get("content") or item))
                if cfg.context_id_path:
                    cid = _dig(item, cfg.context_id_path)
                    if cid is not None:
                        context_ids.append(str(cid))
            else:
                contexts.append(str(item))
        raw_citations = _as_list(_dig(data, cfg.citations_path))
        citations: list[str] = []
        for citation in raw_citations:
            if isinstance(citation, dict):
                citation_id = _dig(citation, cfg.citation_id_path) if cfg.citation_id_path else None
                citation_text = _dig(citation, cfg.citation_text_path) if cfg.citation_text_path else None
                if citation_id is None:
                    citation_id = citation.get("id") or citation.get("document_id") or citation.get("doc_id")
                citations.append(str(citation_id if citation_id is not None else citation_text or citation))
            else:
                citations.append(str(citation))
        if isinstance(mapped_answer, list):
            mapped_answer = "".join(str(part) for part in mapped_answer)
        final_answer = str(mapped_answer) if mapped_answer is not None else ""
        latency = (time.perf_counter() - start) * 1000
        contract_error: str | None = None
        if len(final_answer) > cfg.max_answer_chars:
            contract_error = f"answer exceeded {cfg.max_answer_chars} characters"
        elif len(contexts) > cfg.max_contexts:
            contract_error = f"contexts exceeded maximum count {cfg.max_contexts}"
        elif any(len(context) > cfg.max_context_chars for context in contexts):
            contract_error = f"context exceeded {cfg.max_context_chars} characters"
        if contract_error:
            return RAGResponse(
                question=question,
                answer="",
                latency_ms=latency,
                error=contract_error,
                error_type="response_too_large",
            )
        fallback = _dig(data, cfg.fallback_path)
        if cfg.expected_fallback is not None and fallback is not cfg.expected_fallback:
            return RAGResponse(
                question=question,
                answer=final_answer,
                contexts=contexts,
                context_ids=context_ids,
                citations=citations,
                latency_ms=latency,
                error=f"response fallback flag must be {str(cfg.expected_fallback).lower()}",
                error_type="response_contract",
                raw=data if isinstance(data, dict) else None,
            )
        return RAGResponse(
            question=question,
            answer=final_answer,
            contexts=contexts,
            context_ids=context_ids,
            citations=citations,
            latency_ms=latency,
            first_token_latency_ms=first_token_latency,
            output_char_count=output_chars,
            streamed=cfg.stream,
            raw=data if isinstance(data, dict) else None,
        )

    def ask(self, question: str) -> RAGResponse:
        last_response: RAGResponse | None = None
        for attempt in range(self.config.retries + 1):
            last_response = self._one_request(question)
            if last_response.error is None:
                return last_response
            if not last_response.retryable:
                return last_response
            if attempt < self.config.retries:
                delay = last_response.retry_after_seconds
                if delay is None:
                    delay = self.config.retry_backoff * (2**attempt)
                if self.config.retry_jitter:
                    delay += random.uniform(0, self.config.retry_jitter * max(delay, 1.0))
                if delay:
                    time.sleep(min(delay, max(self.config.timeout, 60.0)))
        return last_response or RAGResponse(question=question, answer="", error="request failed", error_type="unknown")

    async def aask(self, question: str) -> RAGResponse:
        """Async-compatible adapter entry point for event-loop based callers."""
        return await asyncio.to_thread(self.ask, question)
