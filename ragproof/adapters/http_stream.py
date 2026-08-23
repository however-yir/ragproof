"""Bounded sync and async SSE decoders used by the HTTP adapter."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .http_mapping import dig


class ResponseTooLarge(ValueError):
    pass


@dataclass
class StreamResult:
    answer: str
    payloads: list[dict[str, Any]]
    first_token_latency_ms: float | None
    output_char_count: int


@dataclass
class StreamDecoder:
    started: float
    token_path: str | None
    done_markers: set[str]
    max_response_bytes: int
    max_answer_chars: int
    answer_parts: list[str] = field(default_factory=list)
    payloads: list[dict[str, Any]] = field(default_factory=list)
    first_token_latency_ms: float | None = None
    output_char_count: int = 0
    response_bytes: int = 0

    def feed(self, raw_line: str | bytes) -> None:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        self.response_bytes += len(line.encode("utf-8", errors="replace")) + 1
        if self.response_bytes > self.max_response_bytes:
            raise ResponseTooLarge(f"stream response exceeded {self.max_response_bytes} bytes")
        line = line.strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            return
        if line.startswith("data:event:"):
            return
        if line.startswith("data:data:"):
            line = line[len("data:data:") :].strip()
        elif line.startswith("data:"):
            line = line[5:].strip()
        if not line or line in self.done_markers:
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            if line.startswith(("{", "[")):
                raise ValueError("stream contained truncated or invalid JSON") from None
            token = line
        else:
            if not isinstance(payload, dict):
                return
            self.payloads.append(payload)
            token_value = dig(payload, self.token_path) if self.token_path else None
            token_value = token_value or dig(payload, "choices.0.delta.content") or dig(
                payload, "choices.0.message.content"
            )
            token = "" if token_value is None else str(token_value)
        if not token:
            return
        if self.first_token_latency_ms is None:
            self.first_token_latency_ms = (time.perf_counter() - self.started) * 1000
        self.answer_parts.append(token)
        self.output_char_count += len(token)
        if self.output_char_count > self.max_answer_chars:
            raise ResponseTooLarge(f"stream answer exceeded {self.max_answer_chars} characters")

    def finish(self) -> StreamResult:
        return StreamResult(
            answer="".join(self.answer_parts),
            payloads=self.payloads,
            first_token_latency_ms=self.first_token_latency_ms,
            output_char_count=self.output_char_count,
        )


def _check_declared_size(response: httpx.Response, limit: int, label: str) -> None:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ResponseTooLarge(f"{label} Content-Length exceeded {limit} bytes")


def consume_stream(response: httpx.Response, decoder: StreamDecoder) -> StreamResult:
    _check_declared_size(response, decoder.max_response_bytes, "stream")
    for line in response.iter_lines():
        decoder.feed(line)
    return decoder.finish()


async def consume_async_stream(response: httpx.Response, decoder: StreamDecoder) -> StreamResult:
    _check_declared_size(response, decoder.max_response_bytes, "stream")
    async for line in response.aiter_lines():
        decoder.feed(line)
    return decoder.finish()


def read_limited(response: httpx.Response, limit: int) -> bytes:
    _check_declared_size(response, limit, "response")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > limit:
            raise ResponseTooLarge(f"response exceeded {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def read_async_limited(response: httpx.Response, limit: int) -> bytes:
    _check_declared_size(response, limit, "response")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            raise ResponseTooLarge(f"response exceeded {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)

