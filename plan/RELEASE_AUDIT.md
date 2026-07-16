# Thousand Faces 发布候选审计

> 审计日期：2026-07-16
> 审计范围：TF-001～TF-042
> 代码审计基线：`26dbbf6e6fab7db709485da1760054dc5492fa9f`
> 候选版本：`0.1.0`（仍位于 `[Unreleased]`，本次未创建 tag 或 GitHub Release）
> 结论：离线发布候选通过；真实供应商 smoke test 未获授权，明确保留为外部验证项。

## 1. 最终结论

当前代码、测试、文档、CI 和分支保护满足 `plan/PLAN.md` 第 9 节的全部离线完成定义。
本轮没有遗留 P0/P1、Critical 或 Required 级问题，也没有用 TODO 注释代替修复。

发布候选具备以下已验证能力：

- Windows 与 Linux 上使用 Python 3.11 执行同一套阻断门禁。
- 662 项测试、Ruff、Mypy、依赖健康、配置/schema drift、版本元数据、文档命令和离线 self-test 全部通过。
- 失败退出码、安全拒绝、质量 blocker、legacy run 和三类跨领域 corpus 有独立负向或端到端证据。
- `main` 已绑定两个精确的 GitHub Actions required checks，禁止 force push 和 branch deletion。
- 候选提交不包含真实凭证、签名 URL、运行目录、媒体、真实 transcript 或未授权长文本。

本结论不表示真实 TikHub、DashScope/兼容 ASR、OSS、真实账号内容质量、版权授权或商业交付已经验证。
这些项目需要用户另行提供授权、测试账号、隔离环境和可接受的调用/费用边界。

## 2. 审计范围与提交链

| 提交 | 作用 | 审计结论 |
|---|---|---|
| `61b53e076c0ec77df13ab3e64bfb7b8a3e0f49fe` | TF-001～TF-041 聚合实现、测试、CI、文档和发布治理 | 本地门禁通过；首轮托管 CI 发现两个跨环境缺陷 |
| `60d8dbed86e1608b93515f87fc3c860d255d0eb3` | 规范化 Windows 临时目录别名下的质量报告相对路径 | 补丁 1 行，新增旧实现可失败的别名路径回归测试 |
| `26dbbf6e6fab7db709485da1760054dc5492fa9f` | 跟踪被全局 `runs/` / `logs/` 规则漏掉的 4 个 synthetic legacy fixture | 新增 Git 跟踪契约；最终双平台 CI 全绿 |

首轮托管 CI 的失败没有被重跑掩盖：

1. Windows 文档离线演示暴露等价临时目录别名在 `Path.relative_to()` 前未统一解析。
2. Ubuntu 干净 checkout 暴露 `tests/fixtures/runs/legacy_v0` 被运行目录忽略规则排除。
3. 两个根因均先建立最小回归契约，再修复、提交并由全量双平台 CI 验证。

## 3. 最终验证命令与结果

除 GitHub Actions 外，所有会生成文件的本地命令均使用系统临时目录；审计结束后临时目录已清理。

| 门禁 | 命令或证据 | 结果 |
|---|---|---|
| Lint | `python -m ruff check .` | PASS |
| 类型检查 | `python -m mypy scripts` | PASS，51 个源文件 |
| 依赖健康 | `python -m pip check` | PASS，No broken requirements found |
| 配置/schema drift | `python scripts/generate_config_docs.py --check` | PASS，配置产物同步 |
| 发布元数据 | `python scripts/verify_release_metadata.py` | PASS，20 个版本源 |
| 文档契约 | `python scripts/verify_docs_commands.py` | PASS，67 条静态命令和完整离线工作流 |
| 全量测试 | `python -m pytest --cov=scripts ... -q --basetemp <系统临时目录>` | PASS，662 项，410.60 秒 |
| 覆盖率 | Coverage JSON/XML | 79.16%，49 个文件，报告成功解析 |
| 负向审计 | 退出码、CLI、stage coverage、legacy、安全、readiness、evidence、copyright 专项 | PASS，259 项，49.15 秒 |
| 离线运行 | `python scripts/self_test.py` | PASS，offline self-test passed |
| 安全示例配置 | `python scripts/config_check.py --env references/config.example.env --strict` | 预期非零；缺真实 TikHub/ASR endpoint/OSS 配置时不误报 live-ready |
| Workflow 静态检查 | 官方 `actionlint` v1.7.12 | PASS，0 error；发布资产 SHA-256 `6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9` |
| Diff 健康 | `git diff --check` | PASS，无 whitespace error；仅本机 LF/CRLF 策略提示 |

