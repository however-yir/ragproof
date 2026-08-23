# Python extension API

The CLI and run artifact are the primary public contracts. The Python surface below exists for adapter plugins, controlled embedding, and artifact tooling. Prefer these focused entry points over importing private helpers.

## Adapter protocol

```python
from ragproof.adapters.base import RAGAdapter, RAGResponse


class MyAdapter:
    def ask(self, question: str) -> RAGResponse:
        return RAGResponse(
            question=question,
            answer="...",
            contexts=["..."],
            context_ids=["doc-1"],
            citations=["doc-1"],
        )
```

`RAGResponse` carries the normalized answer, contexts, context IDs, citations, timing, stream metadata, and safe error fields. Register a third-party adapter without changing ragproof:

```toml
[project.entry-points."ragproof.adapters"]
my_rag = "my_package:build_adapter"
```

The entry point receives the validated adapter configuration. See [Adapter guide](ADAPTERS.md) for built-in mappings and contract behavior.

## Configuration and execution

| Import | Role |
|---|---|
| `ragproof.config.RunConfig` | Validated top-level evaluation configuration; `RunConfig.load(path)` resolves the dataset relative to the config. |
| `ragproof.config.AdapterConfig` | HTTP, mock, preset, and plugin adapter options. |
| `ragproof.config.JudgeConfig` | Optional OpenAI-compatible judge settings and safety limits. |
| `ragproof.runner.run(config, output)` | Execute an evaluation and atomically write the run artifact. |
| `ragproof.policy.GatePolicy` | One validated model shared by compare, report, CLI, and the composite Action. |

Example:

```python
from ragproof.config import RunConfig
from ragproof.runner import run

config = RunConfig.load("ragproof.yaml")
artifact = run(config, "runs/current.json")
print(artifact["aggregate"])
```

## Run artifact helpers

```python
from ragproof.schema import load_run, migrate_run, validate_run
```

- `load_run(path)` reads JSON, validates the top-level contract, and migrates supported historical versions in memory.
- `validate_run(value)` accepts a decoded object and returns the current compatible view.
- `migrate_run(value)` preserves legacy fields while upgrading supported schema versions.

The on-disk contract is documented in [Run artifact schema](SCHEMA_REFERENCE.md). A schema newer than the installed package is rejected instead of being silently misread.

## Stability boundary

Modules and names prefixed with `_` are internal. Public CLI behavior, the plugin entry-point group, configuration models, and versioned run schema receive compatibility treatment; other Python helpers may evolve between minor releases.
