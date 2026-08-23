# Run artifact schema

Every `ragproof run` produces a versioned JSON artifact. Reports and comparisons read this artifact, so the RAG service does not need to be called again.

The current schema version is **2** and follows JSON Schema draft 2020-12.

[Open the canonical JSON Schema](https://github.com/however-yir/ragproof/blob/main/ragproof/schemas/run.schema.json){ .md-button .md-button--primary }

## Required top-level fields

| Field | Type | Purpose |
|---|---|---|
| `schema_version` | integer | Selects the compatible reader and migration path. |
| `aggregate` | object | Metric names mapped to numeric values or `null`. |
| `results` | array | Per-sample evidence, or an empty array in streaming-result mode. |
| `provenance` | object | Dataset, normalized configuration, and selected-sample fingerprints. |

Common optional fields include `name`, `sample_count`, and `results_jsonl`. When `stream_results` is enabled, `results_jsonl` points to the separately written per-sample JSONL sink while the main artifact stays bounded.

## Provenance contract

The schema requires these fingerprints inside `provenance`:

- `dataset_sha256`
- `config_sha256`
- `selected_sample_ids_sha256`

`compare` rejects incompatible provenance by default. This prevents a different dataset, configuration, or sample selection from being presented as an ordinary quality regression.

## Compatibility

Version 1 artifacts are migrated to the current in-memory view. Unknown future versions are rejected with an actionable error. Historical fixtures for 0.3.x, 0.4.0, and 0.4.1 protect compare and report compatibility in CI.

## Validate outside Python

```python
import json
from pathlib import Path

import jsonschema

schema = json.loads(Path("ragproof/schemas/run.schema.json").read_text())
run = json.loads(Path("runs/current.json").read_text())
jsonschema.validate(run, schema)
```

Inside Python, use `ragproof.schema.load_run()` so compatibility migrations are applied before consumption.
