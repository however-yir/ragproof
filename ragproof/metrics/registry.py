"""Single source of truth for metric semantics used by gates and trends."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    direction: str = "higher"
    minimum: float | None = 0.0
    maximum: float | None = 1.0
    unit: str = "ratio"
    availability: str = "per_sample"


_LOWER = {
    "avg_latency_ms",
    "p50_latency_ms",
    "p95_latency_ms",
    "avg_first_token_latency_ms",
    "p95_first_token_latency_ms",
    "error_rate",
    "empty_answer_rate",
    "refusal_rate",
    "hallucination_rate",
    "duplicate_rate",
    "negative_hit_rate",
    "context_redundancy",
}
_MILLISECONDS = {
    "avg_latency_ms",
    "p50_latency_ms",
    "p95_latency_ms",
    "avg_first_token_latency_ms",
    "p95_first_token_latency_ms",
}
_UNBOUNDED = {"output_token_count", "tokens_per_second"}
_PATTERN = re.compile(r"^(?:recall|precision|ndcg|map|hit_rate|rank_sensitivity)@\d+$")


def metric_spec(name: str) -> MetricSpec:
    if name in _MILLISECONDS:
        return MetricSpec("lower", 0.0, None, "milliseconds", "aggregate")
    if name in _LOWER:
        return MetricSpec("lower", 0.0, 1.0, "ratio")
    if name in _UNBOUNDED:
        return MetricSpec("higher", 0.0, None, "count" if name == "output_token_count" else "tokens_per_second")
    if _PATTERN.match(name):
        return MetricSpec()
    return MetricSpec()


def lower_is_better(name: str) -> bool:
    return metric_spec(name).direction == "lower"


def bounded_unit_interval(name: str) -> bool:
    spec = metric_spec(name)
    return spec.minimum == 0.0 and spec.maximum == 1.0