没有执行 `python scripts/config_check.py --env .env --strict`。原因是该命令会读取真实本地配置，超出本轮
“不读取、输出或提交 `.env`”的安全边界。使用安全示例配置的严格非零结果、配置模型测试和托管离线 CI
替代验证“缺少真实配置时安全失败”，但不替代真实供应商可用性验证。

## 4. GitHub Actions 与分支保护证据

最终托管运行：<https://github.com/lem1272536013/thousand-faces/actions/runs/29464470089>

| Check Run | App ID | 结果 | 测试摘要 |
|---|---:|---|---|
| `quality (ubuntu-latest, Python 3.11)` | 15368 | success | 662 passed，1 个上游弃用 warning，271.53 秒 |
| `quality (windows-latest, Python 3.11)` | 15368 | success | 662 passed，420.98 秒 |

两个完整 job 日志均执行高置信凭证模式复核，命中数为 0。Workflow 使用 `contents: read`，checkout
不持久化凭证，不引用 provider secrets 或仓库 `.env`，不执行真实供应商命令，只上传有界的 JUnit 与
Coverage 报告。

`main` 分支保护回读结果：

- `required_status_checks.strict=true`。
- required checks 精确绑定上述两个 check 名称和 GitHub Actions App ID `15368`。
- `allow_force_pushes=false`。
- `allow_deletions=false`。
- 发布本审计文件期间暂时保持 `enforce_admins=false`；最终审计提交的双平台 checks 成功后启用并再次回读。

## 5. Definition of Done 逐项证据

### 5.1 正确性

| 完成定义 | 结果 | 直接证据 |
|---|---|---|
| ASR 片段不重复遍历，合法重复话术与 0 时间戳保留 | PASS | `tests/test_asr_parsers.py`、`tests/test_transcript_merge.py`、ASR edge fixtures |
| 多 chunk transcript 具有正确全局时间线 | PASS | `tests/test_audio_chunking.py`、`tests/test_transcript_merge.py` |
| 非法参数在创建运行产物前失败 | PASS | `tests/test_cli_validation.py`、`tests/test_run_creation.py`、259 项负向套件 |
| 同一秒并发创建 run 不碰撞 | PASS | `tests/test_run_creation.py` 的并发/唯一运行 ID 契约 |
| 缓存复用由输入、配置和工具指纹证明 | PASS | `tests/test_resume_cache.py`、`tests/quality/test_freshness.py` |

### 5.2 失败语义

| 完成定义 | 结果 | 直接证据 |
|---|---|---|
| workflow、步骤结果、质量报告和退出码一致 | PASS | `tests/test_pipeline_exit_codes.py`、`tests/test_step_results.py`、`tests/test_workflow_state.py` |
| 部分失败不会记录为 succeeded | PASS | `tests/test_stage_coverage.py`、`tests/integration/test_offline_pipeline.py` |
| 基础质量失败默认返回非零 | PASS | `tests/test_pipeline_exit_codes.py`、`tests/quality/test_readiness_semantics.py` |
| 每个失败有稳定 error code 和最短修复提示 | PASS | `tests/test_structured_logging.py`、`tests/test_cli_validation.py`、`scripts/pipeline_models.py` |

### 5.3 安全与治理

