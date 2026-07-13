"""Unit tests for deterministic metrics."""

from ragproof.metrics import (
    citation_coverage,
    citation_validity,
    hit_rate,
    mrr,
    precision_at_k,
    recall_at_k,
)


class TestRecallAtK:
    def test_full_recall(self):
        assert recall_at_k(["a", "b", "c"], ["a", "b"], k=3) == 1.0

    def test_partial_recall(self):
        assert recall_at_k(["a", "x", "y"], ["a", "b"], k=3) == 0.5

    def test_zero_recall(self):
        assert recall_at_k(["x", "y"], ["a"], k=2) == 0.0

    def test_k_cutoff(self):
        # "b" is retrieved but outside top-1
        assert recall_at_k(["a", "b"], ["b"], k=1) == 0.0

    def test_no_ground_truth_returns_none(self):
        assert recall_at_k(["a"], [], k=5) is None


class TestPrecisionAtK:
    def test_all_relevant(self):
        assert precision_at_k(["a", "b"], ["a", "b", "c"], k=2) == 1.0

    def test_half_relevant(self):
        assert precision_at_k(["a", "x"], ["a"], k=2) == 0.5

    def test_empty_retrieved(self):
        assert precision_at_k([], ["a"], k=5) == 0.0

    def test_no_ground_truth_returns_none(self):
        assert precision_at_k(["a"], [], k=5) is None


class TestMRR:
    def test_first_position(self):
        assert mrr(["a", "b"], ["a"]) == 1.0

    def test_second_position(self):
        assert mrr(["x", "a"], ["a"]) == 0.5

    def test_third_position(self):
        assert mrr(["x", "y", "a"], ["a"]) == 1.0 / 3

    def test_not_found(self):
        assert mrr(["x", "y"], ["a"]) == 0.0

    def test_no_ground_truth_returns_none(self):
        assert mrr(["a"], []) is None


class TestHitRate:
    def test_hit(self):
        assert hit_rate(["x", "a"], ["a"], k=2) == 1.0

    def test_miss_due_to_cutoff(self):
        assert hit_rate(["x", "a"], ["a"], k=1) == 0.0

    def test_no_ground_truth_returns_none(self):
        assert hit_rate(["a"], [], k=1) is None


class TestCitationMetrics:
    def test_coverage_with_citations(self):
        assert citation_coverage(["doc1"], ["ctx"]) == 1.0

    def test_coverage_without_citations(self):
        assert citation_coverage([], ["ctx"]) == 0.0

    def test_coverage_no_contexts_returns_none(self):
        assert citation_coverage(["doc1"], []) is None

    def test_validity_all_valid(self):
        assert citation_validity(["doc1", "doc2"], ["doc1", "doc2", "doc3"]) == 1.0

    def test_validity_half_valid(self):
        assert citation_validity(["doc1", "bogus"], ["doc1"]) == 0.5

    def test_validity_no_context_ids(self):
        assert citation_validity(["doc1"], []) == 0.0

    def test_validity_no_citations_returns_none(self):
        assert citation_validity([], ["doc1"]) is None
