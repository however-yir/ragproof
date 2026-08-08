"""Tests for regression comparison and threshold gating."""

import json

import pytest

from ragproof.compare import compare, parse_group_thresholds, parse_thresholds


def _write_run(path, aggregate, *, provenance=None, groups=None):
    path.write_text(
        json.dumps(
            {
                "aggregate": aggregate,
                "groups": groups or {},
                "provenance": provenance
                or {"dataset_sha256": "dataset", "config_sha256": "config", "selected_sample_ids_sha256": "samples"},
                "results": [],
            }
        ),
        encoding="utf-8",
    )


class TestParseThresholds:
    def test_basic(self):
        assert parse_thresholds(["faithfulness=0.8"]) == {"faithfulness": 0.8}

    def test_metric_with_at_sign(self):
        assert parse_thresholds(["recall@5=0.7"]) == {"recall@5": 0.7}

    def test_multiple(self):
        parsed = parse_thresholds(["a=0.1", "b=0.2"])
        assert parsed == {"a": 0.1, "b": 0.2}

    def test_invalid_spec_raises(self):
        with pytest.raises(ValueError):
            parse_thresholds(["nonsense"])

    def test_group_threshold(self):
        assert parse_group_thresholds(["tags:zh:faithfulness=0.8"]) == {("tags", "zh", "faithfulness"): 0.8}

    def test_invalid_group_threshold_raises(self):
        with pytest.raises(ValueError):
            parse_group_thresholds(["zh:faithfulness=0.8"])


class TestCompare:
    def test_all_pass(self, tmp_path):
        base = tmp_path / "base.json"
        cur = tmp_path / "cur.json"
        _write_run(base, {"recall@5": 0.7})
        _write_run(cur, {"recall@5": 0.85})
        results, ok = compare(base, cur, {"recall@5": 0.8})
        assert ok
        assert results[0].passed
        assert results[0].baseline == 0.7

    def test_below_threshold_fails(self, tmp_path):
        base = tmp_path / "base.json"
        cur = tmp_path / "cur.json"
        _write_run(base, {"faithfulness": 0.9})
        _write_run(cur, {"faithfulness": 0.5})
        results, ok = compare(base, cur, {"faithfulness": 0.8})
        assert not ok
        assert not results[0].passed

    def test_missing_metric_fails(self, tmp_path):
        base = tmp_path / "base.json"
        cur = tmp_path / "cur.json"
        _write_run(base, {})
        _write_run(cur, {})
        results, ok = compare(base, cur, {"faithfulness": 0.8})
        assert not ok
        assert "missing" in results[0].reason

    def test_exactly_at_threshold_passes(self, tmp_path):
        base = tmp_path / "base.json"
        cur = tmp_path / "cur.json"
        _write_run(base, {"mrr": 0.5})
        _write_run(cur, {"mrr": 0.8})
        _, ok = compare(base, cur, {"mrr": 0.8})
        assert ok

    def test_provenance_mismatch_blocks(self, tmp_path):
        base = tmp_path / "base.json"
        cur = tmp_path / "cur.json"
        _write_run(base, {"mrr": 0.8})
        _write_run(cur, {"mrr": 0.8}, provenance={"dataset_sha256": "different", "config_sha256": "config", "selected_sample_ids_sha256": "samples"})
        results, ok = compare(base, cur, {})
        assert not ok
        assert results[0].kind == "provenance"

    def test_group_threshold(self, tmp_path):
        base = tmp_path / "base.json"
        cur = tmp_path / "cur.json"
        groups = {"tags": {"zh": {"faithfulness": 0.9}}}
        _write_run(base, {"faithfulness": 0.9}, groups=groups)
        _write_run(cur, {"faithfulness": 0.9}, groups=groups)
        _, ok = compare(base, cur, {}, group_thresholds={("tags", "zh", "faithfulness"): 0.8})
        assert ok
