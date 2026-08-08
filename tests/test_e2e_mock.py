"""End-to-end test: mock adapter -> run -> compare -> report."""

import json

from click.testing import CliRunner

from ragproof.cli import cli

DATASET = "\n".join(
    json.dumps(s, ensure_ascii=False)
    for s in [
        {"id": "q1", "question": "What is RAG?", "ground_truth": "Retrieval augmented generation.", "relevant_doc_ids": ["doc1"]},
        {"id": "q2", "question": "What is pgvector?", "ground_truth": "A Postgres vector extension.", "relevant_doc_ids": ["doc2", "doc3"]},
    ]
)

CONFIG_TMPL = """
name: e2e-test
dataset: {dataset}
adapter:
  type: mock
judge:
  enabled: false
top_k: 3
"""


def _setup(tmp_path):
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(DATASET, encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG_TMPL.format(dataset=dataset), encoding="utf-8")
    return config


def test_run_produces_report_json(tmp_path):
    config = _setup(tmp_path)
    out = tmp_path / "run.json"
    result = CliRunner().invoke(cli, ["run", "-c", str(config), "-o", str(out)])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sample_count"] == 2
    assert "recall@3" in data["aggregate"]
    assert data["aggregate"]["error_rate"] == 0.0
    assert len(data["results"]) == 2


def test_run_is_deterministic(tmp_path):
    config = _setup(tmp_path)
    out1, out2 = tmp_path / "r1.json", tmp_path / "r2.json"
    runner = CliRunner()
    assert runner.invoke(cli, ["run", "-c", str(config), "-o", str(out1)]).exit_code == 0
    assert runner.invoke(cli, ["run", "-c", str(config), "-o", str(out2)]).exit_code == 0
    a = json.loads(out1.read_text(encoding="utf-8"))["aggregate"]
    b = json.loads(out2.read_text(encoding="utf-8"))["aggregate"]
    assert a == b


def test_compare_gate_pass_and_fail(tmp_path):
    config = _setup(tmp_path)
    out = tmp_path / "run.json"
    runner = CliRunner()
    assert runner.invoke(cli, ["run", "-c", str(config), "-o", str(out)]).exit_code == 0

    # Gate that always passes (error_rate >= 0.0)
    ok = runner.invoke(
        cli,
        ["compare", "--baseline", str(out), "--current", str(out), "--threshold", "error_rate=0.0"],
    )
    assert ok.exit_code == 0, ok.output

    # Gate that cannot pass (recall@3 = 1.01 impossible)
    fail = runner.invoke(
        cli,
        ["compare", "--baseline", str(out), "--current", str(out), "--threshold", "recall@3=1.01"],
    )
    assert fail.exit_code == 1


def test_report_html_and_md(tmp_path):
    config = _setup(tmp_path)
    out = tmp_path / "run.json"
    runner = CliRunner()
    assert runner.invoke(cli, ["run", "-c", str(config), "-o", str(out)]).exit_code == 0

    html = tmp_path / "report.html"
    md = tmp_path / "report.md"
    assert runner.invoke(cli, ["report", str(out), "-o", str(html)]).exit_code == 0
    assert runner.invoke(cli, ["report", str(out), "-o", str(md)]).exit_code == 0
    assert "<html" in html.read_text(encoding="utf-8")
    assert "Aggregate Metrics" in md.read_text(encoding="utf-8")


def test_run_records_provenance_and_coverage(tmp_path):
    config = _setup(tmp_path)
    out = tmp_path / "run.json"
    result = CliRunner().invoke(cli, ["run", "-c", str(config), "-o", str(out)])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["provenance"]["dataset_sha256"]) == 64
    assert data["coverage"]["fields"]["answers"]["rate"] == 1.0
    assert data["coverage"]["metrics"]["recall@3"]["rate"] == 1.0


def test_required_metric_fails_with_report(tmp_path):
    config = _setup(tmp_path)
    config.write_text(config.read_text(encoding="utf-8") + "required_metrics: [faithfulness]\n", encoding="utf-8")
    out = tmp_path / "run.json"
    result = CliRunner().invoke(cli, ["run", "-c", str(config), "-o", str(out)])
    assert result.exit_code == 1
    assert out.exists()
    assert "faithfulness" in result.output
