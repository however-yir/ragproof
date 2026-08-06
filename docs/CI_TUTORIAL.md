# CI regression gate tutorial

1. Commit a known-good run as `runs/baseline.json`.
2. Start the RAG service in the workflow.
3. Run `ragproof run` against the same dataset.
4. Gate both the absolute floor and the allowed regression:

```bash
ragproof compare \
  --baseline runs/baseline.json \
  --current runs/current.json \
  --threshold 'recall@5=0.70' \
  --min-delta 'faithfulness=-0.03' \
  --max-relative-drop 'citation_coverage=5%'
```

5. Always upload `runs/current.json` and the HTML report. The report includes failed sample IDs, retrieved IDs, citation matches, context snippets, judge reasons, and a copy-failed-JSON control.

Use `examples/github-actions.yml` as the starting point. Add secrets only in the workflow's environment and keep `.env` files out of git.
