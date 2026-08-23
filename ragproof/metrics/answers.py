"""Deterministic answer-quality helpers that do not require an embedding model."""

from __future__ import annotations

import re
import warnings
from collections import Counter

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_REFUSAL_PATTERNS = {
    "en": (
        r"\bi (?:do not|don't) know\b",
        r"\b(?:cannot|can't) answer\b",
        r"\bno (?:relevant )?information\b",
        r"\binsufficient (?:context|information)\b",
    ),
    "zh": (r"无法回答", r"不知道", r"没有相关信息", r"无法确定", r"信息不足"),
}


def normalize_answer(text: str) -> str:
    return " ".join(text.lower().strip().split())


def exact_match(answer: str, references: list[str]) -> float | None:
    if not references:
        return None
    normalized = normalize_answer(answer)
    return 1.0 if any(normalized == normalize_answer(reference) for reference in references) else 0.0


def lexical_token_f1(answer: str, references: list[str]) -> float | None:
    """Dependency-free token F1; this intentionally does not claim semantics."""
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


def semantic_similarity(answer: str, references: list[str]) -> float | None:
    """Deprecated compatibility alias for :func:`lexical_token_f1`."""
    warnings.warn(
        "semantic_similarity is a lexical token F1 proxy; use lexical_token_f1 or embedding_similarity",
        DeprecationWarning,
        stacklevel=2,
    )
    return lexical_token_f1(answer, references)


def is_empty_answer(answer: str) -> float:
    return 1.0 if not answer.strip() else 0.0


def refusal_rate(
    answer: str,
    answerable: bool = True,
    *,
    patterns: list[str] | None = None,
    exceptions: list[str] | None = None,
    language: str = "auto",
) -> float:
    """Per-sample refusal indicator; unanswerable samples are not penalized."""
    if not answerable:
        return 0.0
    lowered = answer.lower()
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in (exceptions or [])):
        return 0.0
    selected = list(patterns or [])
    if not selected:
        languages = ("en", "zh") if language == "auto" else (language,)
        selected = [pattern for name in languages for pattern in _REFUSAL_PATTERNS[name]]
    return 1.0 if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in selected) else 0.0


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
    """Approximate claim support using content coverage, phrases, and entities.

    This is intentionally deterministic and conservative; teams can replace it
    with a judge metric while keeping the same output field.
    """
    if not answer or not contexts:
        return None
    context_text = normalize_answer(" ".join(contexts))
    context_tokens = set(_TOKEN_RE.findall(context_text))
    stopwords = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to", "was", "were", "with"}
    claims = [part.strip() for part in re.split(r"[.!?。！？；;]+", answer) if part.strip()]
    if not claims:
        return 0.0
    supported = 0
    for claim in claims:
        tokens = [token for token in _TOKEN_RE.findall(normalize_answer(claim)) if token not in stopwords]
        if not tokens:
            continue
        coverage = sum(token in context_tokens for token in tokens) / len(tokens)
        phrases = [" ".join(tokens[index:index + 2]) for index in range(max(0, len(tokens) - 1))]
        phrase_match = len(tokens) == 1 and tokens[0] in context_tokens or any(phrase in context_text for phrase in phrases)
        entities = re.findall(r"\b(?:[A-Z][\w-]+|\d+(?:\.\d+)?)\b", claim)
        entities_match = all(normalize_answer(entity) in context_text for entity in entities)
        supported += coverage >= 0.6 and phrase_match and entities_match
    return supported / len(claims)


def unanswerable_correctness(
    answer: str,
    answerable: bool,
    *,
    patterns: list[str] | None = None,
    exceptions: list[str] | None = None,
    language: str = "auto",
) -> float:
    """Score refusal behavior: refuse unanswerable questions, answer others."""
    refused = refusal_rate(
        answer,
        answerable=True,
        patterns=patterns,
        exceptions=exceptions,
        language=language,
    ) == 1.0
    return 1.0 if (refused == (not answerable)) else 0.0
