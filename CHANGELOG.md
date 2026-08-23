# Changelog

## Unreleased

- Added versioned run artifacts, a packaged JSON Schema, legacy migration reads, and path-independent configuration fingerprints.
- Made persisted run artifacts recursively secret/PII-safe, with atomic run/cache writes and strict top-level, Judge, and dataset field validation.
- Corrected citation span matching to use context IDs and centralized metric direction/range metadata.
- Unified CLI, report, JUnit, SARIF, and Composite Action gates behind a validated `GatePolicy`, including full Action inputs, outputs, and configurable artifact names.
- Hardened HTTP retries, Retry-After handling, jitter, response size contracts, malformed streaming behavior, Judge concurrency/circuit state, and embedding model reuse.
- Corrected CSV/XLSX list-cell imports, rejected unsupported legacy XLS files, and added hash/license validation for the CC0 benchmark manifest.

## 0.4.1 — 2026-08-23

- Renamed the Python distribution to `ragproof-cli` while preserving the `ragproof` module and console command, preventing accidental installation of an unrelated PyPI project.
- Added package metadata checks and a clean-wheel smoke test to the release workflow.
- Added a reproducible public HTTP retrieval corpus, dataset, baseline, and CI gate; corrected the starter benchmark manifest's language labels.
- Added dependency auditing, CodeQL analysis, private-reporting guidance, and GitHub community templates.
- Pinned reusable Action documentation to `v0.4.1`, modernized the standalone workflow example, and clearly labeled the mock-generated sample report.

## 0.4.0 — 2026-08-08

- Added lower-is-better `--max` gates, reusable YAML policies, coverage/sample gates, provenance detail, and direction-aware recommendations.
- Added configurable `group_by`, stratified sampling, dataset manifests, CSV/JSON/XLSX/Parquet import hooks, PII/secret redaction, near-duplicate linting, and a starter benchmark manifest.
- Added claim-support, citation-span, context diversity/redundancy, rank-sensitivity, unanswerable-correctness, token throughput, judge agreement, and optional embedding similarity metrics.
- Added multi-run trend summaries with bootstrap intervals, local regression bisect, JUnit/SARIF output, side-by-side baseline samples, group heatmap data, and richer probe output.
- Added explicit missing-environment diagnostics, custom streaming token paths/done markers, async-compatible adapter calls, judge prompt fingerprints, and circuit-breaker limits.
- Extended the reusable GitHub Action and CI smoke gates with policy inputs, HTML/XML/SARIF artifacts, dataset lint, manifests, and trend output.

## 0.3.2 — 2026-08-08

- Added `ragproof probe` to inspect one HTTP JSON response and generate a safe starter adapter YAML.
- Probe output reports candidate answer, context, citation, and document-ID paths without printing response values or headers.

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
