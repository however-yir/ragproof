"""Baseline/current comparison and CI regression gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import yaml


LOWER_IS_BETTER = {
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


@dataclass
class ThresholdResult:
    metric: str
    threshold: float
    current: float | None
    baseline: float | None
    passed: bool
    reason: str
    kind: str = "absolute"
    actual: float | None = None
    direction: str = "higher"


def parse_thresholds(specs: list[str]) -> dict[str, float]:
    """Parse ``metric=0.8`` or ``metric>=0.8`` absolute gates."""
    out: dict[str, float] = {}
    for spec in specs:
        if ">=" in spec:
            name, val = spec.split(">=", 1)
        elif "=" in spec:
            name, val = spec.split("=", 1)
        else:
            raise ValueError(f"invalid threshold spec (expected name=value): {spec!r}")
        name = name.strip()
        if not name:
            raise ValueError(f"metric name is empty: {spec!r}")
        out[name] = float(val.strip())
    return out


def parse_max_thresholds(specs: Iterable[str]) -> dict[str, float]:
    """Parse ``metric<=0.2`` or ``metric=0.2`` lower-is-better gates."""
    out: dict[str, float] = {}
    for spec in specs:
        if "<=" in spec:
            name, val = spec.split("<=", 1)
        elif "=" in spec:
            name, val = spec.split("=", 1)
        else:
            raise ValueError(f"invalid maximum threshold spec (expected name<=value): {spec!r}")
        name = name.strip()
        if not name:
            raise ValueError(f"metric name is empty: {spec!r}")
        out[name] = float(val.strip())
    return out


def parse_relative_drops(specs: Iterable[str]) -> dict[str, float]:
    """Parse ``metric=5%`` or ``metric=0.05`` maximum relative drops."""
    out: dict[str, float] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"invalid relative-drop spec: {spec!r}")
        name, raw = spec.split("=", 1)
        raw = raw.strip()
        value = float(raw.removesuffix("%"))
        if raw.endswith("%"):
            value /= 100
        if value < 0:
            raise ValueError("relative drop must be non-negative")
        out[name.strip()] = value
    return out


def parse_group_thresholds(specs: Iterable[str]) -> dict[tuple[str, str, str], float]:
    """Parse ``dimension:value:metric=0.8`` group gates."""
    out: dict[tuple[str, str, str], float] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"invalid group threshold spec: {spec!r}")
        selector, raw_value = spec.split("=", 1)
        parts = selector.split(":", 2)
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ValueError("group threshold must be dimension:value:metric=number")
        dimension, group, metric = (part.strip() for part in parts)
        out[(dimension, group, metric)] = float(raw_value.strip())
    return out


def parse_group_max_thresholds(specs: Iterable[str]) -> dict[tuple[str, str, str], float]:
    """Parse ``dimension:value:metric<=number`` lower-is-better group gates."""
    out: dict[tuple[str, str, str], float] = {}
    for spec in specs:
        if "<=" in spec:
            selector, raw_value = spec.split("<=", 1)
        elif "=" in spec:
            selector, raw_value = spec.split("=", 1)
        else:
            raise ValueError(f"invalid group maximum threshold spec: {spec!r}")
        parts = selector.split(":", 2)
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ValueError("group maximum threshold must be dimension:value:metric<=number")
        dimension, group, metric = (part.strip() for part in parts)
        out[(dimension, group, metric)] = float(raw_value.strip())
    return out


def _one_absolute(metric: str, threshold: float, baseline: dict[str, float], current: dict[str, float]) -> ThresholdResult:
    cur_val = current.get(metric)
    base_val = baseline.get(metric)
    if cur_val is None:
        return ThresholdResult(metric, threshold, cur_val, base_val, False, f"metric '{metric}' missing from current run")
    passed = cur_val >= threshold
    reason = f"{cur_val:.3f} >= threshold {threshold:.3f}" if passed else f"{cur_val:.3f} < threshold {threshold:.3f}"
    return ThresholdResult(metric, threshold, cur_val, base_val, passed, reason, actual=cur_val)


def _one_max(metric: str, threshold: float, baseline: dict[str, float], current: dict[str, float]) -> ThresholdResult:
    cur_val = current.get(metric)
    base_val = baseline.get(metric)
    if cur_val is None:
        return ThresholdResult(metric, threshold, cur_val, base_val, False, f"metric '{metric}' missing from current run", "maximum", None, "lower")
    passed = cur_val <= threshold
    reason = f"{cur_val:.3f} <= maximum {threshold:.3f}" if passed else f"{cur_val:.3f} > maximum {threshold:.3f}"
    return ThresholdResult(metric, threshold, cur_val, base_val, passed, reason, "maximum", cur_val, "lower")


def _one_group_absolute(
    dimension: str,
    group: str,
    metric: str,
    threshold: float,
    baseline: dict,
    current: dict,
) -> ThresholdResult:
    label = f"{dimension}:{group}:{metric}"
    base_aggregate = baseline.get(dimension, {}).get(group, {})
    current_aggregate = current.get(dimension, {}).get(group, {})
    cur_val = current_aggregate.get(metric)
    base_val = base_aggregate.get(metric)
    if cur_val is None:
        return ThresholdResult(label, threshold, cur_val, base_val, False, f"group metric '{label}' missing from current run", "group")
    passed = cur_val >= threshold
    reason = f"{cur_val:.3f} >= threshold {threshold:.3f}" if passed else f"{cur_val:.3f} < threshold {threshold:.3f}"
    return ThresholdResult(label, threshold, cur_val, base_val, passed, reason, "group", cur_val)


def _one_group_max(
    dimension: str,
    group: str,
    metric: str,
    threshold: float,
    baseline: dict,
    current: dict,
) -> ThresholdResult:
    label = f"{dimension}:{group}:{metric}"
    base_aggregate = baseline.get(dimension, {}).get(group, {})
    current_aggregate = current.get(dimension, {}).get(group, {})
    cur_val = current_aggregate.get(metric)
    base_val = base_aggregate.get(metric)
    if cur_val is None:
        return ThresholdResult(label, threshold, cur_val, base_val, False, f"group metric '{label}' missing from current run", "group_maximum", None, "lower")
    passed = cur_val <= threshold
    reason = f"{cur_val:.3f} <= maximum {threshold:.3f}" if passed else f"{cur_val:.3f} > maximum {threshold:.3f}"
    return ThresholdResult(label, threshold, cur_val, base_val, passed, reason, "group_maximum", cur_val, "lower")


def _provenance_result(baseline: dict, current: dict, allow_mismatch: bool) -> ThresholdResult:
    baseline_provenance = baseline.get("provenance") or {}
    current_provenance = current.get("provenance") or {}
    keys = ("dataset_sha256", "config_sha256", "selected_sample_ids_sha256")
    mismatches = [
        key
        for key in keys
        if not baseline_provenance.get(key) or not current_provenance.get(key)
        or baseline_provenance.get(key) != current_provenance.get(key)
    ]
    for key in ("judge_prompt_version", "judge_prompt_sha256", "adapter_type"):
        if key in baseline_provenance and key in current_provenance and baseline_provenance.get(key) != current_provenance.get(key):
            mismatches.append(key)
    if not mismatches:
        return ThresholdResult("provenance", 0.0, 1.0, 1.0, True, "baseline and current run provenance match", "provenance", 1.0)
    status = "allowed" if allow_mismatch else "blocked"
    return ThresholdResult(
        "provenance",
        0.0,
        1.0 if allow_mismatch else 0.0,
        1.0,
        allow_mismatch,
        f"{status} provenance mismatch: {', '.join(mismatches)}",
        "provenance",
        1.0 if allow_mismatch else 0.0,
        "higher",
    )


def _sample_count_result(run: dict, minimum: int) -> ThresholdResult:
    actual = int(run.get("sample_count", 0) or 0)
    passed = actual >= minimum
    reason = f"sample count {actual} >= minimum {minimum}" if passed else f"sample count {actual} < minimum {minimum}"
    return ThresholdResult("sample_count", float(minimum), float(actual), None, passed, reason, "sample_count", float(actual), "higher")


def _coverage_result(run: dict, field: str, minimum: float) -> ThresholdResult:
    coverage = run.get("coverage", {})
    item = coverage.get("metrics", {}).get(field) or coverage.get("fields", {}).get(field) or {}
    actual = item.get("rate") if isinstance(item, dict) else None
    passed = actual is not None and actual >= minimum
    reason = (
        f"coverage {field} {actual:.1%} >= minimum {minimum:.1%}"
        if actual is not None and passed
        else f"coverage {field} {actual:.1%} < minimum {minimum:.1%}"
        if actual is not None
        else f"coverage '{field}' missing from run"
    )
    return ThresholdResult(f"coverage:{field}", minimum, actual, None, passed, reason, "coverage", actual, "higher")


def load_threshold_policy(path: str | Path) -> dict[str, object]:
    """Load a YAML/JSON policy file using the same names as ``compare`` args."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("threshold policy must be a mapping")
    return data


