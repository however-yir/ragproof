"""Generic HTTP adapter with bounded sync and native async transports."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import random
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..config import AdapterConfig
from .base import RAGResponse
from .http_mapping import dig as _dig
from .http_mapping import map_response, render_template, validate_contract
from .http_stream import (
    ResponseTooLarge,
    StreamDecoder,
    consume_async_stream,
    consume_stream,
    read_async_limited,
    read_limited,
)

_JITTER_RANDOM = random.SystemRandom()


def _safe_error(exc: Exception) -> str:
    """Keep diagnostics useful without leaking query tokens or large bodies."""
    message = str(exc)[:500]
    return re.sub(
        r"(?i)(token|api[_-]?key|secret|password)=([^&\s]+)",
        r"\1=[REDACTED]",
        message,
    )


class HTTPAdapter:
    """Map arbitrary JSON/SSE RAG APIs to :class:`RAGResponse`."""

    def __init__(self, config: AdapterConfig):
        self.config = config
        self._headers = dict(config.headers)
        if config.bearer_token_env:
            token = os.environ.get(config.bearer_token_env)
            if token:
                self._headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(
            base_url=config.base_url,
            headers=self._headers,
            timeout=config.timeout,
        )
        self._async_client: httpx.AsyncClient | None = None
        self._async_semaphore = asyncio.Semaphore(config.async_max_concurrency)

    def __enter__(self) -> HTTPAdapter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    async def __aenter__(self) -> HTTPAdapter:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def close(self) -> None:
        """Close sync resources; async callers should prefer :meth:`aclose`."""
        self.client.close()

    async def aclose(self) -> None:
        self.client.close()
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=self._headers,
                timeout=self.config.timeout,
            )
        return self._async_client

    def _request_payload(self, question: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        config = self.config
        params = render_template(dict(config.extra_params), question)
        json_body: dict[str, Any] | None = None
        if config.request_template is not None:
            json_body = render_template(dict(config.request_template), question)
            json_body.update(render_template(dict(config.extra_json), question))
        elif config.extra_json or config.json_field:
            json_body = render_template(dict(config.extra_json), question)
        if config.query_param:
            params[config.query_param] = question
        if config.json_field:
            if json_body is None:
                json_body = {}
            json_body[config.json_field] = question
        if config.stream and json_body is not None:
            json_body.setdefault("stream", True)
        return params, json_body

    @staticmethod
    def _stream_payload(text: str) -> tuple[str, dict[str, Any] | None]:
        """Compatibility helper for callers that decode a buffered SSE body."""
        decoder = StreamDecoder(
            started=time.perf_counter(),
            token_path=None,
            done_markers={"[DONE]"},
            max_response_bytes=max(1, len(text.encode("utf-8")) + 1),
            max_answer_chars=max(1, len(text) + 1),
        )
        for line in text.splitlines():
            decoder.feed(line)
        result = decoder.finish()
        return result.answer, result.payloads[-1] if result.payloads else None

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

    def _decoder(self, started: float) -> StreamDecoder:
        return StreamDecoder(
            started=started,
            token_path=self.config.stream_token_path,
            done_markers=set(self.config.stream_done_markers),
            max_response_bytes=self.config.max_response_bytes,
            max_answer_chars=self.config.max_answer_chars,
        )

    def _map_result(
        self,
        question: str,
        started: float,
        payloads: list[dict[str, Any]],
        *,
        transported_answer: str = "",
        first_token_latency_ms: float | None = None,
        output_char_count: int | None = None,
    ) -> RAGResponse:
        mapped = map_response(payloads, self.config, transported_answer=transported_answer)
        contract_error = validate_contract(mapped, self.config)
        latency = (time.perf_counter() - started) * 1000
        if contract_error:
            fallback_error = (
                self.config.expected_fallback is not None
                and mapped.fallback is not self.config.expected_fallback
            )
            return RAGResponse(
                question=question,
                answer=mapped.answer if fallback_error else "",
                contexts=mapped.contexts if fallback_error else [],
                context_ids=mapped.context_ids if fallback_error else [],
                citations=mapped.citations if fallback_error else [],
                latency_ms=latency,
                error=contract_error,
                error_type="response_contract" if fallback_error else "response_too_large",
                raw=mapped.raw,
            )
        return RAGResponse(
            question=question,
            answer=mapped.answer,
            contexts=mapped.contexts,
            context_ids=mapped.context_ids,
            citations=mapped.citations,
            latency_ms=latency,
            first_token_latency_ms=first_token_latency_ms,
            output_char_count=output_char_count,
            streamed=self.config.stream,
            raw=mapped.raw,
        )

    def _parse_buffered(self, response: httpx.Response, content: bytes) -> tuple[str, list[dict[str, Any]]]:
        text = content.decode(response.encoding or "utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except ValueError:
            if "json" in response.headers.get("content-type", "").lower():
                raise ValueError("response declared JSON but could not be parsed") from None
            return text, []
        if not isinstance(parsed, dict):
            raise ValueError("JSON response must be an object")
        return "", [parsed]

    def _error_response(self, question: str, started: float, exc: Exception) -> RAGResponse:
        latency = (time.perf_counter() - started) * 1000
        if isinstance(exc, ResponseTooLarge):
            return RAGResponse(
                question=question,
                answer="",
                latency_ms=latency,
                error=str(exc),
                error_type="response_too_large",
            )
        if isinstance(exc, httpx.TimeoutException):
            return RAGResponse(
                question=question,
                answer="",
                latency_ms=latency,
                error=_safe_error(exc),
                error_type="timeout",
                retryable=True,
            )
        if isinstance(exc, httpx.HTTPStatusError):
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
        if isinstance(exc, httpx.HTTPError):
            return RAGResponse(
                question=question,
                answer="",
                latency_ms=latency,
                error=_safe_error(exc),
                error_type="http_error",
                retryable=True,
            )
        return RAGResponse(
            question=question,
            answer="",
            latency_ms=latency,
            error=_safe_error(exc),
            error_type="response_parse",
        )

    def _one_request(self, question: str) -> RAGResponse:
        config = self.config
        params, json_body = self._request_payload(question)
        started = time.perf_counter()
        try:
            with self.client.stream(
                config.method,
                config.endpoint,
                params=params or None,
                json=json_body,
            ) as response:
                response.raise_for_status()
                if config.stream:
                    stream = consume_stream(response, self._decoder(started))
                    return self._map_result(
                        question,
                        started,
                        stream.payloads,
                        transported_answer=stream.answer,
                        first_token_latency_ms=stream.first_token_latency_ms,
                        output_char_count=stream.output_char_count,
                    )
                answer, payloads = self._parse_buffered(
                    response,
                    read_limited(response, config.max_response_bytes),
                )
                return self._map_result(
                    question,
                    started,
                    payloads,
                    transported_answer=answer,
                    output_char_count=len(answer) if answer else None,
                )
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
            return self._error_response(question, started, exc)

    async def _one_async_request(self, question: str) -> RAGResponse:
        config = self.config
        params, json_body = self._request_payload(question)
        started = time.perf_counter()
        try:
            client = self._get_async_client()
            async with client.stream(
                config.method,
                config.endpoint,
                params=params or None,
                json=json_body,
            ) as response:
                response.raise_for_status()
                if config.stream:
                    stream = await consume_async_stream(response, self._decoder(started))
                    return self._map_result(
                        question,
                        started,
                        stream.payloads,
                        transported_answer=stream.answer,
                        first_token_latency_ms=stream.first_token_latency_ms,
                        output_char_count=stream.output_char_count,
                    )
                content = await read_async_limited(response, config.max_response_bytes)
                answer, payloads = self._parse_buffered(response, content)
                return self._map_result(
                    question,
                    started,
                    payloads,
                    transported_answer=answer,
                    output_char_count=len(answer) if answer else None,
                )
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
            return self._error_response(question, started, exc)

    def _retry_delay(self, response: RAGResponse, attempt: int) -> float:
        delay = response.retry_after_seconds
        if delay is None:
            delay = self.config.retry_backoff * (2**attempt)
        if self.config.retry_jitter:
            delay += _JITTER_RANDOM.uniform(0, self.config.retry_jitter * max(delay, 1.0))
        return min(delay, max(self.config.timeout, 60.0))

    def ask(self, question: str) -> RAGResponse:
        last_response: RAGResponse | None = None
        for attempt in range(self.config.retries + 1):
            last_response = self._one_request(question)
            if last_response.error is None or not last_response.retryable:
                return last_response
            if attempt < self.config.retries:
                delay = self._retry_delay(last_response, attempt)
                if delay:
                    time.sleep(delay)
        return last_response or RAGResponse(
            question=question,
            answer="",
            error="request failed",
            error_type="unknown",
        )

    async def aask(self, question: str) -> RAGResponse:
        """Run a request with native async I/O and bounded in-flight concurrency."""
        async with self._async_semaphore:
            last_response: RAGResponse | None = None
            for attempt in range(self.config.retries + 1):
                last_response = await self._one_async_request(question)
                if last_response.error is None or not last_response.retryable:
                    return last_response
                if attempt < self.config.retries:
                    delay = self._retry_delay(last_response, attempt)
                    if delay:
                        await asyncio.sleep(delay)
            return last_response or RAGResponse(
                question=question,
                answer="",
                error="request failed",
                error_type="unknown",
            )


__all__ = ["HTTPAdapter", "_dig", "_safe_error"]
