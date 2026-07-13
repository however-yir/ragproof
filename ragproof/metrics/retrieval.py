"""Deterministic retrieval metrics.

All functions take:
  retrieved: ordered list of retrieved doc ids
  relevant:  set/list of ground-truth relevant doc ids
"""

from __future__ import annotations


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    if not relevant:
        return None
    top = set(retrieved[:k])
    return sum(1 for d in relevant if d in top) / len(relevant)


def precision_at_k(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    if not relevant or k <= 0:
        return None
    top = retrieved[:k]
    if not top:
        return 0.0
    rel = set(relevant)
    return sum(1 for d in top if d in rel) / len(top)


def mrr(retrieved: list[str], relevant: list[str]) -> float | None:
    """Mean reciprocal rank of the first relevant hit (per-sample RR)."""
    if not relevant:
        return None
    rel = set(relevant)
    for i, d in enumerate(retrieved, start=1):
        if d in rel:
            return 1.0 / i
    return 0.0


def hit_rate(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    """1.0 if any relevant doc appears in top-k, else 0.0."""
    if not relevant:
        return None
    top = set(retrieved[:k])
    return 1.0 if any(d in top for d in relevant) else 0.0
