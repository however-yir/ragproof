# Changelog

## 0.3.1 — 2026-08-08

- Added independent CI coverage floors for the runner (80%), HTTP adapter (70%), and comparison engine (85%).
- Added tag/version validation, source and wheel release assets, and changelog-backed GitHub Release notes.
- Made PyPI publication opt-in through the `RAGPROOF_PYPI_PUBLISH` repository variable until package ownership is verified.

## 0.3.0 — 2026-08-08

- Added dataset/config/sample-selection fingerprints and provenance-safe baseline comparison.
- Added per-tag and per-difficulty absolute regression gates.
- Added field/metric coverage reporting and `--require-metric` completeness gates.
- Added true streaming HTTP consumption with first-token latency and output character metrics.
- Added explicit citation object ID/text mapping for structured API responses.
- Added a 75% CI coverage floor and reproducibility details to generated reports.

## 0.2.0 — 2026-08-07

- Added validated datasets with tags, difficulty, multiple references, expected citations, and duplicate detection.
- Added NDCG/MAP, answer, citation recall, context utilization, refusal, and operational latency metrics.
- Added structured judge results, reasons, cache, retry/backoff, multi-model voting, and estimated cost.
- Added relative-drop and delta regression gates, `validate`, `init`, dry-run, filtering, JSON output, and CSV reports.
- Added HTTP request templates, bearer auth, wildcard response paths, streaming parsing, adapter presets, and plugin entry points.
- Added Python 3.10–3.12 CI, Ruff, coverage artifacts, Dependabot, release drafting, and PyPI trusted publishing configuration.
