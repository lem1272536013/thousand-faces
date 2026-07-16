# Changelog

本文件记录对用户、CLI、持久化产物、schema/preset、安全边界和迁移方式有影响的显著变化。格式参考 [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)，项目版本遵循 [Semantic Versioning 2.0.0](https://semver.org/)。

## [Unreleased]

计划发布版本：`0.1.0`。当前条目仍是候选发布内容；仓库尚无对应 Git tag 或 GitHub Release，创建发布时才补发布日期并冻结该版本内容。

### Added

- 增加离线可重复的单元、集成、跨领域、安全、质量和性能测试，以及 Windows/Linux GitHub Actions 质量门禁。
- 增加版本化 run 根格式、只读诊断、原子写入、步骤状态、缓存指纹、provenance、rights basis、保留/清理策略和结构化日志。
- 增加严格 persona/evaluation/reverse JSON Schema、证据完整性、内容重叠、提示注入隔离、跨领域 taxonomy preset 和宿主精修流程。
- 增加 `SECURITY.md`、`CONTRIBUTING.md`、版本兼容策略、文档命令校验和本发布元数据校验。

### Changed

- 将运行配置集中到类型化 Settings；`config.snapshot.json` 当前使用 `settings_schema_version=2`，配置模板、配置表和 JSON Schema 由同一元数据生成。
- 将 `creator_pipeline.py` 和 `prepare_host_refinement.py` 收敛为稳定 CLI/facade，领域实现迁入单向依赖的 owner 模块。
- 统一 provider 重试、限流、deadline、媒体边界、OSS 生命周期和失败退出码；质量失败不再误报成功。
- 通用提示词从 `references/prompts/celebrity/` 移至 `references/prompts/creator/`。

### Deprecated

- `ALI_ASR_RETRY` 仅作为 `PROVIDER_RETRY_MAX_ATTEMPTS` 未显式设置时的兼容后备；新配置应使用统一重试键。
- `scripts/research/quality_check.py` 仅保留为兼容入口，位置参数语义已收敛为当前 run 目录；新调用使用 `creator_pipeline.py quality-check`。
- `--skip-llm-research` 为兼容旧命令保留，不代表存在另一套在线研究实现。

### Removed

- 删除从未生效的 `ALI_ASR_APP_KEY`、`AUTO_RESUME`、`MAX_INPUT_TOKENS`、`MAX_OUTPUT_TOKENS` 设置；显式配置这些键会快速失败并给出替代方式。
- 删除无生产者/消费者闭环的 `style_research.json` 路径和重复研究质量算法。

### Fixed

- 修复 ASR 嵌套片段重复遍历、零时间戳丢失、多 chunk 全局时间线和合法重复话术误删问题。
- 修复并发 run 命名碰撞、部分失败误记成功、缓存按存在性误复用、空 bucket 虚高分和陈旧派生产物继续通过等问题。
- 修复视频 ID 路径安全、证据伪造、JSON Schema 未运行时验证和 readiness/passed 语义分裂。

### Security

- 增加 SSRF、DNS 重绑定、重定向、路径穿越、符号链接、无限下载、伪装媒体和压缩边界防护。
- 日志、配置快照和错误信息统一清理 secret、Authorization、签名 URL 和不可信正文；fixture 与离线测试不读取真实 `.env` 或网络。
- transcript 和外部元数据固定为不可信数据，不能覆盖宿主指令、证据归属或安全门禁。

### 迁移 / Breaking Changes

- 新 run 必须包含 `run_format=thousand-faces.creator-run`、`schema_version=1` 和必需根清单。缺少这些信息的目录固定标记为 `legacy_unverified`，只能只读诊断；当前不原地迁移，也不会补造清单，必须从原始授权来源新建 run。
- Settings schema 已升至 v2。旧 run 可继续只读诊断，但继续写入前必须使用当前配置重新创建；四个已删除设置不能从旧 `.env`、显式 mapping 或 CLI override 迁入。
- taxonomy preset 现在把名称与精确版本共同写入 run；只记录其中一个、请求未知版本或版本不匹配会在研究派生前失败，不能静默使用最新 preset。
- 旧 `references/prompts/celebrity/` 路径不再存在；自定义引用应迁移到 `references/prompts/creator/`。

### 当前版本清单

下表由 `scripts/verify_release_metadata.py` 与源码字面量逐项比对。任何 schema/preset 版本变化都必须在 `[Unreleased]` 中增加人类可读说明，并同步本表，否则 CI 失败。

<!-- release-metadata:current:start -->
| 版本源 | 当前值 | 所属产物 |
|---|---|---|
| `package_cli` | `0.1.0` | 项目与 CLI 候选发布 |
| `scripts/artifacts.py::ARTIFACT_SCHEMA_VERSION` | `1` | artifact 完成清单 |
| `scripts/content_safety.py::CONTENT_SAFETY_SCHEMA_VERSION` | `1` | 内容安全报告 |
| `scripts/creator_pipeline.py::WORKFLOW_SCHEMA_VERSION` | `1` | workflow plan/state |
| `scripts/entity_review.py::ENTITY_DECISION_SCHEMA_VERSION` | `1` | 实体决策账本 |
| `scripts/entity_review.py::ENTITY_REVIEW_SCHEMA_VERSION` | `1` | 实体复核报告 |
| `scripts/entity_review.py::PROJECT_DICTIONARY_SCHEMA_VERSION` | `1` | 项目实体词典 |
| `scripts/evidence_model.py::EVIDENCE_INTEGRITY_SCHEMA_VERSION` | `1` | 证据完整性报告 |
| `scripts/logging_utils.py::EVENT_SCHEMA_VERSION` | `1` | 结构化事件日志 |
| `scripts/oss_lifecycle.py::_MANIFEST_SCHEMA_VERSION` | `1` | OSS 生命周期清单 |
| `scripts/path_policy.py::VIDEO_ID_MAP_SCHEMA_VERSION` | `1` | 视频 ID 路径映射 |
| `scripts/pipeline_models.py::PIPELINE_RESULT_SCHEMA_VERSION` | `2` | 步骤结果模型 |
| `scripts/provenance.py::PROVENANCE_SCHEMA_VERSION` | `1` | provenance 清单 |
| `scripts/quality_engine.py::FRESHNESS_SCHEMA_VERSION` | `1` | 派生新鲜度记录 |
| `scripts/research_taxonomy.py::TAXONOMY_PRESET_VERSION` | `1.0.0` | taxonomy preset |
| `scripts/run_diagnostics.py::RUN_FORMAT_SCHEMA_VERSION` | `1` | run 根格式 |
| `scripts/run_diagnostics.py::RUN_INSPECTION_SCHEMA_VERSION` | `1` | 只读诊断响应 |
| `scripts/schema_validation.py::SCHEMA_VERSION` | `1.1.0` | persona/evaluation/reverse schema 族 |
| `scripts/settings.py::SETTINGS_SCHEMA_VERSION` | `2` | Settings 快照 |
| `scripts/stage_coverage.py::STAGE_COVERAGE_SCHEMA_VERSION` | `1` | 阶段覆盖报告 |
<!-- release-metadata:current:end -->
