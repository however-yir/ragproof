# Dataset schema

The input is UTF-8 JSONL: one object per line. `id` and `question` are required.

| Field | Type | Purpose |
|---|---|---|
| `id` | string | Stable sample identifier used in reports and CI annotations |
| `question` | string | User question sent to the adapter |
| `ground_truth` | string | Backwards-compatible single reference answer |
| `ground_truths` | string[] | Multiple acceptable reference answers |
| `relevant_doc_ids` | string[] | Retrieval gold labels for recall, precision, MRR, NDCG and MAP |
| `relevance_scores` | object<string, number> | Optional non-negative graded qrels; NDCG uses the grades while binary metrics treat positive grades as relevant |
| `negative_doc_ids` | string[] | Documents that should not be retrieved |
| `expected_citations` | string[] | Citation recall gold labels |
| `tags` | string[] | Slices such as `billing`, `zh`, or `safety` |
| `difficulty` | string | A free-form difficulty bucket, e.g. `easy`, `hard` |
| `answerable` | boolean | Whether refusal should count as a failure signal |
| `metadata` | object | Domain-specific fields preserved by the dataset model |

Example:

```json
{"id":"q-001","question":"什么是 RAG？","ground_truths":["检索增强生成。","Retrieval-augmented generation."],"relevance_scores":{"doc-rag":3,"doc-intro":1},"expected_citations":["doc-rag"],"tags":["zh","intro"],"difficulty":"easy","answerable":true}
```

`ragproof validate -c ragproof.yaml` catches malformed JSONL, empty datasets, duplicate IDs, and duplicate questions before any API call.
