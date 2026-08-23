import json
import re
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import yaml
from click.testing import CliRunner
from pydantic import ValidationError

from ragproof.adapters.http import HTTPAdapter
from ragproof.cli import cli
from ragproof.config import AdapterConfig, JudgeConfig, RunConfig
from ragproof.dataset import Sample, load, validate_benchmark_manifest
from ragproof.metrics.citation import citation_span_overlap
from ragproof.metrics.embedding import _load_model, embedding_similarity
from ragproof.metrics.judge import Judge
from ragproof.policy import GatePolicy
from ragproof.privacy import redact_nested
from ragproof.report import render
from ragproof.schema import CURRENT_RUN_SCHEMA_VERSION, load_run
from ragproof.trend import recommend_from_history


def test_unknown_run_judge_and_sample_fields_are_rejected():
    with pytest.raises(ValidationError):
        RunConfig(dataset="data.jsonl", adapter=AdapterConfig(type="mock"), typo=True)
    with pytest.raises(ValidationError):
        JudgeConfig(typo=True)
    with pytest.raises(ValidationError):
        Sample(id="a", question="q", typo=True)
    assert AdapterConfig(type="plugin", plugin_option=True).model_extra == {"plugin_option": True}


def test_config_summary_is_recursive_secret_safe_and_path_independent(tmp_path):
    fingerprints = []
    for folder in (tmp_path / "one", tmp_path / "two"):
        folder.mkdir()
        (folder / "dataset.jsonl").write_text('{"id":"a","question":"q"}\n', encoding="utf-8")
        config_path = folder / "config.yaml"
        config_path.write_text(
            """dataset: dataset.jsonl
adapter:
  type: mock
  base_url: https://user:pass@example.test/path?api_key=secret-value
  headers: {Authorization: Bearer secret-value}
  extra_json:
    nested: {password: secret-value}
judge: {enabled: false}
""",
            encoding="utf-8",
        )
        config = RunConfig.load(config_path)
        summary_text = json.dumps(config.summary())
        assert "secret-value" not in summary_text
        assert "user:pass" not in summary_text
        assert str(folder) not in summary_text
        fingerprints.append(config.fingerprint_summary())
    assert fingerprints[0] == fingerprints[1]


def test_redaction_never_changes_provenance_hashes():
    digest = "1c059ddec8441026d7da42facf3bd30cba0daeab4630103972e553164350a72a"
    assert redact_nested({"dataset_sha256": digest})["dataset_sha256"] == digest


def test_run_redacts_every_persisted_output_surface(tmp_path):
    secret = "sk_example_abcdefghijklmnop"
    email = "owner@example.com"
    dataset = tmp_path / "private-dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "private",
                "question": f"Contact {email} using {secret}",
                "metadata": {"api_key": secret, "owner": email},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"dataset: {dataset}\nadapter:\n  type: mock\n  extra_json:\n    password: {secret}\njudge: {{enabled: false}}\n",
        encoding="utf-8",
    )
    run_path = tmp_path / "run.json"
    result = CliRunner().invoke(cli, ["run", "-c", str(config_path), "-o", str(run_path)])
    assert result.exit_code == 0, result.output
    for extension in ("html", "md", "csv"):
        destination = tmp_path / f"report.{extension}"
        render(run_path, destination)
        text = destination.read_text(encoding="utf-8")
        assert secret not in text and email not in text and str(tmp_path) not in text
    persisted = run_path.read_text(encoding="utf-8")
    assert secret not in persisted and email not in persisted and str(tmp_path) not in persisted
    run = json.loads(persisted)
    assert run["schema_version"] == CURRENT_RUN_SCHEMA_VERSION
    assert run["results"][0]["metadata"]["api_key"] == "***"


