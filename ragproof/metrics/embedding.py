"""Optional embedding-backed similarity without making embeddings a hard dependency."""

from __future__ import annotations

from typing import Any


def embedding_similarity(answer: str, references: list[str], model_name: str) -> float | None:
    """Compute cosine similarity with sentence-transformers when installed."""
    if not references:
        return None
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("embedding similarity requires the optional 'sentence-transformers' package") from exc
    model: Any = SentenceTransformer(model_name)
    vectors = model.encode([answer, *references], normalize_embeddings=True)
    scores = [float(vectors[0] @ vector) for vector in vectors[1:]]
    return max(scores, default=0.0)
