## Checked-in baseline summary

| Field | Value |
|---|---:|
| Synthetic corpus | 75 CC0-1.0 documents |
| Synthetic questions | 60 English and Chinese samples |
| Answerable / unanswerable | 55 / 5 |
| `recall@3` | 1.000 |
| `mrr` | 1.000 |
| `ndcg@3` | 1.000 |
| `citation_validity` | 1.000 |
| `citation_recall` | 1.000 |
| `unanswerable_correctness` | 1.000 |
| `error_rate` | 0.000 |

Context and citation coverage are 55/60 (91.7%) because the five deliberately unanswerable samples return neither. The Pages workflow replaces this checked-in fallback with a complete current report, including provenance and per-sample evidence, before every deployment.
