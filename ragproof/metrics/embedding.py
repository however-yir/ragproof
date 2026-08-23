"""Optional embedding-backed similarity without making embeddings a hard dependency."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Any

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@lru_cache(maxsize=4)
def _load_model(model_name: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("embedding similarity requires the optional 'sentence-transformers' package") from exc
    return SentenceTransformer(model_name)


def _model_lock(model_name: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(model_name, threading.Lock())


def embedding_similarity(answer: str, references: list[str], model_name: str) -> float | None:
    """Compute cosine similarity with sentence-transformers when installed."""
    if not references:
        return None
    model = _load_model(model_name)
    with _model_lock(model_name):
        vectors = model.encode([answer, *references], normalize_embeddings=True)
    scores = [float(vectors[0] @ vector) for vector in vectors[1:]]
    return max(scores, default=0.0)
