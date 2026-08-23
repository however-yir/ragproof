import json

from ragproof.adapters.base import RAGResponse
from ragproof.config import AdapterConfig
from ragproof.probe import inspect_response, render_config


def test_probe_finds_nested_paths_and_relative_ids():
    payload = {
        "data": {
            "answer": "ok",
            "contexts": [{"id": "doc-1", "text": "context"}],
            "citations": [{"document": {"id": "doc-1"}}],
        }
    }
    mapping = inspect_response(payload)
    assert mapping["answer_path"] == "data.answer"
    assert mapping["contexts_path"] == "data.contexts"
    assert mapping["context_id_path"] == "id"
    assert mapping["citations_path"] == "data.citations"
    assert mapping["citation_id_path"] == "document.id"


def test_probe_config_omits_secret_headers():
    mapping = {
        "answer_path": "data.answer",
        "contexts_path": "data.contexts",
        "context_id_path": "id",
        "citations_path": "data.citations",
        "citation_id_path": "document.id",
    }
    output = render_config(
        AdapterConfig(
            base_url="http://test",
            endpoint="/answer",
            method="POST",
            headers={"Authorization": "secret"},
        ),
        mapping,
    )
    assert "Authorization" not in output
    assert "data.answer" in output


def test_probe_cli_writes_yaml(monkeypatch, tmp_path):
    from click.testing import CliRunner

    import ragproof.adapters
    from ragproof.cli import cli

    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({"id": "q1", "question": "q"}) + "\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"dataset: {dataset}\nadapter:\n  type: http\n  base_url: http://test\n  endpoint: /answer\n  method: POST\n  json_field: query\n",
        encoding="utf-8",
    )
    starter = tmp_path / "probe.yaml"

    class FakeAdapter:
        def ask(self, question):
            return RAGResponse(
                question=question,
                answer="ok",
                latency_ms=1.0,
                raw={"answer": "ok", "contexts": [{"id": "doc-1", "text": "context"}]},
            )

    monkeypatch.setattr(ragproof.adapters, "build_adapter", lambda config: FakeAdapter())
    result = CliRunner().invoke(cli, ["probe", "-c", str(config), "-o", str(starter)])
    assert result.exit_code == 0, result.output
    assert "starter config written" in result.output
    assert "answer_path: answer" in starter.read_text(encoding="utf-8")
