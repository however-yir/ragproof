# Architecture

```mermaid
flowchart LR
  D[JSONL dataset] --> V[Config and schema validation]
  V --> F[Tag filters and deterministic sampling]
  F --> A[HTTP / mock / plugin adapter]
  A --> R[answer + contexts + IDs + citations]
  R --> M[Deterministic metrics]
  R --> J[Optional judge cache / voting]
  M --> O[Run JSON]
  J --> O
  O --> C[Absolute / delta / relative compare]
  O --> H[HTML / Markdown / CSV report]
  C --> CI[CI exit code and annotations]
```

The run JSON is the stable interchange format. It intentionally records the package version, Git SHA, configuration summary, dataset size, timings, metric aggregates, group aggregates, and per-sample evidence so a later report can be rendered without re-running the RAG service. The top-level `schema_version` is migrated on read, and the packaged contract is published at [`ragproof/schemas/run.schema.json`](../ragproof/schemas/run.schema.json).
