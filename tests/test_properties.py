from hypothesis import given
from hypothesis import strategies as st

from ragproof.config import IdNormalizationConfig
from ragproof.dataset import Sample, near_duplicate_questions
from ragproof.metrics.retrieval import (
    average_precision_at_k,
    hit_rate,
    mrr,
    ndcg_at_k,
    precision_at_k,
    rank_sensitivity,
    recall_at_k,
)
from ragproof.normalization import normalize_id

DOC_IDS = st.lists(
    st.text(alphabet="abcde", min_size=1, max_size=4),
    min_size=1,
    max_size=8,
    unique=True,
)


@given(retrieved=DOC_IDS, relevant=DOC_IDS, k=st.integers(min_value=1, max_value=10))
def test_retrieval_metrics_stay_in_unit_interval(retrieved, relevant, k):
    metrics = (
        recall_at_k(retrieved, relevant, k),
        precision_at_k(retrieved, relevant, k),
        ndcg_at_k(retrieved, relevant, k),
        average_precision_at_k(retrieved, relevant, k),
        hit_rate(retrieved, relevant, k),
        mrr(retrieved, relevant),
        rank_sensitivity(retrieved, relevant, k),
    )
    assert all(value is None or 0.0 <= value <= 1.0 for value in metrics)


@given(value=st.text(max_size=80), lowercase=st.booleans())
def test_identifier_normalization_is_idempotent(value, lowercase):
    config = IdNormalizationConfig(lowercase=lowercase, strip_prefixes=["doc-"])
    once = normalize_id(value, config)
    assert normalize_id(once, config) == once


@given(question=st.text(alphabet="abcde ", min_size=1, max_size=50))
def test_near_duplicate_index_always_finds_exact_duplicates(question):
    normalized_question = question.strip() or "a"
    samples = [
        Sample(id="left", question=normalized_question),
        Sample(id="right", question=normalized_question),
    ]
    assert near_duplicate_questions(samples, threshold=0.9) == [("right", "left", 1.0)]
