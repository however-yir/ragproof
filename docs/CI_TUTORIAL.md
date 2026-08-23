# CI regression gate tutorial

1. Commit a known-good run as `runs/baseline.json`.
2. Start the RAG service in the workflow.
3. Run `ragproof run` against the same dataset.
4. Require the metrics that your adapter is expected to provide:

```bash
ragproof run -c examples/knowledgeops.yaml \
  --require-metric recall@5 \
  --require-metric citation_coverage \
  -o runs/current.json
```

5. Gate both the absolute floor and the allowed regression:

```bash
ragproof compare \
  --baseline runs/baseline.json \
  --current runs/current.json \
  --threshold 'recall@5=0.70' \
  --min-delta 'faithfulness=-0.03' \
  --max-relative-drop 'citation_coverage=5%'
```

You can gate slices independently so an overall average cannot hide a regression in a language or difficulty bucket:

```bash
ragproof compare \
  --baseline runs/baseline.json \
  --current runs/current.json \
  --group-threshold 'tags:zh:faithfulness=0.75' \
  --group-threshold 'difficulty:hard:recall@5=0.70'
```

6. Always upload `runs/current.json` and the HTML report. The report includes provenance fingerprints, data coverage, failed sample IDs, retrieved IDs, citation matches, context snippets, judge reasons, and a copy-failed-JSON control.

Baseline and current runs must use the same dataset, normalized configuration, and selected sample set. Use `--allow-provenance-mismatch` only when intentionally comparing different evaluation inputs.

Use `examples/github-actions.yml` as the starting point. Add secrets only in the workflow's environment and keep `.env` files out of git.

For new repositories, the bundled composite Action reduces the workflow to:

```yaml
- uses: however-yir/ragproof/.github/actions/evaluate@v0.4.1
  with:
    config: examples/knowledgeops.yaml
    baseline: runs/baseline.json
    thresholds: |
      recall@5=0.70
      faithfulness=0.75
    group-thresholds: |
      tags:zh:faithfulness=0.75
    required-metrics: |
      recall@5
      citation_coverage
```

The Action uploads the JSON and HTML report and appends a short summary to the GitHub Job Summary.

Pinning a release tag keeps the workflow reproducible. Security-sensitive consumers can replace `v0.4.1` with the tag's full commit SHA.
