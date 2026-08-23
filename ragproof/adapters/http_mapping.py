"""Pure request/response mapping helpers for the generic HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import AdapterConfig


def dig(data: Any, path: str | None) -> Any:
    """Resolve dotted paths, numeric list indexes, and ``*`` list wildcards."""
    if not path:
        return None
    parts = path.split(".")

    def walk(current: Any, remaining: list[str]) -> Any:
        if not remaining:
            return current
        part = remaining[0]
        if part == "*" and isinstance(current, list):
            values = [walk(item, remaining[1:]) for item in current]
            return [value for value in values if value is not None]
        if isinstance(current, dict):
            return walk(current.get(part), remaining[1:]) if part in current else None
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            return walk(current[index], remaining[1:]) if index < len(current) else None
        return None

    return walk(data, parts)


def render_template(value: Any, question: str) -> Any:
    if isinstance(value, str):
        return value.replace("{{question}}", question).replace("{question}", question)
    if isinstance(value, dict):
        return {key: render_template(item, question) for key, item in value.items()}
    if isinstance(value, list):
        return [render_template(item, question) for item in value]
    return value


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


@dataclass(frozen=True)
class MappedResponse:
    answer: str
    contexts: list[str]
    context_ids: list[str]
    citations: list[str]
    fallback: Any = None
    raw: dict[str, Any] | None = None


def _last_value(payloads: list[dict[str, Any]], path: str | None) -> Any:
    for payload in reversed(payloads):
        value = dig(payload, path)
        if value is not None:
            return value
    return None


def map_response(
    payloads: list[dict[str, Any]],
    config: AdapterConfig,
    *,
    transported_answer: str = "",
) -> MappedResponse:
    """Map one JSON response or a sequence of SSE events into the public contract."""
    mapped_answer = transported_answer or _last_value(payloads, config.answer_path)
    if isinstance(mapped_answer, list):
        mapped_answer = "".join(str(part) for part in mapped_answer)

    raw_contexts: list[Any] = []
    raw_citations: list[Any] = []
    for payload in payloads:
        raw_contexts.extend(as_list(dig(payload, config.contexts_path)))
        raw_citations.extend(as_list(dig(payload, config.citations_path)))

    contexts: list[str] = []
    context_ids: list[str] = []
    for item in raw_contexts:
        if isinstance(item, str):
            contexts.append(item)
            continue
        if isinstance(item, dict):
            mapped_text = dig(item, config.context_text_path) if config.context_text_path else None
            contexts.append(str(mapped_text or item.get("text") or item.get("content") or item))
            if config.context_id_path:
                context_id = dig(item, config.context_id_path)
                if context_id is not None:
                    context_ids.append(str(context_id))
            continue
        contexts.append(str(item))

    citations: list[str] = []
    for citation in raw_citations:
        if isinstance(citation, dict):
            citation_id = dig(citation, config.citation_id_path) if config.citation_id_path else None
            citation_text = dig(citation, config.citation_text_path) if config.citation_text_path else None
            if citation_id is None:
                citation_id = citation.get("id") or citation.get("document_id") or citation.get("doc_id")
            citations.append(str(citation_id if citation_id is not None else citation_text or citation))
        else:
            citations.append(str(citation))

    raw = payloads[-1] if payloads else None
    return MappedResponse(
        answer=str(mapped_answer) if mapped_answer is not None else "",
        contexts=contexts,
        context_ids=context_ids,
        citations=citations,
        fallback=_last_value(payloads, config.fallback_path),
        raw=raw,
    )


def validate_contract(mapped: MappedResponse, config: AdapterConfig) -> str | None:
    if len(mapped.answer) > config.max_answer_chars:
        return f"answer exceeded {config.max_answer_chars} characters"
    if len(mapped.contexts) > config.max_contexts:
        return f"contexts exceeded maximum count {config.max_contexts}"
    if any(len(context) > config.max_context_chars for context in mapped.contexts):
        return f"context exceeded {config.max_context_chars} characters"
    if config.expected_fallback is not None and mapped.fallback is not config.expected_fallback:
        return f"response fallback flag must be {str(config.expected_fallback).lower()}"
    return None

