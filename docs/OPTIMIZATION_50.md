# 50 项优化交付清单

这份清单把本轮升级拆成可验证的仓库能力。需要外部账号、模型或数据授权的项目，仓库提供了接口、示例和离线测试；不会把未配置的外部服务伪装成已运行。

| # | 优化项 | 交付位置 |
|---:|---|---|
| 1 | 低值更好指标的最大门禁 | `compare --max` |
| 2 | 配置驱动的 `group_by` | `RunConfig.group_by` / run JSON |
| 3 | 多 run 趋势报告 | `trend` |
| 4 | Bootstrap 置信区间 | `ragproof.trend.bootstrap_interval` |
| 5 | 阈值策略文件 | `--policy` / `examples/threshold-policy.yaml` |
| 6 | Provenance 差异说明 | `compare` provenance result |
| 7 | 最小样本数门禁 | `min_sample_count` |
| 8 | 历史阈值推荐 | `threshold-recommend` |
| 9 | 回归 bisect | `bisect` |
| 10 | 失败严重度排序 | `report._sort_by_severity` |
| 11 | 默认指标方向 | `compare.LOWER_IS_BETTER` |
| 12 | 覆盖率门禁 | `min_coverage` / `--require-field` |
| 13 | 数据集 lint | `dataset-lint` |
| 14 | 分层抽样 | `stratify_by` |
| 15 | 数据集 manifest | `dataset-manifest` |
| 16 | 近重复问题检测 | `near_duplicate_questions` |
| 17 | CSV/JSON/XLSX/Parquet 导入 | `dataset.load` |
| 18 | 数据集脱敏 | `redact_text` |
| 19 | 标准数据模板 | `examples/` 与 schema 文档 |
| 20 | 基准数据清单 | `examples/benchmark-manifest.json` |
| 21 | 可选 embedding 相似度 | `metrics.embedding` |
| 22 | 中文/多语言启发式 tokenizer | `tokenizer` 配置 |
| 23 | Claim-level 支撑度 | `claim_support` |
| 24 | Citation span overlap | `citation_span_overlap` |
| 25 | 上下文多样性/冗余 | `context_diversity` / `context_redundancy` |
| 26 | Rank sensitivity | `rank_sensitivity@k` |
| 27 | 不可回答问题正确性 | `unanswerable_correctness` |
| 28 | Judge golden 校准 | `judge-calibrate` |
| 29 | Judge 多模型一致性 | `judge_agreement` |
| 30 | Judge prompt 版本/hash | run provenance |
| 31 | Judge 失败熔断 | `JudgeConfig.max_failures` |
| 32 | Judge 可用性检查 | `judge-check` |
| 33 | Token throughput | `tokens_per_second` |
| 34 | 自定义流式 token/done 标记 | `stream_token_path` / `stream_done_markers` |
| 35 | 多问题 probe | `probe --question` 可重复 |
| 36 | Probe 置信度 | `inspect_response.confidence` |
| 37 | Probe 请求模板骨架 | `render_config` |
| 38 | 缺失环境变量提示 | `RunConfig.validation_errors` |
| 39 | 值级 secret 脱敏 | config summary / dataset redact |
| 40 | 安全错误诊断 | HTTP `_safe_error` |
| 41 | Async-compatible adapter | `HTTPAdapter.aask` |
| 42 | Preset contract tests | `tests/test_optimizations.py` |
| 43 | 框架接入示例 | `examples/*.yaml` |
| 44 | JUnit XML | `report -o report.xml` |
| 45 | SARIF | `report -o report.sarif` |
| 46 | 可复用 GitHub Action | `.github/actions/evaluate` |
| 47 | Baseline/current 样本对照 | HTML/Markdown report |
| 48 | 趋势/分组可视化数据 | trend HTML + group heatmap table |
| 49 | 覆盖率分层门槛 | `.github/workflows/ci.yml` |
| 50 | 版本/发行准备 | `0.4.0` + CHANGELOG + release workflow |

第 50 项的 GitHub Release 仍由 tag 触发；本次代码推送不会自动替用户创建外部发行或启用 PyPI Trusted Publisher。
