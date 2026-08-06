from ragproof.metrics import (
    average_precision_at_k,
    citation_recall,
    context_utilization,
    exact_match,
    ndcg_at_k,
    refusal_rate,
    semantic_similarity,
)


def test_ranking_metrics():
    assert ndcg_at_k(["a", "x", "b"], ["a", "b"], 3) > 0.8
    assert average_precision_at_k(["a", "x", "b"], ["a", "b"], 3) == 0.8333333333333333


def test_answer_metrics_and_unanswerable_refusal():
    assert exact_match("A correct answer", ["a correct answer"]) == 1.0
    assert semantic_similarity("RAG retrieves context", ["RAG retrieves useful context"]) > 0.5
    assert refusal_rate("I don't know", True) == 1.0
    assert refusal_rate("I don't know", False) == 0.0
    assert context_utilization("RAG context", ["This is a RAG context"]) == 1.0


def test_citation_recall():
    assert citation_recall(["doc1"], ["doc1", "doc2"]) == 0.5
