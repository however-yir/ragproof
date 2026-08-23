# CLI reference

Run `ragproof COMMAND --help` for every option. All commands return a non-zero exit code for validation failures, evaluation errors that cannot be tolerated, or failed regression gates.

| Command | Purpose |
|---|---|
| `init` | Create a starter YAML configuration and JSONL dataset. |
| `validate` | Validate configuration and dataset structure without calling the RAG API. |
| `run` | Evaluate the selected dataset and write a versioned run artifact. |
| `compare` | Compare baseline and current runs; exit 1 when a gate fails. |
| `report` | Render HTML, Markdown, CSV, JUnit XML, or SARIF. |
| `probe` | Call an HTTP adapter and suggest response mappings without printing secrets or response content. |
| `dataset-lint` | Check schema, duplicate IDs/questions, and near duplicates. |
| `dataset-manifest` | Print a stable dataset fingerprint and summary. |
| `benchmark-manifest-lint` | Verify benchmark paths, hashes, schemas, and license evidence. |
| `trend` | Summarize multiple runs with bootstrap confidence intervals. |
| `bisect` | Find the first run file that crosses a threshold. |
| `threshold-recommend` | Recommend conservative gates from a run history. |
| `judge-check` | Check an optional judge endpoint and structured score parsing. |
| `judge-calibrate` | Measure judge calibration against supplied golden labels. |

## Core workflow

```bash
ragproof validate -c ragproof.yaml
ragproof run -c ragproof.yaml -o runs/current.json
ragproof compare \
  --baseline runs/baseline.json \
  --current runs/current.json \
  --threshold "recall@5=0.70" \
  --max "error_rate<=0.05" \
  --max-relative-drop "citation_coverage=5%"
ragproof report runs/current.json -o runs/report.html
```

## Gate families

| Option | Meaning |
|---|---|
| `--threshold metric=value` | Minimum absolute value for higher-is-better metrics. |
| `--max metric<=value` | Maximum absolute value for lower-is-better metrics. |
| `--min-delta metric=value` | Minimum allowed current-minus-baseline change. |
| `--max-relative-drop metric=5%` | Maximum allowed proportional drop. |
| `--group-threshold dimension:value:metric=value` | Minimum threshold for one tag or difficulty slice. |
| `--group-max dimension:value:metric<=value` | Maximum threshold for one slice. |
| `--min-coverage field=value` | Minimum availability for a field or metric. |
| `--require-field field` | Require complete availability. |
| `--min-sample-count count` | Reject undersized current runs. |
| `--policy path` | Load the same gate model from YAML or JSON. |

Baseline and current artifacts must have compatible provenance unless `--allow-provenance-mismatch` is explicitly supplied.

## Dataset tools

```bash
ragproof dataset-lint dataset.jsonl
ragproof dataset-manifest dataset.jsonl --json
ragproof benchmark-manifest-lint examples/benchmark-manifest.json
```

See the [dataset reference](DATASET_SCHEMA.md) for supported fields and input formats.