| 完成定义 | 结果 | 直接证据 |
|---|---|---|
| SSRF、路径穿越、无限下载和伪装媒体被拒绝 | PASS | `tests/security/test_url_policy.py`、`test_path_containment.py`、`test_download_limits.py`、`tests/test_media_validation.py` |
| transcript 提示注入被隔离为数据 | PASS | `tests/security/test_prompt_injection_isolation.py` |
| 日志、快照和研究包不含 secret 或签名 URL | PASS | `tests/security/test_redaction.py`、`tests/test_structured_logging.py`、全仓/CI 日志敏感模式扫描 |
| OSS 与本地媒体有可审计保留/清理策略 | PASS | `tests/test_oss_lifecycle.py`、`tests/test_retention_policy.py` |
| 每个 run 记录 rights basis 和来源边界 | PASS | `tests/test_provenance.py`、`tests/test_run_creation.py` |

### 5.4 质量门禁

| 完成定义 | 结果 | 直接证据 |
|---|---|---|
| coverage 在质量检查时是最新的 | PASS | `tests/quality/test_freshness.py` |
| 空 bucket 不产生虚高分数 | PASS | `tests/quality/test_evidence_coverage.py`、`tests/quality/test_readiness_semantics.py` |
| JSON Schema 在运行时验证 | PASS | `tests/quality/test_json_schemas.py` |
| evidence ID 属于 corpus 且类型匹配 | PASS | `tests/quality/test_evidence_integrity.py` |
| `ready_for_use` 必须依赖 `passed` | PASS | `tests/quality/test_readiness_semantics.py` |
| 自填 passed、伪造 ID 或堆字数不能绕过 | PASS | readiness、evidence integrity、copyright 三组负向测试 |
| transcript dump 使用内容重叠检测 | PASS | `tests/quality/test_copyright_overlap.py`、`tests/quality/test_encoding.py` |

### 5.5 泛化

| 完成定义 | 结果 | 直接证据 |
|---|---|---|
| 科技 taxonomy 是可选 preset | PASS | `tests/research/test_taxonomy_presets.py` |
| 默认 generic 流程不包含科技假设 | PASS | taxonomy 契约与 `tests/integration/test_cross_domain_pipeline.py` |
| 至少两个非科技 corpus 端到端通过 | PASS | 美食、亲子与法律 synthetic corpus；跨领域集成测试 |
| 主题、短语和实体可追溯到视频证据 | PASS | topic discovery、Chinese signals、entity review、evidence coverage 测试 |

### 5.6 工程质量

| 完成定义 | 结果 | 直接证据 |
|---|---|---|
| pytest、ruff、mypy、pip check、self-test 全部通过 | PASS | 第 3 节最终命令记录 |
| CI 覆盖 Windows、Linux 和声明的 Python 版本 | PASS | GitHub Actions 运行 `29464470089`，两个 Python 3.11 check success |
| 两个超大核心脚本拆成可测试模块 | PASS | 架构契约测试；核心 CLI 已成为薄编排层 |
| 配置、模板和文档由单一 Settings 模型同步 | PASS | `generate_config_docs.py --check`、settings/config docs 测试 |
| 无真实凭证、未授权长文本或运行产物进入 Git | PASS | Git 跟踪审计、fixture 脱敏测试、内容安全测试和日志扫描 |

### 5.7 文档与兼容性

| 完成定义 | 结果 | 直接证据 |
|---|---|---|
| 新用户可按 README 完成离线运行 | PASS | 67 条文档静态命令和实际离线工作流 |
| 旧 run 有 legacy 诊断且不被误判 verified | PASS | `tests/integration/test_legacy_run.py`、4 个被 Git 跟踪的 synthetic legacy fixtures |
| breaking changes、schema 版本和迁移方式进入 changelog | PASS | `verify_release_metadata.py`，20 个版本源 |
| 最终发布审计保存命令和结果 | PASS | 本文件 |

## 6. P0/P1 与代码质量审查

