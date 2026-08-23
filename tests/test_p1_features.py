import asyncio
import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from ragproof.adapters.http import HTTPAdapter
from ragproof.cli import cli
from ragproof.config import AdapterConfig, IdNormalizationConfig, JudgeConfig, RunConfig
from ragproof.metrics.answers import refusal_rate, semantic_similarity
from ragproof.metrics.judge import Judge
from ragproof.metrics.retrieval import ndcg_at_k, rank_sensitivity
from ragproof.normalization import normalize_id, normalize_relevance
from ragproof.probe import inspect_responses
from ragproof.runner import run
from ragproof.schema import load_run


def test_http_native_async_and_context_lifecycle(monkeypatch):
    async def scenario():
        active = 0
        maximum = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(200, json={"answer": request.url.path})

        adapter = HTTPAdapter(
            AdapterConfig(
                base_url="http://test",
                endpoint="/answer",
                async_max_concurrency=2,
            )
        )
        adapter._async_client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        )
        monkeypatch.setattr(asyncio, "to_thread", lambda *_args, **_kwargs: pytest.fail("used to_thread"))
        responses = await asyncio.gather(*(adapter.aask(str(index)) for index in range(6)))
        assert all(response.error is None for response in responses)
        assert maximum == 2
        client = adapter._async_client
        await adapter.aclose()
        assert client is not None and client.is_closed

    asyncio.run(scenario())


def test_sse_maps_answer_contexts_and_citations_across_events():
    async def scenario():
        body = "".join(
            [
                'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n',
                'data: {"contexts":[{"id":"doc-1","text":"grounding"}]}\n\n',
                'data: {"choices":[{"delta":{"content":"world"}}]}\n\n',
                'data: {"citations":[{"document_id":"doc-1"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        adapter = HTTPAdapter(
            AdapterConfig(
                base_url="http://test",
                endpoint="/stream",
                stream=True,
                contexts_path="contexts",
                context_id_path="id",
                context_text_path="text",
                citations_path="citations",
                citation_id_path="document_id",
            )
        )
        adapter._async_client = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        )
        response = await adapter.aask("question")
        assert response.answer == "hello world"
        assert response.contexts == ["grounding"]
        assert response.context_ids == ["doc-1"]
        assert response.citations == ["doc-1"]
        await adapter.aclose()

    asyncio.run(scenario())


def test_adapter_and_judge_sync_context_managers_close_clients():
    adapter = HTTPAdapter(AdapterConfig(base_url="http://test", endpoint="/answer"))
    with adapter as active_adapter:
        assert active_adapter is adapter
    assert adapter.client.is_closed

    judge = Judge(JudgeConfig(cache_enabled=False))
    with judge as active_judge:
        assert active_judge is judge
    assert judge.client.is_closed


def test_streaming_run_uses_jsonl_sink_without_embedded_results(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        "".join(
            json.dumps({"id": f"q{index}", "question": f"question {index}"}) + "\n"
            for index in range(7)
        ),
        encoding="utf-8",
    )
    output = tmp_path / "run.json"
    report = run(
        RunConfig(
            dataset=str(dataset),
            adapter=AdapterConfig(type="mock"),
            judge=JudgeConfig(enabled=False),
            batch_size=2,
            stream_results=True,
            result_sink="details.jsonl",
        ),
        output,
    )
    sink = tmp_path / "details.jsonl"
    assert report["sample_count"] == 7
    assert report["results"] == []
    assert report["results_jsonl"] == "details.jsonl"
    assert len(sink.read_text(encoding="utf-8").splitlines()) == 7
    assert report["coverage"]["fields"]["answers"]["rate"] == 1.0


def test_graded_qrels_normalization_refusal_and_rank_perturbation():
    ideal = ndcg_at_k(["high", "low"], {"high": 3, "low": 1}, 2)
    reversed_score = ndcg_at_k(["low", "high"], {"high": 3, "low": 1}, 2)
    assert ideal == 1.0
    assert reversed_score is not None and reversed_score < ideal
    assert rank_sensitivity(["high", "low"], {"high": 3, "low": 1}, 2) > 0

    config = IdNormalizationConfig(lowercase=True, strip_prefixes=["DOC-"])
    assert normalize_id("  DOC-Cafe\u0301 ", config) == "café"
    assert normalize_relevance({"DOC-A": 1, "doc-a": 3}, config) == {"a": 3.0}

    assert refusal_rate("blocked by policy", patterns=[r"blocked by policy"]) == 1.0
    assert refusal_rate(
        "not blocked by policy exception",
        patterns=[r"blocked by policy"],
        exceptions=[r"exception"],
    ) == 0.0
    assert refusal_rate("信息不足", language="zh") == 1.0


def test_semantic_similarity_warns_for_one_release_cycle():
    with pytest.warns(DeprecationWarning):
        assert semantic_similarity("same tokens", ["same tokens"]) == 1.0


def test_probe_confidence_uses_repeated_structure_and_ambiguity():
    payloads = [
        {"answer": "a", "contexts": [{"id": "1", "text": "one"}]},
        {"answer": "b", "contexts": [{"id": "2", "text": "two"}]},
    ]
    mapping = inspect_responses(payloads)
    assert mapping["validated_responses"] == 2
    assert 0.8 <= mapping["confidence"]["answer_path"] < 0.9
    assert mapping["confidence"]["context_id_path"] >= 0.9


def test_optional_dependency_extras_are_formalized():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    assert {"embedding", "excel", "parquet"}.issubset(extras)
    assert any(requirement.startswith("sentence-transformers") for requirement in extras["embedding"])
    assert any(requirement.startswith("openpyxl") for requirement in extras["excel"])
    assert any(requirement.startswith("pyarrow") for requirement in extras["parquet"])


def test_compare_json_is_machine_readable_on_pass_and_failure(tmp_path):
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "aggregate": {"recall@1": 1.0},
                "provenance": {
                    "dataset_sha256": "same",
                    "config_sha256": "same",
                    "selected_sample_ids_sha256": "same",
                },
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    passed = runner.invoke(
        cli,
        [
            "compare",
            "--baseline",
            str(run_path),
            "--current",
            str(run_path),
            "--threshold",
            "recall@1=1",
            "--json",
        ],
    )
    assert passed.exit_code == 0
    assert json.loads(passed.output)["passed"] is True

    failed = runner.invoke(
        cli,
        [
            "compare",
            "--baseline",
            str(run_path),
            "--current",
            str(run_path),
            "--threshold",
            "recall@1=2",
            "--json",
        ],
    )
    assert failed.exit_code == 1
    assert json.loads(failed.output)["passed"] is False


@pytest.mark.parametrize("version", ["v0.3.x", "v0.4.0", "v0.4.1"])
def test_historical_run_fixtures_migrate(version):
    run_artifact = load_run(Path("tests/fixtures/runs") / f"{version}.json")
    assert run_artifact["schema_version"] == 2
    assert run_artifact["aggregate"]
    assert run_artifact["results"]