def compare(
    baseline_path: str | Path,
    current_path: str | Path,
    thresholds: dict[str, float],
    *,
    min_deltas: dict[str, float] | None = None,
    max_relative_drops: dict[str, float] | None = None,
    max_thresholds: dict[str, float] | None = None,
    group_thresholds: dict[tuple[str, str, str], float] | None = None,
    group_max_thresholds: dict[tuple[str, str, str], float] | None = None,
    min_sample_count: int | None = None,
    min_coverage: dict[str, float] | None = None,
    required_fields: Iterable[str] | None = None,
    allow_provenance_mismatch: bool = False,
) -> tuple[list[ThresholdResult], bool]:
    """Return results for all configured gates and a combined pass/fail value."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = json.loads(Path(current_path).read_text(encoding="utf-8"))
    b_agg: dict[str, float] = baseline.get("aggregate", {})
    c_agg: dict[str, float] = current.get("aggregate", {})
    results = [_one_absolute(metric, threshold, b_agg, c_agg) for metric, threshold in thresholds.items()]
    results.extend(_one_max(metric, threshold, b_agg, c_agg) for metric, threshold in (max_thresholds or {}).items())

    for metric, minimum_delta in (min_deltas or {}).items():
        cur_val = c_agg.get(metric)
        base_val = b_agg.get(metric)
        delta = cur_val - base_val if cur_val is not None and base_val is not None else None
        passed = delta is not None and delta >= minimum_delta
        reason = (
            f"delta {delta:+.3f} >= minimum {minimum_delta:+.3f}"
            if passed
            else f"delta {delta:+.3f} < minimum {minimum_delta:+.3f}"
            if delta is not None
            else f"metric '{metric}' missing from baseline or current run"
        )
        results.append(ThresholdResult(metric, minimum_delta, cur_val, base_val, passed, reason, "delta", delta))

    for metric, max_drop in (max_relative_drops or {}).items():
        cur_val = c_agg.get(metric)
        base_val = b_agg.get(metric)
        if cur_val is None or base_val is None:
            drop = None
            passed = False
            reason = f"metric '{metric}' missing from baseline or current run"
        elif base_val == 0:
            drop = 0.0 if cur_val >= 0 else 1.0
            passed = drop <= max_drop
            reason = f"relative drop {drop:.1%} {'<=' if passed else '>'} allowed {max_drop:.1%}"
        else:
            drop = (base_val - cur_val) / abs(base_val)
            passed = drop <= max_drop
            reason = f"relative drop {drop:.1%} {'<=' if passed else '>'} allowed {max_drop:.1%}"
        results.append(ThresholdResult(metric, max_drop, cur_val, base_val, passed, reason, "relative_drop", drop))
    for (dimension, group, metric), threshold in (group_thresholds or {}).items():
        results.append(
            _one_group_absolute(dimension, group, metric, threshold, baseline.get("groups", {}), current.get("groups", {}))
        )
    for (dimension, group, metric), threshold in (group_max_thresholds or {}).items():
        results.append(_one_group_max(dimension, group, metric, threshold, baseline.get("groups", {}), current.get("groups", {})))
    if min_sample_count is not None:
        results.append(_sample_count_result(current, min_sample_count))
    for field, minimum in (min_coverage or {}).items():
        results.append(_coverage_result(current, field, minimum))
    for field in required_fields or ():
        results.append(_coverage_result(current, field, 1.0))
    results.append(_provenance_result(baseline, current, allow_provenance_mismatch))
    return results, all(result.passed for result in results)


def recommend_thresholds(run_path: str | Path, *, floor: float = 0.95) -> dict[str, float]:
    """Suggest absolute gates at ``floor`` of each bounded baseline metric."""
    data = json.loads(Path(run_path).read_text(encoding="utf-8"))
    return {
        name: round(value * floor, 4)
        for name, value in data.get("aggregate", {}).items()
        if 0 <= value <= 1 and name not in LOWER_IS_BETTER
    }


def recommend_max_thresholds(run_path: str | Path, *, headroom: float = 1.05) -> dict[str, float]:
    """Suggest maximum gates for operational/error metrics."""
    data = json.loads(Path(run_path).read_text(encoding="utf-8"))
    return {
        name: round(value * headroom, 4)
        for name, value in data.get("aggregate", {}).items()
        if value >= 0 and name in LOWER_IS_BETTER
    }


def results_as_dicts(results: list[ThresholdResult]) -> list[dict[str, object]]:
    return [asdict(result) for result in results]