- 提交前五轴审查覆盖正确性、安全、性能、可维护性和测试质量，未留下 Critical/Required 项。
- 托管 CI 发现的 Windows 路径别名和 Linux fixture 跟踪问题均已关闭并有回归测试。
- 生产代码中的 `TODO`、`FIXME`、`HACK`、`XXX` 命中数为 0。
- 全仓共有 167 个已跟踪文件；除既有 README 宣传图外没有超过 1 MiB 的代码、fixture 或报告文件。
- `tests/providers/test_asr_polling.py`、`tests/providers/test_retry_policy.py`、`tests/test_structured_logging.py`
  中的 3 个 key 形状命中均为显式 fake/test/synthetic 数据，受 fixture/日志脱敏测试约束，不是真实凭证。
- `creator_quality.py`、`entity_review.py`、`quality_engine.py` 等领域 owner 模块仍较大，但职责边界明确并有架构测试；
  继续拆分属于 P2 可维护性优化，不是本候选的正确性或安全 blocker。

## 7. 工作区与发布内容审计

- `.env` 被 `.gitignore` 排除，未被读取、输出或提交。
- `.venv`、pytest/Mypy/Ruff cache 和 `__pycache__` 是预期本地忽略项，不属于候选内容。
- 精确检查没有 `.env`、`.coverage`、非 fixture `runs/`、`logs/` 或 `output/` 路径被 Git 跟踪。
- `tests/fixtures/runs/legacy_v0/**` 是清单声明、synthetic-only、无凭证的测试资源，并有 Git 跟踪契约。
- 本次最终待提交改动只应包含 `plan/PLAN.md`、`plan/TODO.md` 和本审计文件；提交前再次执行范围核对。

## 8. 未验证与需外部授权项目

| 项目 | 状态 | 原因与后续条件 |
|---|---|---|
| 真实 TikHub API smoke | 未执行 | 需要用户授权、测试账号、调用次数/费用边界和脱敏日志策略 |
| 真实 DashScope/兼容 ASR smoke | 未执行 | 需要用户授权、音频权利确认、调用预算和输出留存边界 |
| 真实 OSS 上传、签名 URL 与清理 | 未执行 | 需要隔离 bucket、最小权限凭证、TTL 和删除范围确认 |
| 真实 `.env` 严格配置检查 | 未执行 | 本轮明确不读取真实本地凭证；由部署操作者在受控环境执行 |
| 真实账号内容质量、事实准确性和商业可交付性 | 未验证 | synthetic corpus 只能证明确定性链路，仍需人工领域与权利审查 |
| Git tag / GitHub Release | 未创建 | 用户只授权提交、推送、CI 和 required checks，未授权正式发布 |
| GitHub Private Vulnerability Reporting | 未启用 | 当前仓库设置关闭；已有 SECURITY 中的无细节公开转私密 advisory 流程 |

这些未验证项不影响 TF-042 的离线完成判定，因为计划明确允许在未获授权时记录而不执行真实 API smoke。

## 9. 剩余风险

- 供应商响应、限流和 SDK 行为可能随时间变化；正式部署前应在隔离环境做受控 smoke。
- Windows 原子替换曾在本地杀毒/文件占用条件下出现瞬时 `WinError 5`；本轮本地与托管 Windows 全量均通过，
  但高并发生产使用仍应监控该错误码。
- `jieba`、`crcmod` 和部分阿里云依赖存在上游弃用/构建提示；当前安装与运行成功，不是功能 blocker。
- 中文主题、实体和内容重叠仍包含启发式判断；高风险商业使用必须保留人工审核。
- 最终审计提交本身还需再次通过两个 required checks；通过后启用管理员强制执行并回读，作为交付收尾条件。

## 10. 发布判定

离线发布候选：**通过**。

允许的下一步是提交本审计与计划状态、等待最终 Windows/Linux required checks 成功、启用
`enforce_admins` 并核对远端 SHA。未经另行授权，不创建 tag/Release，不读取真实 `.env`，不调用真实供应商。
