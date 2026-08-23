import json
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema

from ragproof.report import render


def _write_run(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "name": "report-contract",
                "sample_count": 1,
                "aggregate": {"error_rate": 0.0, "recall@1": 1.0},
                "provenance": {
                    "dataset_sha256": "dataset",
                    "config_sha256": "config",
                    "selected_sample_ids_sha256": "samples",
                },
                "results": [
                    {
                        "id": "unsafe",
                        "question": "<script>alert(1)</script>",
                        "answer": "<b>answer</b>",
                        "latency_ms": 10,
                        "metrics": {"recall@1": 1.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_run_sarif_junit_and_html_report_contracts(tmp_path):
    run_path = tmp_path / "run.json"
    _write_run(run_path)

    run_schema = json.loads(Path("ragproof/schemas/run.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(json.loads(run_path.read_text(encoding="utf-8")), run_schema)

    junit_path = render(run_path, tmp_path / "report.xml")
    suite = ET.parse(junit_path).getroot()
    assert suite.tag == "testsuite"
    assert suite.attrib["tests"] == "1"
    assert suite.find("testcase") is not None

    sarif_path = render(run_path, tmp_path / "report.sarif")
    sarif = json.loads(sarif_path.read_text(encoding="utf-8"))
    sarif_schema = json.loads(Path("tests/fixtures/sarif-core.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(sarif, sarif_schema)

    html_path = render(run_path, tmp_path / "report.html")
    html = html_path.read_text(encoding="utf-8")
    assert "<html" in html and "<table" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>answer</b>" not in html
