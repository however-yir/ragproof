"""Deterministic citation metrics.

citation_coverage: did the answer cite anything at all when contexts existed?
citation_validity: fraction of citations that point at actually-retrieved docs.
"""

from __future__ import annotations


def citation_coverage(citations: list[str], contexts: list[str]) -> float | None:
    """1.0 if the answer carries at least one citation when contexts were retrieved."""
    if not contexts:
        return None
    return 1.0 if citations else 0.0


def citation_validity(citations: list[str], context_ids: list[str]) -> float | None:
    """Fraction of citations that reference a retrieved context id."""
    if not citations:
        return None
    if not context_ids:
        return 0.0
    known = set(context_ids)
    return sum(1 for c in citations if c in known) / len(citations)


def citation_precision(citations: list[str], context_ids: list[str]) -> float | None:
    """Alias with information-retrieval terminology for citation validity."""
    return citation_validity(citations, context_ids)


def citation_recall(citations: list[str], expected_citations: list[str]) -> float | None:
    """Fraction of expected citations that were emitted by the answer."""
    if not expected_citations:
        return None
    expected = set(expected_citations)
    return len(expected.intersection(citations)) / len(expected)


def citation_matches(citations: list[str], context_ids: list[str]) -> list[dict[str, str | bool]]:
    """Return per-citation evidence used by the report's explainability view."""
    known = set(context_ids)
    return [{"citation": citation, "valid": citation in known} for citation in citations]
