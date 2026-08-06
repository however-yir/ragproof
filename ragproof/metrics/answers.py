"""Deterministic answer-quality helpers that do not require an embedding model."""

from __future__ import annotations

import re
from collections import Counter

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_REFUSAL_PATTERNS = (
    "i don't know",
    "i do not know",
    "cannot answer",
    "can't answer",
    "no information",
    "无法回答",
    "不知道",
    "没有相关信息",
    "无法确定",
)


def normalize_answer(text: str) -> str:
    return " ".join(text.lower().strip().split())


def exact_match(answer: str, references: list[str]) -> float | None:
    if not references:
        return None
    normalized = normalize_answer(answer)
    return 1.0 if any(normalized == normalize_answer(reference) for reference in references) else 0.0


def semantic_similarity(answer: str, references: list[str]) -> float | None:
    """A dependency-free token F1 proxy; use an embedding metric for deep semantics."""
    if not references:
        return None
    answer_tokens = Counter(_TOKEN_RE.findall(normalize_answer(answer)))
    best = 0.0
    for reference in references:
        ref_tokens = Counter(_TOKEN_RE.findall(normalize_answer(reference)))
        overlap = sum((answer_tokens & ref_tokens).values())
        if not answer_tokens or not ref_tokens:
            score = 1.0 if answer_tokens == ref_tokens else 0.0
        else:
            precision = overlap / sum(answer_tokens.values())
            recall = overlap / sum(ref_tokens.values())
            score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        best = max(best, score)
    return best


def is_empty_answer(answer: str) -> float:
    return 1.0 if not answer.strip() else 0.0


def refusal_rate(answer: str, answerable: bool = True) -> float:
    """Per-sample refusal indicator; unanswerable samples are not penalized."""
    if not answerable:
        return 0.0
    lowered = answer.lower()
    return 1.0 if any(pattern in lowered for pattern in _REFUSAL_PATTERNS) else 0.0


def context_utilization(answer: str, contexts: list[str]) -> float | None:
    """Fraction of answer tokens that also occur in retrieved context text."""
    if not contexts:
        return None
    answer_tokens = set(_TOKEN_RE.findall(normalize_answer(answer)))
    context_tokens = set(_TOKEN_RE.findall(normalize_answer(" ".join(contexts))))
    if not answer_tokens:
        return 0.0
    return len(answer_tokens.intersection(context_tokens)) / len(answer_tokens)