def test_schema_reader_migrates_legacy_and_rejects_future(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"aggregate":{},"results":[]}', encoding="utf-8")
    assert load_run(legacy)["schema_version"] == CURRENT_RUN_SCHEMA_VERSION
    future = tmp_path / "future.json"
    future.write_text(json.dumps({"schema_version": CURRENT_RUN_SCHEMA_VERSION + 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="newer"):
        load_run(future)


def test_citation_overlap_uses_context_ids_not_positions():
    score = citation_span_overlap(
        "target evidence",
        ["doc-b"],
        ["unrelated words", "target evidence"],
        ["doc-a", "doc-b"],
    )
    assert score == 1.0


def _http_adapter(handler, **updates):
    config = AdapterConfig(
        base_url="http://test",
        endpoint="/answer",
        method="POST",
        answer_path="answer",
        retry_jitter=0,
        **updates,
    )
    adapter = HTTPAdapter(config)
    adapter.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return adapter


def test_http_retries_only_transient_statuses_and_honors_retry_after(monkeypatch):
    calls = {"count": 0}

    def throttled(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"answer": "ok"})

    sleeps = []
    monkeypatch.setattr("ragproof.adapters.http.time.sleep", sleeps.append)
    response = _http_adapter(throttled, retries=1).ask("q")
    assert response.answer == "ok" and calls["count"] == 2 and sleeps == [2.0]

    calls["count"] = 0

    def bad_request(request):
        calls["count"] += 1
        return httpx.Response(400)

    response = _http_adapter(bad_request, retries=3).ask("q")
    assert response.status_code == 400 and not response.retryable and calls["count"] == 1


def test_http_faults_timeout_invalid_json_huge_body_and_truncated_sse():
    calls = {"count": 0}

    def timeout(request):
        calls["count"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    assert _http_adapter(timeout, retries=1).ask("q").error_type == "timeout"
    assert calls["count"] == 2

    invalid = _http_adapter(
        lambda request: httpx.Response(200, text="{broken", headers={"content-type": "application/json"})
    ).ask("q")
    assert invalid.error_type == "response_parse" and not invalid.retryable

    huge = _http_adapter(
        lambda request: httpx.Response(200, content=b"x" * 20), max_response_bytes=10
    ).ask("q")
    assert huge.error_type == "response_too_large"

    stream = _http_adapter(
        lambda request: httpx.Response(200, text="data: {broken\n", headers={"content-type": "text/event-stream"}),
        stream=True,
    ).ask("q")
    assert stream.error_type == "response_parse" and not stream.retryable


def test_http_response_contract_limits_contexts_and_answer():
    response = _http_adapter(
        lambda request: httpx.Response(200, json={"answer": "long", "contexts": ["a", "b"]}),
        contexts_path="contexts",
        max_answer_chars=3,
        max_contexts=1,
    ).ask("q")
    assert response.error_type == "response_too_large"


def test_judge_concurrency_cache_and_circuit_breaker_are_thread_safe(tmp_path):
    state = {"active": 0, "maximum": 0, "calls": 0}
    lock = threading.Lock()

    def success(request):
        with lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            state["calls"] += 1
        time.sleep(0.005)
        with lock:
            state["active"] -= 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "8"}}]})

    cache_path = tmp_path / "judge-cache.json"
    judge = Judge(JudgeConfig(cache_path=str(cache_path), max_concurrency=2, retries=0))
    judge.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(success))
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(lambda i: judge.answer_relevancy(f"q{i}", "a") == 0.8, range(12)))
    assert state["maximum"] <= 2
    assert isinstance(json.loads(cache_path.read_text(encoding="utf-8")), dict)
    judge.close()

    failures = {"calls": 0}

    def unavailable(request):
        failures["calls"] += 1
        return httpx.Response(500)

    circuit = Judge(JudgeConfig(cache_enabled=False, max_concurrency=1, max_failures=3, retries=0))
    circuit.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(unavailable))
    for index in range(10):
        circuit.answer_relevancy(str(index), "a")
    assert failures["calls"] == 3 and circuit.failures == 3 and circuit.circuit_open
    circuit.close()


def test_judge_prompt_token_and_character_limits_preserve_both_ends():
    judge = Judge(JudgeConfig(cache_enabled=False, max_prompt_tokens=24, max_prompt_chars=120))
    prompt = judge._prompt("answer_relevancy", question="HEAD " * 100, ground_truth="reference", answer="TAIL " * 100)
    assert "strict QA judge" in prompt and "TAIL" in prompt and "TRUNCATED BY RAGPROOF" in prompt
    assert len(prompt) <= 120
    assert len(re.findall(r"[\w\u4e00-\u9fff]+|[^\s\w]", prompt)) <= 24
    judge.close()


