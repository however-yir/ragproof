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


def token_count(text: str, *, tokenizer: str = "heuristic") -> int:
    """Count output tokens with a dependency-free or explicitly simple tokenizer."""
    if tokenizer == "chars":
        return len(text)
    if tokenizer == "whitespace":
        return len(text.split())
    return len(_TOKEN_RE.findall(normalize_answer(text)))


def tokens_per_second(text: str, latency_ms: float | None, *, tokenizer: str = "heuristic") -> float | None:
    if latency_ms is None or latency_ms <= 0:
        return None
    return token_count(text, tokenizer=tokenizer) / (latency_ms / 1000)


def context_redundancy(contexts: list[str]) -> float | None:
    """Fraction of context tokens repeated across retrieved chunks."""
    if not contexts:
        return None
    total = 0
    unique: set[str] = set()
    for context in contexts:
        tokens = _TOKEN_RE.findall(normalize_answer(context))
        total += len(tokens)
        unique.update(tokens)
    return 0.0 if total == 0 else 1.0 - len(unique) / total


def context_diversity(contexts: list[str]) -> float | None:
    """Inverse redundancy score; useful for spotting duplicate retrieval chunks."""
    redundancy = context_redundancy(contexts)
    return None if redundancy is None else 1.0 - redundancy


def claim_support(answer: str, contexts: list[str]) -> float | None:
    """Approximate claim-level support by sentence/token overlap.

    This is intentionally deterministic and conservative; teams can replace it
    with a judge metric while keeping the same output field.
    """
    if not answer or not contexts:
        return None
    context_tokens = set(_TOKEN_RE.findall(normalize_answer(" ".join(contexts))))
    claims = [part.strip() for part in re.split(r"[.!?。！？；;]+", answer) if part.strip()]
    if not claims:
        return 0.0
    supported = sum(bool(set(_TOKEN_RE.findall(normalize_answer(claim))) & context_tokens) for claim in claims)
    return supported / len(claims)


def unanswerable_correctness(answer: str, answerable: bool) -> float:
    """Score refusal behavior: refuse unanswerable questions, answer others."""
    refused = refusal_rate(answer, answerable=True) == 1.0
    return 1.0 if (refused == (not answerable)) else 0.0
