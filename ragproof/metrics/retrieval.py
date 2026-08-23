"""Deterministic retrieval metrics.

All functions take:
  retrieved: ordered list of retrieved doc ids
  relevant:  set/list of ground-truth relevant doc ids
"""

from __future__ import annotations

import math
import random

Relevance = list[str] | dict[str, float]


def _grades(relevant: Relevance) -> dict[str, float]:
    if isinstance(relevant, dict):
        return {doc_id: float(score) for doc_id, score in relevant.items() if score > 0}
    return dict.fromkeys(relevant, 1.0)


def recall_at_k(retrieved: list[str], relevant: Relevance, k: int) -> float | None:
    if not relevant:
        return None
    grades = _grades(relevant)
    top = set(retrieved[:k])
    return sum(1 for doc_id in grades if doc_id in top) / len(grades)


def precision_at_k(retrieved: list[str], relevant: Relevance, k: int) -> float | None:
    if not relevant or k <= 0:
        return None
    top = retrieved[:k]
    if not top:
        return 0.0
    rel = set(_grades(relevant))
    return sum(1 for d in top if d in rel) / len(top)


def mrr(retrieved: list[str], relevant: Relevance) -> float | None:
    """Mean reciprocal rank of the first relevant hit (per-sample RR)."""
    if not relevant:
        return None
    rel = set(_grades(relevant))
    for i, d in enumerate(retrieved, start=1):
        if d in rel:
            return 1.0 / i
    return 0.0


def hit_rate(retrieved: list[str], relevant: Relevance, k: int) -> float | None:
    """1.0 if any relevant doc appears in top-k, else 0.0."""
    if not relevant:
        return None
    top = set(retrieved[:k])
    return 1.0 if any(d in top for d in _grades(relevant)) else 0.0


def ndcg_at_k(retrieved: list[str], relevant: Relevance, k: int) -> float | None:
    """Normalized discounted cumulative gain for binary or graded qrels."""
    if not relevant or k <= 0:
        return None
    grades = _grades(relevant)
    dcg = sum(((2 ** grades.get(doc_id, 0.0) - 1) / math.log2(i + 2)) for i, doc_id in enumerate(retrieved[:k]))
    ideal = sum(
        (2 ** grade - 1) / math.log2(index + 2)
        for index, grade in enumerate(sorted(grades.values(), reverse=True)[:k])
    )
    return dcg / ideal if ideal else 0.0


def average_precision_at_k(retrieved: list[str], relevant: Relevance, k: int) -> float | None:
    """Average precision at k for binary document relevance."""
    if not relevant or k <= 0:
        return None
    rel = set(_grades(relevant))
    hits = 0
    score = 0.0
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in rel:
            hits += 1
            score += hits / rank
    return score / min(len(rel), k)


def duplicate_rate(retrieved: list[str]) -> float:
    """Fraction of retrieved slots that repeat an earlier document id."""
    if not retrieved:
        return 0.0
    return (len(retrieved) - len(set(retrieved))) / len(retrieved)


def rank_sensitivity(
    retrieved: list[str],
    relevant: Relevance,
    k: int,
    *,
    permutations: int = 16,
    seed: int = 42,
) -> float | None:
    """Mean NDCG change under deterministic position perturbations."""
    if not relevant or k <= 0:
        return None
    ordered = ndcg_at_k(retrieved, relevant, k)
    if ordered is None:
        return None
    top = retrieved[:k]
    if len(top) < 2:
        return 0.0
    rng = random.Random(seed)  # noqa: S311 - deterministic metric perturbations
    changes = []
    for _ in range(max(1, permutations)):
        shuffled = rng.sample(top, k=len(top))
        changes.append(abs(ordered - (ndcg_at_k(shuffled, relevant, k) or 0.0)))
    return sum(changes) / len(changes)