def test_embedding_model_is_cached_and_encoding_is_batched(monkeypatch):
    created = {"count": 0, "batches": []}

    class Vector:
        def __init__(self, value):
            self.value = value

        def __matmul__(self, other):
            return self.value * other.value

    class FakeModel:
        def __init__(self, name):
            created["count"] += 1

        def encode(self, values, normalize_embeddings=True):
            created["batches"].append(list(values))
            return [Vector(1.0) for _ in values]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeModel))
    _load_model.cache_clear()
    assert embedding_similarity("a", ["b", "c"], "fake") == 1.0
    assert embedding_similarity("d", ["e"], "fake") == 1.0
    assert created["count"] == 1 and created["batches"][0] == ["a", "b", "c"]
    _load_model.cache_clear()


def test_tabular_lists_are_parsed_and_xls_is_rejected(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        'id,question,ground_truths,relevant_doc_ids,tags,metadata,answerable\n'
        'a,q,"[""one"", ""two""]",doc1|doc2,zh;easy,"{""owner"": ""team""}",false\n',
        encoding="utf-8",
    )
    sample = load(csv_path)[0]
    assert sample.ground_truths == ["one", "two"]
    assert sample.relevant_doc_ids == ["doc1", "doc2"]
    assert sample.tags == ["easy", "zh"] and sample.metadata == {"owner": "team"} and not sample.answerable
    legacy = tmp_path / "data.xls"
    legacy.write_bytes(b"legacy")
    with pytest.raises(ValueError, match="not supported"):
        load(legacy)


def test_history_recommendation_uses_distribution_not_latest(tmp_path):
    paths = []
    for index, error_rate in enumerate((0.10, 0.20, 0.01)):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps({"aggregate": {"error_rate": error_rate}, "results": []}), encoding="utf-8")
        paths.append(path)
    recommendation = recommend_from_history(paths)
    assert recommendation["max_thresholds"]["error_rate"] > 0.1


def test_policy_is_shared_by_report_junit_and_sarif(tmp_path):
    run = {
        "sample_count": 2,
        "aggregate": {"recall@5": 0.8, "error_rate": 0.2},
        "groups": {"tags": {"zh": {"error_rate": 0.2}}},
        "coverage": {"fields": {"contexts": {"rate": 1.0}}, "metrics": {}},
        "provenance": {"dataset_sha256": "d", "config_sha256": "c", "selected_sample_ids_sha256": "s"},
        "results": [],
    }
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(json.dumps(run), encoding="utf-8")
    current.write_text(json.dumps(run), encoding="utf-8")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """thresholds: {recall@5: 0.7}
max_thresholds: {error_rate: 0.1}
min_deltas: {recall@5: -0.1}
max_relative_drops: {recall@5: 0.1}
group_max_thresholds: {tags:zh:error_rate: 0.1}
min_sample_count: 2
min_coverage: {contexts: 1.0}
required_fields: [contexts]
""",
        encoding="utf-8",
    )
    policy = GatePolicy.load(policy_path)
    assert policy.group_max_thresholds["tags:zh:error_rate"] == 0.1
    junit = render(current, tmp_path / "report.xml", baseline=baseline, policy=policy_path)
    sarif = render(current, tmp_path / "report.sarif", baseline=baseline, policy=policy_path)
    assert "ragproof.gates" in junit.read_text(encoding="utf-8")
    assert "ragproof.maximum" in sarif.read_text(encoding="utf-8")


def test_benchmark_manifest_and_composite_action_contract():
    assert validate_benchmark_manifest("examples/benchmark-manifest.json") == []
    with open(".github/actions/evaluate/action.yml", encoding="utf-8") as handle:
        action = yaml.safe_load(handle)
    for name in (
        "min-deltas",
        "max-relative-drops",
        "group-max-thresholds",
        "min-sample-count",
        "min-coverage",
        "allow-provenance-mismatch",
        "artifact-name",
    ):
        assert name in action["inputs"]
    assert {"run-json", "html-report", "junit-report", "sarif-report"} <= set(action["outputs"])
