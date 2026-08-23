"""Inspect one JSON response and suggest HTTP adapter mappings."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import yaml

from .adapters.http import _dig
from .config import AdapterConfig

_ANSWER_KEYS = {"answer", "answer_text", "content", "response", "text", "message"}
_CONTEXT_KEYS = {"context", "contexts", "documents", "docs", "retrieved", "retrieved_documents"}
_CITATION_KEYS = {"citation", "citations", "references", "sources"}
_ID_KEYS = {"chunk_id", "doc_id", "document_id", "id", "source_id"}
_TEXT_KEYS = {"text", "content", "page_content", "snippet"}


def _walk(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if path:
        yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _walk(child, child_path)
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        for key, child in value[0].items():
            child_path = f"{path}.*.{key}" if path else f"*.{key}"
            yield from _walk(child, child_path)


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower()


def _select_path(paths: list[tuple[str, Any]], keys: set[str], container: type) -> str | None:
    candidates = [(path, value) for path, value in paths if isinstance(value, container) and _leaf(path) in keys]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0].count("."), len(item[0])))
    return candidates[0][0]


def _select_scalar_path(paths: list[tuple[str, Any]], keys: set[str]) -> str | None:
    candidates = [(path, value) for path, value in paths if not isinstance(value, (dict, list)) and _leaf(path) in keys]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0].count("."), len(item[0])))
    return candidates[0][0]


def inspect_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Return candidate response paths without including response values."""
    return inspect_responses([payload])


def inspect_responses(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer mappings and evidence-based confidence across multiple responses."""
    if not payloads:
        raise ValueError("at least one response payload is required")
    payload = payloads[0]
    paths = list(_walk(payload))
    answer_candidates = [path for path, value in paths if not isinstance(value, (dict, list)) and _leaf(path) in _ANSWER_KEYS]
    context_candidates = [path for path, value in paths if isinstance(value, list) and _leaf(path) in _CONTEXT_KEYS]
    citation_candidates = [path for path, value in paths if isinstance(value, list) and _leaf(path) in _CITATION_KEYS]
    answer_path = _select_scalar_path(paths, _ANSWER_KEYS)
    contexts_path = _select_path(paths, _CONTEXT_KEYS, list)
    citations_path = _select_path(paths, _CITATION_KEYS, list)

    context_id_path = None
    context_text_path = None
    if contexts_path:
        items = _dig(payload, contexts_path)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            context_id_path = _select_scalar_path(list(_walk(items[0])), _ID_KEYS)
            context_text_path = _select_scalar_path(list(_walk(items[0])), _TEXT_KEYS)

    citation_id_path = None
    if citations_path:
        items = _dig(payload, citations_path)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            citation_id_path = _select_scalar_path(list(_walk(items[0])), _ID_KEYS)

    selected = {
        "answer_path": answer_path,
        "contexts_path": contexts_path,
        "citations_path": citations_path,
        "context_id_path": context_id_path,
        "context_text_path": context_text_path,
    }

    def observed(field: str, item: dict[str, Any]) -> bool:
        path = selected[field]
        if not path:
            return False
        if field in {"context_id_path", "context_text_path"} and contexts_path:
            contexts = _dig(item, contexts_path)
            return bool(
                isinstance(contexts, list)
                and contexts
                and isinstance(contexts[0], dict)
                and _dig(contexts[0], path) is not None
            )
        return _dig(item, path) is not None

    def confidence(field: str, candidates: list[str], *, structural: bool = False) -> float:
        path = selected[field]
        if not path:
            return 0.0
        repeated = sum(observed(field, item) for item in payloads) / len(payloads)
        ambiguity = max(0, len(candidates) - 1)
        score = 0.45 + 0.35 * repeated + (0.15 if structural else 0.1) - min(0.25, ambiguity * 0.08)
        return round(min(1.0, max(0.0, score)), 2)

    return {
        "answer_path": answer_path,
        "contexts_path": contexts_path,
        "context_id_path": context_id_path,
        "context_text_path": context_text_path,
        "citations_path": citations_path,
        "citation_id_path": citation_id_path,
        "candidates": {
            "answer_paths": answer_candidates,
            "contexts_paths": context_candidates,
            "citations_paths": citation_candidates,
        },
        "confidence": {
            "answer_path": confidence("answer_path", answer_candidates),
            "contexts_path": confidence("contexts_path", context_candidates, structural=True),
            "citations_path": confidence("citations_path", citation_candidates, structural=True),
            "context_id_path": confidence("context_id_path", [context_id_path] if context_id_path else []),
            "context_text_path": confidence("context_text_path", [context_text_path] if context_text_path else []),
        },
        "validated_responses": len(payloads),
    }


def render_config(adapter: AdapterConfig, mapping: dict[str, Any]) -> str:
    """Render a safe starter YAML without copying headers or secret values."""
    output_adapter: dict[str, Any] = {
        "type": "http",
        "base_url": adapter.base_url,
        "endpoint": adapter.endpoint,
        "method": adapter.method,
        "answer_path": mapping.get("answer_path") or adapter.answer_path,
    }
    for field in ("query_param", "json_field"):
        value = getattr(adapter, field)
        if value:
            output_adapter[field] = value
    if adapter.stream:
        output_adapter["stream"] = True
    if not adapter.query_param and not adapter.json_field and not adapter.request_template:
        output_adapter["request_template"] = {"question": "{{question}}"}
    for field in ("contexts_path", "context_id_path", "context_text_path", "citations_path", "citation_id_path", "citation_text_path"):
        value = mapping.get(field)
        if value:
            output_adapter[field] = value
    payload = {
        "name": "my-rag-probe",
        "dataset": "dataset.jsonl",
        "adapter": output_adapter,
        "judge": {"enabled": False},
    }
    return (
        "# Generated by ragproof probe. Copy authentication, request_template, and extra fields from the source config.\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    )
