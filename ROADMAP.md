# Roadmap

## Shipped in 0.4.1

- Renamed the Python distribution to `ragproof-cli` to avoid the unrelated `ragproof` project on PyPI while keeping the `ragproof` import and command stable.
- Added wheel metadata checks, a clean-install release smoke test, dependency auditing, CodeQL, and safer community contribution templates.
- Added a reproducible public HTTP retrieval corpus, dataset, known-good baseline, and CI regression gate.

## Shipped in 0.4.0

- Lower-is-better and policy-file gates, expanded dataset governance, and richer provenance diagnostics.
- Multi-run trend summaries, bootstrap intervals, local regression bisect, and JUnit/SARIF output.
- Optional embedding similarity, multilingual tokenization, richer retrieval/citation metrics, and extended adapters.

## Shipped in 0.3.1

- Core CI coverage contracts: runner 80%, HTTP adapter 70%, comparison engine 85%, plus a 75% project floor.
- Tag releases validate the package version, attach source/wheel artifacts, and publish the matching CHANGELOG section to GitHub Releases.
- PyPI publication is deliberately opt-in until this repository has a verified PyPI package identity.

## Shipped in 0.3.0

- Run provenance fingerprints for dataset, normalized config, and selected sample set.
- Per-group absolute gates for tags and difficulty buckets.
- Metric/field coverage reports and required-metric completeness gates.
- Incremental streaming HTTP consumption with first-token latency.
- Structured citation object mapping and a 75% CI coverage floor.

## Shipped in 0.2.0

- Reliable run metadata, deterministic sampling, dataset slices, and schema validation.
- Deterministic retrieval/answer/citation metrics plus optional judge metrics.
- Explainable HTML/Markdown/CSV reports and absolute/delta/relative CI gates.
- HTTP presets, streaming, retries, auth, plugin entry points, and release automation.

## Next milestones

- Native OpenAI Assistants thread polling and more framework-specific adapters.
- Expand the public benchmark with Chinese, unanswerable, and citation-required slices.
- Publish first-party adapter examples and define compatibility contracts for third-party plugins.
- Bind the `ragproof-cli` PyPI Trusted Publisher and enable verified package publication.
- Explore hosted annotation integrations without weakening the local-first workflow.

When this roadmap becomes a GitHub Project, keep one issue per adapter or metric so adoption feedback can be connected to a concrete release milestone.
