# ragproof — RAG 评测与回归测试 CLI | RAG Evaluation & Regression Testing

[![CI](https://github.com/however-yir/ragproof/actions/workflows/ci.yml/badge.svg)](https://github.com/however-yir/ragproof/actions/workflows/ci.yml)
[![CodeQL](https://github.com/however-yir/ragproof/actions/workflows/codeql.yml/badge.svg)](https://github.com/however-yir/ragproof/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/however-yir/ragproof?display_name=tag)](https://github.com/however-yir/ragproof/releases)
[![Python](https://img.shields.io/badge/python-3.10--3.13-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **一句话**：框架无关的 RAG 质量评测工具。喂数据集 → 调你的 RAG API → 算指标 → 出报告 → CI 卡红线。
>
> **One line**: A framework-agnostic RAG evaluation harness. Feed a dataset → call your RAG API → compute metrics → render a report → gate CI on regressions.

RAG 系统最大的风险不是"跑不起来"，而是"改了一个 prompt、换了一个 chunk 策略、升级了一个模型之后，质量悄悄下降却没人知道"。`ragproof` 把 RAG 质量变成**可度量、可比较、可在 CI 中卡红线**的一等公民。

The hardest part of shipping RAG is not getting it to run — it is knowing that a prompt tweak, a chunking change, or a model upgrade silently degraded quality. `ragproof` makes RAG quality **measurable, comparable, and enforceable in CI**.

---

![ragproof mock-generated sample report](docs/assets/sample-report-screenshot.png)

> **Mock-generated demo:** this screenshot demonstrates report structure and UI; it is not evidence of production RAG quality. See the [reproducible public HTTP benchmark](docs/BENCHMARK.md) for a real retrieval gate.

## Features

| 能力 | 说明 |
|---|---|
| **接入探针** | `ragproof probe` 调用一次 HTTP API，发现答案 / 上下文 / 引用字段并生成安全的初始 YAML |
| **确定性检索指标** | `recall@k` / `precision@k` / `MRR` / graded `NDCG` / `hit_rate@k` — 不依赖任何 LLM，稳定可复现 |
| **引用溯源指标** | `citation_coverage`（有上下文时是否给出引用）/ `citation_validity`（引用是否指向真实检索结果） |
| **LLM-as-judge** | `faithfulness`（答案是否被上下文支撑 / 幻觉检测）/ `answer_relevancy`（答案是否切题），任何 OpenAI 兼容端点均可，**本地 Ollama 开箱即用** |
| **回归门禁** | `ragproof compare` 支持绝对阈值、低值上限、delta、相对下降、分组、样本数、coverage 和 YAML 策略文件 |
| **可比性保护** | run 自动记录数据集、配置和样本选择指纹；baseline 不匹配时默认阻断比较 |
| **分组门禁** | 可按 tags / difficulty 对中文、困难题、安全题等切片单独卡阈值 |
| **数据完整性** | 报告记录答案、上下文、引用和各指标的可用率，可用 `--require-metric` 防止 N/A 悄悄通过 |
| **流式性能** | 原生 AsyncClient、并发上限和多事件 SSE 映射；大型 JSONL 可分批评测并把逐样本结果流式写入独立 JSONL |
| **报告** | 一条命令生成 Markdown / HTML / CSV / JUnit XML / SARIF 报告，并可嵌入 baseline/current 样本对照 |
| **可解释性** | 失败样本排序、上下文片段、检索 ID、引用匹配、Judge 原因、复制失败 JSON |
| **分组分析** | 按 tags / difficulty 汇总，支持中文、英文、企业、安全数据切片 |
| **回归策略** | 绝对阈值、最小 delta、最大相对下降，支持 GitHub Actions 注释 |
| **工程化** | `validate` / `init` / dry-run / JSON / CSV / judge cache / 多模型投票 / provenance |
| **数据治理** | `dataset-lint` / `dataset-manifest`、近重复检测、分层抽样、CSV/JSON/XLSX/Parquet 导入、持久化产物递归脱敏 |
| **趋势分析** | `trend` bootstrap 置信区间、`bisect` 首个回归定位、分组热力数据 |
| **框架无关** | 通用 HTTP adapter，通过 YAML 声明请求/响应字段映射即可接入任何 RAG API（Spring AI / LangChain / LlamaIndex / 自研均可） |
| **优雅降级** | Judge 端点不可用时自动跳过 LLM 指标，确定性指标照常输出 |

## Quick Start

```bash
# 安装最新已验证发行版（GitHub Release tag）
pip install "git+https://github.com/however-yir/ragproof.git@v0.4.1"

# 或从源码安装（开发）
pip install -e ".[dev]"

# 按需安装，不把重依赖强加给基础 CLI
pip install -e ".[embedding]"  # sentence-transformers
pip install -e ".[excel]"      # openpyxl
pip install -e ".[parquet]"    # pandas + pyarrow
```

发行包名是 `ragproof-cli`，Python 导入名与命令仍是 `ragproof`。PyPI 上的 `ragproof` 属于无关项目，**不要运行 `pip install ragproof`**。在 `ragproof-cli` 的 Trusted Publisher 启用前，请使用上面的固定 Git tag 安装方式。每个 `vX.Y.Z` tag 都会校验版本、检查包元数据、在干净环境烟测 wheel，并创建带 CHANGELOG 摘要的 GitHub Release；详见 [发行说明](docs/RELEASING.md)。

**30 秒离线体验**（mock adapter，无需任何 RAG 系统或模型）：

```bash
ragproof run -c examples/mock.yaml -o runs/current.json
ragproof report runs/current.json -o report.html

# 对低值更好的指标设置上限，并复用策略文件
ragproof compare \
  --baseline runs/baseline.json --current runs/current.json \
  --max "error_rate<=0.10" \
  --max "p95_latency_ms<=1500" \
  --policy examples/threshold-policy.yaml

# 多次运行趋势、置信区间和首个回归文件
ragproof trend runs/*.json -o trend.json
ragproof bisect runs/*.json --metric recall@5 --threshold 0.70
open report.html
```

**评测真实系统**：

```bash
# 1. 声明你的 RAG API 怎么调、字段怎么映射（见 examples/knowledgeops.yaml）
ragproof run -c examples/knowledgeops.yaml -o runs/current.json

# 2. 与 baseline 对比，阈值不达标则 exit 1
ragproof compare \
  --baseline runs/baseline.json \
  --current  runs/current.json \
  --threshold "recall@5=0.70" \
  --threshold "faithfulness=0.75"

# 对中文切片单独卡门禁
ragproof compare \
  --baseline runs/baseline.json \
  --current runs/current.json \
  --group-threshold "tags:zh:faithfulness=0.75" \
  --group-threshold "difficulty:hard:recall@5=0.70"

# 要求关键指标对每个选中样本都可用
ragproof run -c examples/knowledgeops.yaml \
  --require-metric citation_coverage \
  --require-metric recall@5 \
  -o runs/current.json

# 同时限制相对回归和绝对变化
ragproof compare \
  --baseline runs/baseline.json --current runs/current.json \
  --min-delta "faithfulness=-0.03" \
  --max-relative-drop "citation_coverage=5%"

# 3. 生成报告
ragproof report runs/current.json -o report.html
```

**第一次接入未知 API**：

```bash
ragproof probe -c examples/knowledgeops.yaml \
  --question "What is RAG?" \
  -o probe.yaml
```

`probe` 只打印字段路径和延迟，不打印响应内容或请求头；生成的 `probe.yaml` 仍需补回认证和完整请求模板。

## How It Works

```
dataset.jsonl ──▶ adapter (HTTP/mock) ──▶ your RAG API
                        │
                        ▼
              answer + contexts + citations
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
  retrieval metrics  citation metrics  LLM-as-judge
  (recall@k, MRR…)   (coverage, valid) (faithfulness…)
        └───────────────┼────────────────┘
                        ▼
                 runs/current.json
                   │           │
                   ▼           ▼
          ragproof compare   ragproof report
          (CI gate, exit 1)  (Markdown / HTML)
```

## Dataset Format

每行一个 JSON（JSONL）；分级相关性可用 `relevance_scores`，未提供时 `relevant_doc_ids` 默认按 1.0 处理：

```json
{"id": "q001", "question": "什么是 RAG？", "ground_truth": "RAG 是...", "relevant_doc_ids": ["doc1"], "relevance_scores": {"doc1": 3, "doc2": 1}}
```

- `ground_truth` — 供 `answer_relevancy` judge 参考（可空）
- `relevant_doc_ids` — 供 `recall@k` / `MRR` 等检索指标使用（可空，为空时该指标记 N/A）

## Configuration

```yaml
name: my-rag-eval
dataset: examples/dataset.sample.jsonl

adapter:
  type: http
  base_url: http://localhost:8080
  endpoint: /ai/pdf/chat
  method: POST
  headers:
    X-API-Key: "${KNOWLEDGEOPS_API_KEY}"   # 支持 ${ENV_VAR} 展开
  json_field: message                       # 问题放进 JSON body 的哪个字段
  answer_path: data.answer                  # 从响应里取答案的 dotted path
  contexts_path: data.contexts              # 检索上下文列表
  context_id_path: docId                    # 每个上下文条目的 id 字段
  citations_path: data.citations            # 引用列表
  citation_id_path: document.id             # 引用对象的文档 ID（可选）
  fallback_path: fallback                   # 可选：明确的服务降级标记
  expected_fallback: false                  # 评测时拒绝 fallback=true 的回答
  bearer_token_env: KNOWLEDGEOPS_API_KEY    # 自动生成 Authorization: Bearer ...
  retries: 2                                # 仅 timeout / 网络错误 / 429 / 5xx 重试
  max_response_bytes: 10000000              # 读取阶段限制响应体
  max_answer_chars: 1000000
  max_contexts: 1000
  max_context_chars: 1000000
  async_max_concurrency: 20                 # aask 的原生异步在途请求上限

judge:
  base_url: http://localhost:11434/v1       # Ollama / 任何 OpenAI 兼容端点
  model: qwen2.5:7b
  skip_on_error: true                       # judge 不可用时跳过而非失败
  max_concurrency: 4                        # Judge 独立并发上限
  max_prompt_tokens: 30000                  # 启发式 token 上限，超限保留首尾
  max_prompt_chars: 120000                  # 字符级二次上限

top_k: 5
top_ks: [3, 5, 10]                          # 一次运行多个 k
concurrency: 4

# 可选数据切片
include_tags: [enterprise]
exclude_tags: [draft]
sample_limit: 100
seed: 42
required_metrics: [recall@5, citation_coverage]
redact_sensitive: true                      # 保存 run/report 前递归清理 secret 与常见 PII
id_normalization:
  lowercase: true
  strip_prefixes: ["doc:"]                  # 统一检索、qrels 与引用 ID
refusal_language: auto                       # auto / en / zh
refusal_patterns: []                         # 可追加自定义正则
refusal_exceptions: []                       # 命中后不视为拒答
batch_size: 100
stream_results: true                         # 主报告不内嵌逐样本大对象
result_sink: run-details.jsonl
```

未知的顶层、Judge 和数据集字段会直接报错，避免拼写错误被静默忽略；Adapter 仍允许插件自定义字段。Run JSON 的当前结构定义见 [`ragproof/schemas/run.schema.json`](ragproof/schemas/run.schema.json)，旧版 run 会在读取时兼容迁移。

完整示例：[examples/knowledgeops.yaml](examples/knowledgeops.yaml)（对接 [knowledgeops-agent](https://github.com/however-yir/knowledgeops-agent)）、[examples/mock.yaml](examples/mock.yaml)（离线演示）。

## CI Gate

在 GitHub Actions 中把 eval 变成 PR 门禁 —— prompt / 检索策略改动导致指标跌破阈值时，PR 直接红：

```yaml
- name: Regression gate
  run: |
    ragproof compare \
      --baseline runs/baseline.json \
      --current  runs/current.json \
      --threshold "recall@5=0.70" \
      --threshold "faithfulness=0.75" \
      --threshold "citation_coverage=0.80"
```

完整流水线示例：[examples/github-actions.yml](examples/github-actions.yml)。

先用 `ragproof validate -c examples/mock.yaml` 检查配置，用 `ragproof run --dry-run -c examples/mock.yaml` 检查执行计划。公开基准清单可用 `ragproof benchmark-manifest-lint examples/benchmark-manifest.json` 同时核对路径、SHA-256、数据 schema 与许可文件。

## Metrics Reference

| Metric | Type | 含义 |
|---|---|---|
| `recall@k` | deterministic | 相关文档在 top-k 检索结果中的召回比例 |
| `precision@k` | deterministic | top-k 检索结果中相关文档的占比 |
| `mrr` | deterministic | 第一个相关文档排名的倒数 |
| `hit_rate@k` | deterministic | top-k 中是否命中任一相关文档 |
| `ndcg@k` / `map@k` | deterministic | 排序质量指标 |
| `citation_coverage` | deterministic | 检索到上下文时答案是否给出引用 |
| `citation_validity` | deterministic | 引用指向真实检索结果的比例 |
| `citation_recall` | deterministic | 命中期望引用的比例 |
| `exact_match` / `lexical_token_f1` | deterministic | 参考答案精确匹配 / 明确命名的词法 token-F1；旧 `semantic_similarity` 仅保留一个发布周期 |
| `context_utilization` | deterministic | 答案词与上下文词的重合度 |
| `empty_answer_rate` / `refusal_rate` | deterministic | 空答案 / 拒答信号 |
| `faithfulness` | LLM-as-judge | 答案声明被上下文支撑的程度（幻觉检测），0–1 |
| `groundedness` / `hallucination_rate` | LLM-as-judge | 更细的支撑度 / 幻觉反向指标 |
| `context_relevance` | LLM-as-judge | 检索上下文对问题的相关性 |
| `answer_relevancy` | LLM-as-judge | 答案对问题的切题程度，0–1 |
| `avg_latency_ms` / `error_rate` | operational | 平均延迟 / 请求错误率 |
| `tokens_per_second` / `avg_first_token_latency_ms` | operational | 输出吞吐 / 首 Token 延迟 |
| `claim_support` / `citation_span_overlap` | deterministic | 声明支撑度 / 引用上下文重合度 |
| `context_redundancy` / `context_diversity` | deterministic | 检索上下文重复度 / 多样性 |
| `unanswerable_correctness` / `judge_agreement` | safety / judge | 不可回答问题处理 / 多模型一致性 |

## Sample Report

仓库内置一份用 mock adapter 跑出的**界面演示**（截图见文首）：[docs/sample-report.md](docs/sample-report.md)（HTML 版见 [docs/sample-report.html](docs/sample-report.html)）。它不代表生产质量。可复现的真实 HTTP 检索基准、语料、数据集和 baseline 见 [Benchmark 文档](docs/BENCHMARK.md)。报告也支持 CSV、JUnit XML 和 SARIF：`ragproof report runs/current.json -o report.csv`。

更多说明：[数据集规范](docs/DATASET_SCHEMA.md)、[Adapter 指南](docs/ADAPTERS.md)、[CI 教程](docs/CI_TUTORIAL.md)、[架构](docs/ARCHITECTURE.md)、[Benchmark 与适用边界](docs/BENCHMARK.md)、[PyPI Trusted Publishing](docs/TRUSTED_PUBLISHING.md)。

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check ragproof tests
mypy ragproof --ignore-missing-imports

# 创建一个新评测
ragproof init eval/ragproof.yaml
ragproof validate -c eval/ragproof.yaml
```

## Roadmap

- [x] GitHub Release：tag/版本一致性校验、发行资产与 CHANGELOG 版本说明
- [x] 唯一发行名 `ragproof-cli` 与 wheel 安装烟测
- [ ] PyPI 发布（绑定 `ragproof-cli` Trusted Publisher 后启用）
- [x] LLM judge 结果缓存、结构化原因、多模型投票
- [x] `compare` 支持相对回归阈值和 delta
- [x] LangServe / LangChain / LlamaIndex / Dify / OpenAI 兼容预设
- [x] 多 run 趋势报告、bootstrap 区间和本地回归定位
- [x] 可选 embedding-backed semantic similarity、启发式中文 tokenizer 和自定义 token 统计
- [x] 可复现的公共 HTTP 检索基准、固定 baseline 与 CI 门禁

## Why Another Eval Tool?

相比 ragas / promptfoo 等优秀工具，`ragproof` 刻意保持**小而专**：

1. **面向"已部署的 RAG API"** 而非 Python 进程内 pipeline —— 你只需要一个 HTTP 端点，不需要用特定框架重写检索逻辑；
2. **回归门禁是一等公民** —— `compare` + exit code 天生为 CI 设计；
3. **零重依赖** —— 只有 httpx / pydantic / click / jinja2 / pyyaml，安装秒级完成；
4. **local-first** —— judge 默认指向 Ollama，无 API key 也能完整体验。

## License

MIT © [however-yir](https://github.com/however-yir)
