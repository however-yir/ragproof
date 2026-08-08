# Roadmap

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

- Multi-run trend reports with confidence intervals and bootstrap significance checks.
- Optional embedding-backed semantic similarity and multilingual tokenizer plugins.
- Native OpenAI Assistants thread polling and more framework-specific adapters.
- A public benchmark corpus and a GitHub Project with issue templates for adapter requests.

When this roadmap becomes a GitHub Project, keep one issue per adapter or metric so adoption feedback can be connected to a concrete release milestone.
