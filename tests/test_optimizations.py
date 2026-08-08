import json

import pytest

from click.testing import CliRunner

from ragproof.cli import cli
from ragproof.compare import (
    compare,
    load_threshold_policy,
    parse_group_max_thresholds,
    parse_group_thresholds,
    parse_max_thresholds,
    parse_relative_drops,
    parse_thresholds,
    recommend_max_thresholds,
    recommend_thresholds,
)
from ragproof.dataset import Sample, manifest, near_duplicate_questions, redact_text, stratified_sample, validate
from ragproof.metrics.answers import claim_support, context_diversity, context_redundancy, token_count, tokens_per_second, unanswerable_correctness
from ragproof.metrics.citation import citation_span_overlap
from ragproof.metrics.retrieval import rank_sensitivity
from ragproof.report import render
from ragproof.runner import _git_sha
from ragproof.trend import bootstrap_interval, find_first_regression, summarize_runs
from ragproof.adapters import build_adapter
from ragproof.config import AdapterConfig


def _run(path, *, value=0.5, sample_count=2):
    path.write_text(json.dumps({
        "name": "run",
        "sample_count": sample_count,
        "aggregate": {"error_rate": value, "recall@5": 1 - value},
        "coverage": {"fields": {"contexts": {"rate": 1.0}}, "metrics": {}},
        "provenance": {"dataset_sha256": "d", "config_sha256": "c", "selected_sample_ids_sha256": "s"},
        "results": [],
    }), encoding="utf-8")


def test_max_gate_and_policy_inputs(tmp_path):
    baseline, current = tmp_path / "baseline.json", tmp_path / "current.json"
    _run(baseline, value=0.1)
    _run(current, value=0.2)
    results, passed = compare(baseline, current, {}, max_thresholds=parse_max_thresholds(["error_rate<=0.3"]))
    assert passed
    assert results[0].direction == "lower"
    assert parse_group_max_thresholds(["tags:zh:error_rate<=0.3"]) == {("tags", "zh", "error_rate"): 0.3}
    policy = tmp_path / "policy.yaml"
    policy.write_text("thresholds:\n  recall@5: 0.7\n", encoding="utf-8")
    assert load_threshold_policy(policy)["thresholds"]["recall@5"] == 0.7
    _, passed = compare(baseline, current, {}, min_sample_count=2, min_coverage={"contexts": 1.0}, required_fields=["contexts"])
    assert passed
    assert parse_thresholds(["recall@5>=0.7"]) == {"recall@5": 0.7}
    assert parse_relative_drops(["error_rate=5%"]) == {"error_rate": 0.05}
    assert parse_group_thresholds(["tags:zh:recall@5=0.7"])
    assert recommend_thresholds(baseline)["recall@5"] == 0.855
    assert recommend_max_thresholds(baseline)["error_rate"] == 0.105
    _, failed = compare(baseline, current, {}, max_thresholds={"missing": 0.1})
    assert not failed
    with pytest.raises(ValueError):
        parse_max_thresholds(["invalid"])


def test_dataset_manifest_and_stratification(tmp_path):
    source = tmp_path / "data.jsonl"
    source.write_text('\n'.join([
        '{"id":"a","question":"same question","tags":["zh"]}',
        '{"id":"b","question":"same question again","tags":["en"]}',
        '{"id":"c","question":"different","tags":["zh"]}',
    ]) + "\n", encoding="utf-8")
    assert manifest(source)["sample_count"] == 3
    samples = [Sample.model_validate(json.loads(line)) for line in source.read_text().splitlines()]
    assert near_duplicate_questions(samples, threshold=0.5)
    assert {sample.tags[0] for sample in stratified_sample(samples, 2, dimension="tags", seed=1)} == {"en", "zh"}
    assert redact_text("mail x@y.example and sk_test_abcdefghijklmnop") == "mail [REDACTED_EMAIL] and [REDACTED_SECRET]"
    assert not validate(source)


def test_trend_bootstrap_and_report_formats(tmp_path):
    first, second = tmp_path / "1.json", tmp_path / "2.json"
    _run(first, value=0.1)
    _run(second, value=0.2)
    assert bootstrap_interval([1, 2, 3])
    assert summarize_runs([first, second])["run_count"] == 2
    assert find_first_regression([first, second], "error_rate", 0.15, maximum=True) == str(second)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(first.read_text(), encoding="utf-8")
    html = render(second, tmp_path / "comparison.html", baseline=baseline, max_thresholds=["error_rate<=0.3"])
    assert html.exists()
    junit = render(first, tmp_path / "report.xml")
    sarif = render(first, tmp_path / "report.sarif")
    assert junit.exists() and sarif.exists()


def test_cli_dataset_manifest(tmp_path):
    source = tmp_path / "data.jsonl"
    source.write_text('{"id":"a","question":"q"}\n', encoding="utf-8")
    result = CliRunner().invoke(cli, ["dataset-manifest", str(source), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["sample_count"] == 1


def test_cli_trend_bisect_and_judge_calibrate(tmp_path):
    first, second = tmp_path / "1.json", tmp_path / "2.json"
    _run(first, value=0.1)
    _run(second, value=0.2)
    runner = CliRunner()
    trend_output = tmp_path / "trend.json"
    assert runner.invoke(cli, ["trend", str(first), str(second), "-o", str(trend_output)]).exit_code == 0
    assert runner.invoke(cli, ["bisect", str(first), str(second), "--metric", "error_rate", "--threshold", "0.15", "--max"]).output.strip() == str(second)
    calibrated = runner.invoke(cli, ["judge-calibrate", "--score", "0.8", "--label", "1.0"])
    assert calibrated.exit_code == 0 and "mae" in calibrated.output


def test_deterministic_quality_helpers(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "test-sha")
    assert _git_sha() == "test-sha"
    assert token_count("中文 answer") == 2
    assert tokens_per_second("one two", 1000) == 2.0
    assert context_redundancy(["a b", "a c"]) > 0
    assert context_diversity(["a b", "a c"]) < 1
    assert claim_support("answer. unsupported.", ["answer is here"]) == 0.5
    assert unanswerable_correctness("无法回答", False) == 1.0
    assert citation_span_overlap("answer", ["doc"], ["answer evidence"])
    assert rank_sensitivity(["d2", "d1"], ["d1"], 2) >= 0


def test_adapter_preset_contracts():
    for name, endpoint in (("langserve", "/invoke"), ("llamaindex", "/query"), ("dify", "/v1/chat-messages"), ("openai", "/chat/completions")):
        adapter = build_adapter(AdapterConfig(type=name, base_url="http://localhost"))
        assert adapter.config.endpoint == endpoint
