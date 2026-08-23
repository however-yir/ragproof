# 30-second offline quickstart

This flow creates a starter dataset and mock configuration, evaluates one sample, checks a gate, and renders a report. It does not call a model or external API.

## Install the verified release tag

This project requires Python 3.10 or newer. Check with `python --version` before installing.

```bash
python -m pip install "git+https://github.com/however-yir/ragproof.git@v0.4.1"
```

The distribution name is `ragproof-cli`, while the import package and command remain `ragproof`. Do not run `pip install ragproof`: that PyPI name belongs to an unrelated project. Until the `ragproof-cli` Trusted Publisher is active, the fixed Git tag above is the supported install path.

## Create and run an evaluation

```bash
mkdir ragproof-demo
cd ragproof-demo

ragproof init ragproof.yaml
ragproof validate -c ragproof.yaml
ragproof run -c ragproof.yaml -o current.json
```

`init` creates both `ragproof.yaml` and `dataset.jsonl`. The starter configuration uses the deterministic mock adapter.

## Exercise the regression gate

```bash
ragproof compare \
  --baseline current.json \
  --current current.json \
  --max "error_rate<=0.0"
```

Using the same run as baseline and current only verifies that the command, artifact reader, and exit-code path work. It is not a quality benchmark. In a real project, commit a reviewed known-good run as the baseline and compare later runs against it.

## Render the report

```bash
ragproof report current.json -o report.html --open
```

The same command can produce Markdown, CSV, JUnit XML, or SARIF by changing the output extension.

## Connect a real RAG API

1. Start from the [adapter guide](ADAPTERS.md) or run `ragproof probe` against a safe test endpoint.
2. Add retrieval gold labels and expected citations using the [dataset schema](DATASET_SCHEMA.md).
3. Run the [CI tutorial](CI_TUTORIAL.md) to add absolute, regression, group, and coverage gates.
4. Keep secrets in environment variables; persistent run and report artifacts are recursively redacted when `redact_sensitive` is enabled.
