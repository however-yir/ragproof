import json

from ragproof.compare import compare, parse_relative_drops


def _write(path, aggregate):
    path.write_text(json.dumps({"aggregate": aggregate}), encoding="utf-8")


def test_relative_drop_and_delta_gates(tmp_path):
    baseline, current = tmp_path / "baseline.json", tmp_path / "current.json"
    _write(baseline, {"faithfulness": 0.8})
    _write(current, {"faithfulness": 0.77})
    results, passed = compare(
        baseline,
        current,
        {},
        min_deltas={"faithfulness": -0.05},
        max_relative_drops=parse_relative_drops(["faithfulness=5%"]),
    )
    assert passed
    assert all(result.passed for result in results)


def test_relative_drop_failure(tmp_path):
    baseline, current = tmp_path / "baseline.json", tmp_path / "current.json"
    _write(baseline, {"m": 1.0})
    _write(current, {"m": 0.8})
    _, passed = compare(baseline, current, {}, max_relative_drops={"m": 0.1})
    assert not passed
