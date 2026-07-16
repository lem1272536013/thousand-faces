# 千人千面项目系统优化开发计划

> 文档版本：1.0
> 编制日期：2026-07-15
> 适用仓库：`qianrenqianmian` / Thousand Faces
> 计划状态：已完成（离线发布候选验证通过；真实供应商 smoke 需另行授权）
> 配套清单：`plan/TODO.md`

## 1. 计划目的

本计划把当前仓库审计中发现的正确性、安全性、质量门禁、领域泛化、可靠性、性能、工程化和文档问题，拆解为可由 AI 在多个独立会话中逐项完成的开发任务。

计划的最终目标不是简单让现有离线自测继续通过，而是让项目达到以下状态：

1. 语料不会因为解析、去重、分片或缓存错误而被静默污染。
2. 流水线失败时，CLI、工作流状态、日志和退出码表达一致。
3. 外部 URL、供应商响应、标题和转写稿全部按不可信输入处理。
4. `passed` 和 `ready_for_use` 由可重新计算的事实决定，而不是由文件存在、字数或自填布尔值决定。
5. 研究层不再默认等同于 AI/科技账号，可以处理不同垂直领域的创作者。
6. 高成本步骤可以安全恢复，但不会错误复用已经过期或不完整的产物。
7. 核心模块有稳定接口、自动化测试、持续集成和清晰的运维证据。

## 2. 当前基线与已确认问题

### 2.1 当前可用能力

- 已具备端到端确定性流水线和离线自测。
- 已具备 TikHub、Qwen-ASR 兼容接口、DashScope 录音文件识别和 OSS 桥接。
- 已具备运行目录、中间产物、工作流状态和基础质量报告。
- 已区分 `passed` 与 `ready_for_use`。
- 已有免责声明、安全边界、证据索引和宿主 Agent 精修流程。
- `.env` 已被 Git 忽略，当前工作区没有已跟踪密钥。

### 2.2 必须解决的已确认问题

| 编号 | 问题 | 当前证据 | 目标任务 |
|---|---|---|---|
| B-01 | ASR 片段递归重复收集、合法重复话术被误删、`start=0` 丢失 | 3 个输入片段被收集为 6 个，最终只保留 2 句 | TF-006、TF-007 |
| B-02 | 质量失败时进程退出码仍为 0 | `quality_passed=false`、workflow failed，但 return code 为 0 | TF-009、TF-010 |
| B-03 | 同一秒创建的两次运行目录碰撞 | 两次 `create_run()` 返回相同路径 | TF-004 |
| B-04 | 非法 `sample_count` 没有被拒绝 | `sample_count=-1` 实际选择了 N-1 条数据 | TF-004 |
| B-05 | Evidence coverage 是过期派生产物 | 修改 evidence index 后存储覆盖数仍为 0，重算为 1 | TF-018 |
| B-06 | 空覆盖 bucket 被算作满分 | 零证据样本得到 `overall_score=0.6` | TF-019 |
| B-07 | 转写稿直接进入 Agent brief，缺少提示注入隔离 | transcript excerpt 以普通 Markdown 正文写入 | TF-014 |
| B-08 | URL 与下载边界缺少 SSRF、私网、大小、MIME 限制 | 任意 HTTP(S) URL 可被跟随和下载 | TF-011、TF-012 |
| B-09 | 研究词典硬编码为 AI/科技账号 | 主题、Hook、实体和贡献类型均偏科技领域 | TF-024 至 TF-028 |
| B-10 | JSON Schema 只生成不验证 | 质量检查只看 schema 文件存在和手写字段 | TF-020 至 TF-022 |
| B-11 | 缓存只按文件存在复用 | 音频分片、ASR JSON、transcript 无输入指纹 | TF-008 |
| B-12 | 配置存在多源漂移和死配置 | 根模板与参考模板参数不同，部分运行参数未纳入快照 | TF-033、TF-034、TF-037 |
| B-13 | 自动化测试只有单条 happy path | 无 pytest、CI、错误路径、恶意输入和跨平台测试 | TF-001 至 TF-003 |
| B-14 | 核心文件过大且职责混合 | 两个核心脚本均超过 1400 行 | TF-035、TF-036 |

## 3. 目标架构原则

### 3.1 数据边界

- TikHub 响应、ASR 响应、视频标题、转写稿、URL、已有运行产物均视为不可信输入。
- 外部输入先进入解析和验证层，转换为内部规范模型后，业务代码不得继续递归猜测任意 JSON。
- 文件路径必须由规范 ID 派生，并在读写前验证解析后的绝对路径仍位于预期目录内。

### 3.2 流水线状态

- 每个步骤返回结构化 `StepResult`，至少包含状态、输入数量、成功数量、失败数量、跳过数量、耗时和问题摘要。
- 步骤状态使用 `pending/running/succeeded/partial/failed/skipped`，不再把部分失败记为 completed。
- CLI 退出码与最终状态一致；失败和不满足质量门槛不得返回 0。
- 所有关键 JSON 使用原子写入，运行目录必须唯一。

### 3.3 产物恢复

- 高成本产物必须有 manifest，记录源文件哈希、相关配置哈希、工具/模型版本和产物哈希。
- 只有指纹完全匹配且产物校验通过时才允许复用。
- 老运行目录可以只读兼容；缺少 manifest 时默认判定为 legacy，并要求显式选择是否信任。

### 3.4 质量门禁

- 派生指标在质量检查时重新计算，或通过输入指纹证明未过期。
- JSON Schema 必须在运行时验证。
- 所有 evidence ID 必须属于本次 corpus，并能追溯到至少一个真实 transcript 或明确的缺失说明。
- `ready_for_use = passed AND content_readiness`。
- 自动门禁不得只依赖 Agent 自己填写的 `passed=true`。

### 3.5 领域泛化

- 当前科技词典保留为可选 preset，不再作为全局默认人格模型。
- 通用流程先做无领域假设的语料统计和候选主题发现，再应用领域 preset 或宿主 Agent 归纳。
- 无法分类时保留 `unclassified` 和置信度，不强行贴科技标签。

## 4. 非目标与兼容约束

本轮优化不包括：

- 不建设 Web 平台、数据库、用户系统或 SaaS 后台。
- 不新增与问题无关的供应商。
- 不改变“公开或授权材料、不得冒充本人”的产品定位。
- 不在单元测试或 CI 中调用真实 TikHub、ASR、OSS 服务。
- 不把完整转写稿写入最终 Creator Skill。

必须保留：

- 现有主要 CLI 命令和运行目录顶层结构。
- `scripts/self_test.py` 作为用户可直接运行的离线冒烟入口。
- 已有 `.env` 变量在迁移期内继续兼容；废弃项需要警告和迁移说明。
- 旧运行目录至少支持质量诊断和明确的 legacy 状态，不得静默误判为新格式。

## 5. 依赖关系与关键路径

```text
TF-001 测试基础
  ├─ TF-002 回归 fixtures
  │    ├─ TF-004 输入与 Run ID
  │    ├─ TF-006 ASR 解析
  │    │    └─ TF-007 分片时间线
  │    ├─ TF-011 网络边界
  │    └─ TF-019 覆盖率语义
  └─ TF-003 离线集成测试

TF-004 ─┬─ TF-005 原子状态
TF-006 ─┤
TF-007 ─┴─ TF-008 指纹恢复 ── TF-009 失败语义 ── TF-010 覆盖阈值

TF-011 ─ TF-012 ─ TF-013 ─ TF-014 ─ TF-015 ─ TF-016 ─ TF-017

TF-018 ─ TF-019 ─ TF-020 ─ TF-021 ─ TF-022 ─ TF-023

TF-006 + TF-019 ─ TF-024 ─ TF-025 ─ TF-026 ─ TF-027 ─ TF-028

行为稳定后：
TF-033 ─ TF-034 ─ TF-035 ─ TF-036 ─ TF-037 ─ TF-038

最终：
TF-039 ─ TF-040 ─ TF-041 ─ TF-042
```

关键路径是：测试基线 → ASR 正确性 → 状态与恢复 → 安全边界 → 质量门禁 → 领域泛化 → 架构拆分 → 发布验收。

## 6. AI 执行协议

后续 AI 每次执行任务时必须遵守：

1. 先读取本文件和 `plan/TODO.md`，确认任务依赖均已完成。
2. 执行前运行 `git status --short --branch`，区分已有改动和本任务改动。
3. 行为修改优先补失败测试，再实施最小修复。
4. 每次只完成一个任务编号；任务过大时先在 PLAN 中拆分，不得一次横跨多个阶段。
5. 不使用真实凭证构造测试，不把 `.env` 内容写入日志、fixture 或测试快照。
6. 外部服务测试使用脱敏录制 fixture 或本地 mock server。
7. 验收命令必须实际运行；不能只根据代码阅读勾选完成。
8. 完成后在 `plan/TODO.md` 勾选任务，并记录验证命令和结果摘要。
9. 若修改公共产物格式，必须增加 `schema_version`、迁移说明和旧格式测试。
10. 若发现当前任务必须扩大范围，先更新 PLAN 的依赖和验收标准，再继续编码。

## 7. 分阶段任务清单

## Phase 0：建立可重复验证基线

### TF-001：建立隔离的测试与开发工具基线

**目标：** 为所有后续行为修改提供统一的 pytest、静态检查和隔离依赖入口。

**实施内容：**

- 新增 `pyproject.toml`，声明支持的 Python 版本、pytest 配置、ruff 规则和项目元数据。
- 新增开发依赖文件或锁定方案，至少包含 pytest、pytest-cov、ruff、mypy 和 JSON Schema validator。
- 保留 `requirements.txt` 作为运行依赖入口，但明确运行依赖和开发依赖的边界。
- 新增 `tests/conftest.py`，提供临时运行目录、脱敏配置和 fixture 根目录。
- 文档中要求在独立 `.venv` 内运行 `pip check`，不得用全局环境结果判断项目依赖健康。

**验收标准：**

- [x] 新建虚拟环境后可以一次安装运行依赖和开发依赖。
- [x] `python -m pytest --collect-only` 成功。
- [x] `python -m ruff check .` 能运行且没有未解释错误。
- [x] `python -m pip check` 在项目虚拟环境内通过。

**验证命令：**

```powershell
python -m pytest --collect-only
python -m ruff check .
python -m pip check
```

**依赖：** 无。
**可能涉及文件：** `pyproject.toml`、`requirements.txt`、`requirements-dev.txt`、`tests/conftest.py`。
**规模：** M。

### TF-002：建立脱敏回归 fixture 矩阵

**目标：** 用固定输入覆盖当前已确认 bug 和供应商响应差异。

**实施内容：**

- 增加 TikHub 单页、多页、重复视频、字段变体、空列表、异常统计值 fixture。
- 增加 compatible chat completions、audio transcriptions、DashScope segments、嵌套重复节点 fixture。
- 增加合法重复话术、`start=0`、乱序时间戳、无时间戳、空文本和超长文本 fixture。
- 增加非科技领域标题与转写 fixture，例如美食、法律或母婴账号。
- 增加恶意 URL、路径穿越 ID、Markdown 指令注入和伪造 evidence ID fixture。
- 所有 fixture 必须确认不含真实用户数据、真实 token、签名 URL 或未授权长文本。

**验收标准：**

- [x] 每类 fixture 有清晰 README 或命名说明。
- [x] fixture 内容均为人工构造或已脱敏短样本。
- [x] 测试可在无网络、无 `.env` 的环境运行。

**验证命令：**

```powershell
python -m pytest tests/test_fixtures.py -q
git grep -n -E "(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)" -- tests
```

**依赖：** TF-001。
**可能涉及文件：** `tests/fixtures/**`、`tests/test_fixtures.py`、`tests/fixtures/README.md`。
**规模：** M。

### TF-003：把离线自测提升为可断言的集成测试

**目标：** 保留用户入口，同时让 CI 能检查每个关键产物和退出语义。

**实施内容：**

- 将 `self_test.py` 中的场景抽取为 pytest 集成测试可复用函数。
- `scripts/self_test.py` 继续作为薄 CLI，内部调用同一测试场景或等价公共 helper。
- 增加无 transcript、部分 transcript、空 metadata、准备 host refinement 后仍非 ready 的场景。
- 断言退出码、workflow 最终状态、质量报告、产物数量和关键 schema 版本。

**验收标准：**

- [x] 原 `python scripts/self_test.py` 继续通过。
- [x] pytest 能独立执行同一离线端到端路径。
- [x] 失败场景可以证明当前 runner 不会把失败报告为成功。

**验证命令：**

```powershell
python scripts/self_test.py
python -m pytest tests/integration/test_offline_pipeline.py -q
```

**依赖：** TF-001、TF-002。
**可能涉及文件：** `scripts/self_test.py`、`tests/integration/test_offline_pipeline.py`、`tests/helpers.py`。
**规模：** M。

### Checkpoint 0：测试基线

- [x] 测试无需外部网络和真实凭证。
- [x] 当前行为 bug 均有失败测试或明确的 xfail 说明。
- [x] `self_test.py` 与 pytest 不维护两套相互漂移的 fixture。

## Phase 1：修复核心正确性、状态和恢复机制

### TF-004：校验 CLI 输入并生成不可碰撞的 Run ID

**目标：** 阻止非法参数和运行目录复用污染。

**实施内容：**

- `sample_count`、fetch limit、并发、重试、timeout、segment seconds 必须有明确范围。
- 对 `sample_count <= 0`、超出合理上限或非法整数直接报错。
- Run ID 改为 UTC 毫秒时间戳加随机后缀或 UUID。
- 创建目录使用不可覆盖语义；路径已存在时重试生成或失败，不使用 `exist_ok=True` 静默复用。
- 对 project slug 长度和空值做验证。

**验收标准：**

- [x] 同一进程连续创建 1000 个 run 不重复。
- [x] `sample_count=-1/0` 返回非零退出码且不创建半成品 run。
- [x] 正常 project name 和中文名称仍可创建目录。

**验证命令：**

```powershell
python -m pytest tests/test_run_creation.py tests/test_cli_validation.py -q
```

**依赖：** TF-001、TF-002。
**可能涉及文件：** `scripts/build_creator_skill.py`、`scripts/run_creator_skill_build.py`、`tests/test_run_creation.py`、`tests/test_cli_validation.py`。
**规模：** M。

### TF-005：实现原子 JSON 写入和可恢复 workflow 状态

**目标：** 防止进程中断产生半截 JSON 或丢失工作流状态。

**实施内容：**

- 提供单一 `atomic_write_json()` 和 `atomic_write_text()`。
- 先写同目录临时文件，flush/fsync 后使用原子 replace。
- workflow 更新失败不能被无声吞掉；至少写入 stderr 并保留恢复错误。
- workflow 顶层增加 `schema_version`、`created_at`、`updated_at`、`final_status`。
- 为中断写入、损坏旧 JSON 和恢复更新增加测试。

**验收标准：**

- [x] 模拟写入中断后原文件仍可解析。
- [x] workflow JSON 损坏时返回明确诊断，不继续假装更新成功。
- [x] 所有关键 JSON 写入迁移到公共原子写入函数。

**验证命令：**

```powershell
python -m pytest tests/test_atomic_io.py tests/test_workflow_state.py -q
```

**依赖：** TF-004。
**可能涉及文件：** `scripts/io_utils.py`、`scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`tests/test_atomic_io.py`。
**规模：** M。

### TF-006：重写 ASR 响应解析，保留真实语料语义

**目标：** 消除递归重复、错误去重、时间零值丢失和响应结构误判。

**实施内容：**

- 建立规范 `TranscriptSegment` 模型，包含 text、start_ms、end_ms、source_index 和 provider。
- 为 compatible chat、audio transcriptions、DashScope 分别实现显式 adapter。
- 不再对任意 JSON 进行无边界递归并同时遍历已处理节点。
- 使用 `is not None` 判断时间值，保留 `0`。
- 仅去除同一 provider 节点被重复映射产生的完全相同片段，不删除不同时间出现的相同话术。
- 片段按有效时间和原始顺序稳定排序。
- 无法识别响应结构时返回明确错误，保留原始 JSON 供诊断。

**验收标准：**

- [x] 3 个输入片段输出 3 个片段，不再变成 6 个。
- [x] 两个不同时间的相同文本都被保留。
- [x] `start=0` 输出 `[00:00:00]`。
- [x] 乱序输入按时间稳定排序。
- [x] 未识别格式导致步骤失败，而不是生成空 transcript。

**验证命令：**

```powershell
python -m pytest tests/test_asr_parsers.py -q
```

**依赖：** TF-001、TF-002。
**可能涉及文件：** `scripts/asr_parsers.py`、`scripts/creator_pipeline.py`、`tests/test_asr_parsers.py`。
**规模：** M。

### TF-007：修复音频分片合并与全局时间线

**目标：** 分片 ASR 合并后仍保持单调、可追溯的全局时间戳。

**实施内容：**

- 切片 manifest 记录每片实际开始时间、结束时间、时长和源音频哈希。
- 合并片段时将局部时间戳加上 chunk offset。
- 处理边界重叠：仅在相邻 chunk 的时间窗和文本相似度同时满足条件时去除重复。
- 合并后验证时间戳单调、片段数量和非空文本比例。
- transcript 中保留 chunk 来源映射到单独 JSON，不把调试元数据写进正文。

**验收标准：**

- [x] 第二片 5 秒处在 120 秒分片后显示为 125 秒。
- [x] 分片边界合法重复不会被误删。
- [x] 合并结果时间戳单调递增。
- [x] 分片失败不会退化成错误的完整文件缓存。

**验证命令：**

```powershell
python -m pytest tests/test_audio_chunking.py tests/test_transcript_merge.py -q
```

**依赖：** TF-006。
**可能涉及文件：** `scripts/run_creator_skill_build.py`、`scripts/asr_parsers.py`、`tests/test_audio_chunking.py`、`tests/test_transcript_merge.py`。
**规模：** M。

### TF-008：为下载、音频、ASR 和摘要增加产物指纹

**目标：** 只复用与当前输入和配置严格一致的高成本产物。

**实施内容：**

- 定义统一 artifact manifest schema。
- 下载记录 URL 的安全指纹、响应元数据和文件 SHA-256，不保存敏感查询明文。
- 音频记录源视频哈希、ffmpeg 版本和音频参数。
- ASR 记录音频哈希、provider、endpoint 标识、model、语言、分片配置和 parser version。
- 摘要、signal、coverage 记录上游文件哈希。
- 旧产物没有 manifest 时标记 `legacy_unverified`，默认不自动用于成品质量门禁。

**验收标准：**

- [x] 修改 ASR 模型、分片时长或源音频后缓存失效。
- [x] 配置未变化时重复运行可以复用已验证产物。
- [x] 截断、空文件或哈希不一致的产物不会被复用。
- [x] manifest 不包含 API key、签名 URL或完整 Authorization。

**验证命令：**

```powershell
python -m pytest tests/test_artifact_manifest.py tests/test_resume_cache.py -q
```

**依赖：** TF-005、TF-006、TF-007。
**可能涉及文件：** `scripts/artifacts.py`、`scripts/run_creator_skill_build.py`、`scripts/creator_pipeline.py`、`tests/test_resume_cache.py`。
**规模：** M。

### TF-009：统一步骤结果、最终状态和退出码

**目标：** 让 shell、CI、Agent、workflow 和质量报告对成功失败给出相同结论。

**实施内容：**

- 定义 `StepResult` 和 `PipelineResult`。
- 下载、音频、ASR、研究、构建和质量步骤返回结构化结果，不只返回日志路径。
- 对关键步骤区分 succeeded、partial、failed、skipped。
- runner 最终失败或基础质量未通过时返回非零退出码。
- `quality-check` 增加默认严格退出语义；如需只打印报告，提供显式 `--report-only`。
- 异常路径先写最终 workflow 状态，再抛出可诊断错误。

**验收标准：**

- [x] 空 metadata/无 transcript 的 runner 返回非零。
- [x] workflow `final_status` 与退出码一致。
- [x] `quality-check` 失败默认非零。
- [x] report-only 模式可返回 0，但输出中明确 `passed=false`。

**验证命令：**

```powershell
python -m pytest tests/test_pipeline_exit_codes.py tests/test_step_results.py -q
```

**依赖：** TF-005、TF-008。
**可能涉及文件：** `scripts/pipeline_models.py`、`scripts/run_creator_skill_build.py`、`scripts/creator_pipeline.py`、`tests/test_pipeline_exit_codes.py`。
**规模：** M。

### TF-010：建立阶段覆盖率和部分失败门槛

**目标：** 防止 50 条样本只成功 1 条仍被基础流水线视为完整。

**实施内容：**

- 质量报告记录 selected/downloaded/audio/transcribed 各阶段数量和比率。
- 定义 draft 与 ready 两套最低阈值，并允许通过配置在合理范围内调整。
- 缺下载 URL、下载失败、音频失败、ASR 跳过必须进入问题清单。
- 样本量很小时使用绝对数量规则，样本量较大时同时使用比例规则。
- `passed` 至少要求所有必需阶段达到 draft 门槛。

**验收标准：**

- [x] selected=50、transcribed=1 时 `passed=false`。
- [x] 使用 `--transcripts-dir` 的合法离线路径不会被下载覆盖率误伤。
- [x] 每个未覆盖视频有可追踪状态和原因。

**验证命令：**

```powershell
python -m pytest tests/test_stage_coverage.py -q
```

**依赖：** TF-009。
**可能涉及文件：** `scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`tests/test_stage_coverage.py`。
**规模：** M。

### Checkpoint 1：可信流水线基础

- [x] 已确认的 ASR 重复、时间戳、退出码、Run ID 和非法参数 bug 全部有回归测试。
- [x] 任意关键步骤失败不会返回成功退出码。
- [x] 缓存复用有指纹证据。
- [x] 原离线自测继续通过。

## Phase 2：安全与数据治理

### TF-011：实现统一网络访问策略并阻断 SSRF

**目标：** 所有外部请求在发出前和重定向后都经过一致的 URL 安全策略。

**实施内容：**

- 仅允许 HTTP/HTTPS。
- 抖音来源链接使用明确域名 allowlist。
- 解析 DNS 后拒绝 loopback、link-local、私网、保留地址和本机地址。
- 每次重定向重新验证目标。
- provider endpoint 作为受信配置与用户输入 URL 分开处理，但仍拒绝 URL 中嵌入凭证。
- 单元测试使用本地假解析器或 mock，不实际访问内网。

**验收标准：**

- [x] `localhost`、`127.0.0.1`、`169.254.169.254`、RFC1918 和 IPv6 loopback 被拒绝。
- [x] 公网抖音短链允许解析。
- [x] 公网 URL 重定向到私网时被拒绝。
- [x] 错误信息不回显敏感查询字符串。

**验证命令：**

```powershell
python -m pytest tests/security/test_url_policy.py -q
```

**依赖：** TF-001、TF-002。
**可能涉及文件：** `scripts/network_policy.py`、`scripts/provider_adapters.py`、`tests/security/test_url_policy.py`。
**规模：** M。

### TF-012：限制下载资源并验证媒体文件

**目标：** 防止无限下载、磁盘耗尽、伪装内容和错误缓存。

**实施内容：**

- 配置最大视频字节数、最大响应头等待时间和总下载 deadline。
- 流式下载时累计字节，超限立即中止并删除 `.part`。
- 检查 HTTP 状态、Content-Length、Content-Type，并用 ffprobe 验证实际媒体。
- 下载重试前清理或安全处理旧 `.part`，不得与重复 video ID 并发写同一文件。
- 记录内容哈希和媒体基本信息。

**验收标准：**

- [x] 超过大小限制的响应被中止且不留下可复用文件。
- [x] HTML/JSON 伪装成 mp4 时被拒绝。
- [x] 有效媒体通过验证。
- [x] 重复 video ID 不发生并发覆盖。

**验证命令：**

```powershell
python -m pytest tests/security/test_download_limits.py tests/test_media_validation.py -q
```

**依赖：** TF-011。
**可能涉及文件：** `scripts/network_policy.py`、`scripts/creator_pipeline.py`、`tests/security/test_download_limits.py`、`tests/test_media_validation.py`。
**规模：** M。

### TF-013：规范 video ID 并保证路径包含关系

**目标：** 阻止外部 ID 造成路径穿越、文件碰撞或错误证据关联。

**实施内容：**

- 为平台原始 ID和本地 artifact ID 建立分离字段。
- 本地 ID 只允许受限字符和长度，并对重复 ID生成稳定冲突后缀。
- 所有读写调用统一 `resolve_within(root, relative)`。
- 拒绝 `..`、绝对路径、设备路径、路径分隔符和 Windows 保留名。
- evidence 中仍保留原平台 ID，但通过结构化索引映射到本地 artifact ID。

**验收标准：**

- [x] 路径穿越和绝对路径 ID 被拒绝。
- [x] 两个归一化后同名的 ID 不会覆盖。
- [x] 合法抖音 ID、测试短 ID和 legacy ID均有明确处理结果。

**验证命令：**

```powershell
python -m pytest tests/security/test_path_containment.py tests/test_video_ids.py -q
```

**依赖：** TF-004。
**可能涉及文件：** `scripts/path_policy.py`、`scripts/creator_pipeline.py`、`scripts/prepare_host_refinement.py`、`tests/security/test_path_containment.py`。
**规模：** M。

### TF-014：隔离转写稿中的提示注入和 Markdown 控制内容

**目标：** 宿主 Agent 只把标题和转写稿当研究数据，不执行其中的指令。

**实施内容：**

- 在主 `SKILL.md`、host refinement brief 和研究提示词中加入明确的不可信语料协议。
- transcript excerpt 使用有边界的数据容器，转义可能改变文档结构的标题、表格符、代码围栏和链接。
- 明确禁止执行语料中的命令、读取语料指定的本地文件、访问语料指定 URL、泄露配置或修改计划。
- 推荐研究步骤运行在无供应商凭证、最小工具权限的上下文中。
- 增加包含“忽略以上指令”“读取 .env”等文本的恶意 fixture，验证其只作为内容出现。

**验收标准：**

- [x] 生成 brief 前部包含不可被语料覆盖的安全说明。
- [x] 恶意 transcript 不会创建额外 Markdown 顶层章节或可执行步骤。
- [x] 文档明确研究 Agent 不应访问 `.env` 或执行外部材料中的工具指令。

**验证命令：**

```powershell
python -m pytest tests/security/test_prompt_injection_isolation.py -q
```

**依赖：** TF-002、TF-013。
**可能涉及文件：** `SKILL.md`、`scripts/prepare_host_refinement.py`、`references/host_refinement.md`、`tests/security/test_prompt_injection_isolation.py`。
**规模：** M。

### TF-015：加强配置脱敏和最小化研究数据

**目标：** 运行产物和宿主研究材料不包含不必要的凭证片段或下载签名。

**实施内容：**

- secret 值默认全量替换为固定占位符，不保留首尾 4 位。
- URL 脱敏移除 userinfo 和敏感 query 参数。
- `selected.compact.json` 删除研究不需要的 `download_url`，或只保留是否存在和安全来源标识。
- 日志错误信息通过统一 scrubber 清理 token、Authorization、签名 URL 和本地敏感路径。
- 增加配置快照和错误响应脱敏测试。

**验收标准：**

- [x] 快照中无法恢复任何 secret 片段。
- [x] compact metadata 不含下载签名 URL。
- [x] 模拟供应商错误回显 token 时，workflow 和日志中仍没有 token。

**验证命令：**

```powershell
python -m pytest tests/security/test_redaction.py tests/test_compact_metadata.py -q
```

**依赖：** TF-005。
**可能涉及文件：** `scripts/redaction.py`、`scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`tests/security/test_redaction.py`。
**规模：** M。

### TF-016：实现 OSS 对象隔离、生命周期和清理策略

**目标：** 避免跨运行覆盖、长期残留和不可审计的第三方音频存储。

**实施内容：**

- OSS object key 包含 project/run/video/chunk 和源文件哈希，不再只使用文件名。
- 在 manifest 中记录上传对象和清理状态，但不记录签名 URL 明文。
- 提供成功后删除、失败保留一定时间、显式保留三种策略。
- 清理失败进入 workflow 问题清单，但不泄露凭证。
- 文档说明 OSS 生命周期规则和成本/隐私影响。

**验收标准：**

- [x] 两个 run 的同名音频不会覆盖同一对象。
- [x] 默认策略下 ASR 完成后执行清理或写入明确待清理状态。
- [x] mock OSS 测试覆盖上传、签名、删除和删除失败。

**验证命令：**

```powershell
python -m pytest tests/test_oss_lifecycle.py -q
```

**依赖：** TF-008、TF-015。
**可能涉及文件：** `scripts/provider_adapters.py`、`scripts/artifacts.py`、`tests/test_oss_lifecycle.py`、`references/configuration.md`。
**规模：** M。

### TF-017：增加来源权利依据、溯源和数据保留清单

**目标：** 把“公开或授权材料”从文案声明变成运行级可审计数据。

**实施内容：**

- 输入增加 `rights_basis`，例如 `public_research`、`creator_authorized`、`team_owned`。
- 授权场景可记录授权引用 ID或本地说明路径，但不得把合同/身份证明复制进 run。
- `input.json` 和 `meta.json` 记录来源平台、采集时间、rights basis、retention policy 和 opt-out/takedown 联系说明。
- 提供保留媒体、仅保留 transcript、仅保留最终 skill 等策略。
- 未声明 rights basis 时允许 draft 研究与否应形成明确产品决策；默认不得进入商业交付 ready 状态。

**验收标准：**

- [x] 每个新 run 都有可枚举的 rights basis。
- [x] ready 成品包含来源和使用边界，但不包含私密授权材料。
- [x] 数据清理策略可 dry-run 并列出将删除的产物。

**验证命令：**

```powershell
python -m pytest tests/test_provenance.py tests/test_retention_policy.py -q
```

**依赖：** TF-004、TF-015、TF-016。
**可能涉及文件：** `scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`scripts/retention.py`、`tests/test_provenance.py`。
**规模：** M。

### Checkpoint 2：安全与治理

- [x] 外部 URL、路径、文本和响应均经过边界验证。
- [x] 恶意 transcript 无法改变 Agent 工作指令。
- [x] 研究材料和日志不含 secret、签名 URL或不必要下载地址。
- [x] OSS 和本地产物都有保留/清理策略。

## Phase 3：重建可信质量门禁

### TF-018：质量检查时重算或验证派生产物新鲜度

**目标：** 修改 evidence、persona 或 transcript 后，质量检查不再读取过期报告。

**实施内容：**

- 提取纯函数形式的 corpus、signals、coverage 和 diagnostics 计算入口。
- `quality-check` 对关键派生产物实时重算，或验证 manifest 输入哈希匹配。
- 报告增加 `computed_from` 和 `freshness` 字段。
- 过期报告不得参与 `ready_for_use` 判定。
- 文档无需再要求用户记住额外重跑 prepare 命令。

**验收标准：**

- [x] 修改 evidence index 后再次 quality-check 能立即看到新覆盖数。
- [x] 修改 transcript 后旧 signal/coverage 被判定 stale。
- [x] stale 产物使 ready=false，并给出最短修复命令。

**验证命令：**

```powershell
python -m pytest tests/quality/test_freshness.py -q
```

**依赖：** TF-008。
**可能涉及文件：** `scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`scripts/prepare_host_refinement.py`、`tests/quality/test_freshness.py`。
**规模：** M。

### TF-019：修正覆盖率 denominator、N/A 和证据解析

**目标：** 空类别不再凭空加分，视频 ID 只按结构化证据条目计算。

**实施内容：**

- coverage bucket 在 total=0 时返回 `status=not_applicable`，不返回 ratio=1。
- overall score 只平均 applicable bucket，并同时报告覆盖视频绝对数量。
- 解析 evidence index 的明确表格/结构字段，不使用简单 substring。
- coverage report 区分 missing、rejected_with_reason、not_applicable。
- 每类阈值必须有命名配置和解释。

**验收标准：**

- [x] 零证据时 overall score 为 0 或 unavailable，不再为 0.6。
- [x] ID `123` 不会因为 evidence 中出现 `1234` 被算作覆盖。
- [x] 不存在短视频/边界样本时对应 bucket 为 N/A。
- [x] 被明确拒绝的噪声样本不算 evidence，但可关闭 gap。

**验证命令：**

```powershell
python -m pytest tests/quality/test_evidence_coverage.py -q
```

**依赖：** TF-002、TF-018。
**可能涉及文件：** `scripts/quality_engine.py`、`scripts/prepare_host_refinement.py`、`tests/quality/test_evidence_coverage.py`。
**规模：** M。

### TF-020：执行 JSON Schema 运行时验证

**目标：** persona、evaluation 和 reverse identification 必须真正符合 schema。

**实施内容：**

- 选择 Draft 2020-12 validator，并固定依赖版本范围。
- schema 默认设置 `additionalProperties: false`；确需扩展处显式声明。
- quality report 输出带 JSON Pointer 的错误位置和简短信息。
- schema 文件增加独立版本，禁止只按文件大小判断。
- 模板和最终产物分别使用 template status 与 completed status 约束。

**验收标准：**

- [x] 字段类型错误、缺字段、多余字段和非法状态均导致验证失败。
- [x] 合法模板可生成，但不能进入 ready。
- [x] 合法完成产物通过 schema 验证。

**验证命令：**

```powershell
python -m pytest tests/quality/test_json_schemas.py -q
```

**依赖：** TF-001、TF-018。
**可能涉及文件：** `scripts/schema_validation.py`、`scripts/prepare_host_refinement.py`、`scripts/creator_pipeline.py`、`tests/quality/test_json_schemas.py`。
**规模：** M。

### TF-021：验证证据 ID、persona model 和 corpus 的引用完整性

**目标：** 阻止伪造或不属于本次语料的证据 ID 通过门禁。

**实施内容：**

- 所有 model/evaluation/reverse-identification evidence ID 必须属于 corpus。
- evidence anchor 必须映射到 metadata、transcript 状态和 evidence index 条目。
- topic model 的两个 evidence ID必须是两个不同视频。
- transcript 缺失的视频只能作为 metadata evidence，不能支撑表达/脚本结论。
- 输出 orphan、missing、duplicate 和 type-mismatch 引用清单。

**验收标准：**

- [x] 15 个伪造 ID无法满足 evidence minimum。
- [x] 同一个 ID重复两次不满足“两条证据”。
- [x] 缺 transcript 的视频不能支撑语气和脚本结构模型。

**验证命令：**

```powershell
python -m pytest tests/quality/test_evidence_integrity.py -q
```

**依赖：** TF-019、TF-020。
**可能涉及文件：** `scripts/evidence_model.py`、`scripts/quality_engine.py`、`tests/quality/test_evidence_integrity.py`。
**规模：** M。

### TF-022：重定义 `passed` 与 `ready_for_use`，减少自我声明

**目标：** 成品状态由事实和独立评测结果共同决定。

**实施内容：**

- 明确 `passed` 是确定性流水线最低完整性，`ready_for_use` 必须首先要求 passed。
- evaluation/reverse JSON 中 Agent 自填 `passed` 仅作为声明，不是最终判定。
- quality engine 根据 case 完成度、引用完整性、边界响应和固定断言计算 evaluator verdict。
- reviewer/audit 的建议作为人工信号展示，不得单独翻转自动失败项。
- 报告列出 blocking checks 与 advisory checks。

**验收标准：**

- [x] `passed=false` 时不可能出现 `ready_for_use=true`。
- [x] 只把 scorecard 改为 true 不能通过。
- [x] reviewer 建议 ready 不能覆盖 schema 或 evidence failure。
- [x] 报告能解释每个 blocker 的证据。

**验证命令：**

```powershell
python -m pytest tests/quality/test_readiness_semantics.py -q
```

**依赖：** TF-020、TF-021。
**可能涉及文件：** `scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`tests/quality/test_readiness_semantics.py`。
**规模：** M。

### TF-023：改进转写倾倒、版权风险和乱码检查

**目标：** 不再只靠时间戳行数和单行长度判断长篇原文复制。

**实施内容：**

- 将最终 skill 与 transcript 做 n-gram/序列重叠检测，报告最长重叠和总体复制比例。
- 保留短引用允许规则，并对证据摘要与原文重叠设置不同阈值。
- 编码检查覆盖 replacement character、异常问号密度和 UTF-8 可解析性。
- 不因正常代码围栏或合理问句产生无关误报。
- 报告只输出短片段哈希或有限上下文，避免再次泄露原文。

**验收标准：**

- [x] 把 transcript 拆成 100 字一行仍能检测大段复制。
- [x] 合理短引用和改写摘要可以通过。
- [x] 正常 Markdown 代码块不会自动被判版权失败。

**验证命令：**

```powershell
python -m pytest tests/quality/test_copyright_overlap.py tests/quality/test_encoding.py -q
```

**依赖：** TF-021、TF-022。
**可能涉及文件：** `scripts/content_safety.py`、`scripts/quality_engine.py`、`tests/quality/test_copyright_overlap.py`。
**规模：** M。

### Checkpoint 3：可信质量门禁

- [x] 派生产物不会过期参与评分。
- [x] 零证据、伪造 ID、自填通过和 transcript dump 均无法进入 ready。
- [x] 质量报告能区分 blocker、warning、N/A 和修复建议。
- [x] 同一输入重复检查产生确定性结果。

## Phase 4：实现跨领域创作者泛化

### TF-024：把科技研究词典改造成可选 taxonomy preset

**目标：** 保留现有科技账号效果，但解除其全局默认地位。

**实施内容：**

- 定义 `TaxonomyPreset` 接口或数据结构。
- 将 THEME/HOOK/ARGUMENT/ENDING/ENTITY 常量迁入 `tech_creator` preset。
- 新增最小 `generic_zh_creator` preset，只包含跨领域结构信号。
- 运行输入记录使用的 preset 和版本。
- 未选择时默认 generic，而不是 tech。

**验收标准：**

- [x] 科技 fixture 使用 tech preset 时结果与迁移前基本一致。
- [x] 非科技 fixture 默认不被贴上 AI/Agent 主题。
- [x] preset 缺失或版本错误给出清晰错误。

**验证命令：**

```powershell
python -m pytest tests/research/test_taxonomy_presets.py -q
```

**依赖：** TF-006、TF-019。
**可能涉及文件：** `scripts/research_taxonomy.py`、`scripts/prepare_host_refinement.py`、`tests/research/test_taxonomy_presets.py`。
**规模：** M。

### TF-025：增加无领域假设的主题候选发现

**目标：** 从当前 corpus 自动发现主题候选，而不是只命中预设关键词。

**实施内容：**

- 基于标题、词频、共现和视频级文档频率生成候选主题，不直接把候选当最终人格结论。
- 为候选主题输出代表视频、区分词、覆盖率和置信度。
- 高频但无区分度的通用词进入 stop/filter 层。
- 宿主 Agent 可对候选主题重命名、合并、拒绝并保留审计记录。
- 不引入需要联网下载模型的硬依赖；高级模型作为可选增强。

**验收标准：**

- [x] 非科技 fixture 能产生其真实领域候选。
- [x] 主题候选均附带真实视频 ID。
- [x] 候选不足时返回低置信度，而不是编造主题。

**验证命令：**

```powershell
python -m pytest tests/research/test_topic_discovery.py -q
```

**依赖：** TF-024。
**可能涉及文件：** `scripts/topic_discovery.py`、`scripts/prepare_host_refinement.py`、`tests/research/test_topic_discovery.py`。
**规模：** M。

### TF-026：修正中文词语和重复短语分析

**目标：** 避免把整段连续中文当成一个 token 或抽取随机字符串块。

**实施内容：**

- 选择明确的轻量中文分词策略；如保留 `pypinyin`，必须说明真实用途，否则移除。
- 使用文档频率而非纯总词频降低单条长视频支配。
- 重复短语跨视频计数，不把同一视频多次重复等同于跨样本稳定风格。
- 输出 stopword 版本、tokenizer 版本和最小出现视频数。
- 保留原始片段 ID，方便宿主 Agent 回查。

**验收标准：**

- [x] 中文句子不会整句作为所谓“高频词”。
- [x] 重复短语至少跨两个视频才标为跨样本模式。
- [x] 非中文和中英混合文本不报错。

**验证命令：**

```powershell
python -m pytest tests/research/test_chinese_signals.py -q
```

**依赖：** TF-025。
**可能涉及文件：** `scripts/text_analysis.py`、`scripts/prepare_host_refinement.py`、`requirements.txt`、`tests/research/test_chinese_signals.py`。
**规模：** M。

### TF-027：把 ASR 专名复核改为领域可扩展并记录处理状态

**目标：** 专名清单不再只覆盖 AI 产品，且真正参与 ready 判定。

**实施内容：**

- entity dictionary 从 preset 加载，允许项目级扩展。
- 每个候选增加 unresolved/confirmed/corrected/ignored 状态和处理说明。
- 高影响未解决专名进入 blocker 或 warning，规则可解释。
- 修正项映射到 transcript 与最终 skill，不静默改写原始 ASR 文件。
- 对大小写、别名和中英文混写做归一化。

**验收标准：**

- [x] `review_required=true` 但全部未处理时不能被当成已完成审计。
- [x] 非科技品牌、人名和专业术语可通过 preset/项目词典加入。
- [x] 原始 ASR、修正层和最终引用保持可追溯。

**验证命令：**

```powershell
python -m pytest tests/research/test_entity_review.py -q
```

**依赖：** TF-024、TF-026。
**可能涉及文件：** `scripts/entity_review.py`、`scripts/prepare_host_refinement.py`、`tests/research/test_entity_review.py`。
**规模：** M。

### TF-028：增加跨领域端到端回归套件

**目标：** 用至少两个非科技账号样本证明项目真正泛化。

**实施内容：**

- 增加科技、非科技 A、非科技 B 三套短小脱敏 corpus。
- 对每套检查主题候选、Hook、论证、边界、证据覆盖和 ready 前置条件。
- 断言非科技样本不会系统性输出科技标签。
- 记录 preset 和通用发现对结果的贡献。
- 将套件纳入 CI，但保持总时长适合每次提交运行。

**验收标准：**

- [x] 三套 corpus 均能生成完整 draft 和 host refinement package。
- [x] 非科技 corpus 的主要候选主题与 fixture 设计一致。
- [x] 无任何真实创作者长文本进入仓库。

**验证命令：**

```powershell
python -m pytest tests/integration/test_cross_domain_pipeline.py -q
```

**依赖：** TF-024、TF-025、TF-026、TF-027。
**可能涉及文件：** `tests/fixtures/corpora/**`、`tests/integration/test_cross_domain_pipeline.py`。
**规模：** M。

### Checkpoint 4：领域泛化

- [x] 科技 preset 保持可用。
- [x] 通用默认不隐含科技领域。
- [x] 至少两个非科技 corpus 通过端到端 draft 测试。
- [x] 专名、主题、短语均有置信度和证据来源。

## Phase 5：供应商可靠性、性能与可观测性

### TF-029：统一请求重试、限流和 deadline

**目标：** 对网络异常、429、5xx 和异步 ASR 轮询提供一致且有上限的恢复行为。

**实施内容：**

- 建立统一 retry policy，支持最大尝试、指数退避、抖动和 Retry-After。
- 429、可重试 5xx、连接超时和读取超时分类处理。
- 4xx 参数/鉴权错误默认不重试。
- DashScope poll 增加总 deadline 和未知状态处理，FAILED 必须失败。
- 响应错误只保留脱敏摘要。

**验收标准：**

- [x] 429 按 Retry-After 重试且不超过总 deadline。
- [x] 持续 5xx 最终失败并记录尝试次数。
- [x] poll 不会无限循环。
- [x] 401 不重复请求。

**验证命令：**

```powershell
python -m pytest tests/providers/test_retry_policy.py tests/providers/test_asr_polling.py -q
```

**依赖：** TF-011、TF-015。
**可能涉及文件：** `scripts/retry_policy.py`、`scripts/provider_adapters.py`、`tests/providers/test_retry_policy.py`。
**规模：** M。

### TF-030：增加结构化日志、步骤耗时和问题摘要

**目标：** 不读取大量原始日志也能判断慢在哪里、失败在哪里和是否可恢复。

**实施内容：**

- 每个步骤记录开始/结束时间、duration、输入/成功/失败/跳过数量。
- 统一错误代码，例如 NETWORK_TIMEOUT、RATE_LIMIT、INVALID_MEDIA、ASR_PARSE_FAILED、STALE_ARTIFACT。
- JSON 日志和人类可读控制台输出共享同一事件模型。
- 错误详情经过 redaction，限制长度。
- run summary 汇总最慢步骤、失败步骤和下一步命令。

**验收标准：**

- [x] 离线运行可从 run summary 看出每步耗时和数量。
- [x] 相同错误有稳定 error code。
- [x] 日志中不存在 token 和签名 URL。

**验证命令：**

```powershell
python -m pytest tests/test_structured_logging.py -q
```

**依赖：** TF-009、TF-015、TF-029。
**可能涉及文件：** `scripts/logging_utils.py`、`scripts/pipeline_models.py`、`scripts/run_creator_skill_build.py`、`tests/test_structured_logging.py`。
**规模：** M。

### TF-031：减少 host refinement 对 transcript 的重复读取

**目标：** 大样本研究准备阶段每个 transcript 只解析一次。

**实施内容：**

- 建立只读 corpus cache，在一次 prepare 执行中共享规范文本和统计。
- corpus index、signals、matrix、entity review、brief 使用同一数据对象。
- 对单文件和总 corpus 设置合理最大读取字符数；超限给出分层索引策略。
- 增加性能基准，比较重构前后读取次数和耗时。

**验收标准：**

- [x] 单次 prepare 中每个 transcript 只发生一次完整读取。
- [x] 50 个中等 transcript 的准备耗时不回退。
- [x] 输出与等价 fixture 的旧逻辑保持语义一致。

**验证命令：**

```powershell
python -m pytest tests/performance/test_corpus_loading.py -q
```

**依赖：** TF-006、TF-024。
**可能涉及文件：** `scripts/corpus.py`、`scripts/prepare_host_refinement.py`、`tests/performance/test_corpus_loading.py`。
**规模：** M。

### TF-032：限制媒体并发并实现本地产物保留策略

**目标：** 在提升吞吐的同时避免 CPU、内存和磁盘失控。

**实施内容：**

- 下载、ffmpeg、ASR 使用独立并发上限。
- ffmpeg 默认保守并发，允许按 CPU 和磁盘能力配置。
- compatible chat base64 前检查分片大小，避免错误配置导致并发内存峰值。
- 支持按 retention policy 清理视频、音频、chunk 和 raw provider JSON。
- cleanup 先 dry-run，删除前验证目标位于 run 目录。

**验收标准：**

- [x] 并发上限分别生效。
- [x] 超大 ASR 分片在编码前被拒绝或重新切片。
- [x] dry-run 与实际清理列表一致。
- [x] 清理不会越出目标 run 目录。

**验证命令：**

```powershell
python -m pytest tests/performance/test_concurrency_limits.py tests/test_retention_policy.py -q
```

**依赖：** TF-008、TF-012、TF-017、TF-030。
**可能涉及文件：** `scripts/run_creator_skill_build.py`、`scripts/retention.py`、`tests/performance/test_concurrency_limits.py`。
**规模：** M。

### Checkpoint 5：可靠性与运行可见性

- [x] 所有请求有 deadline，异步轮询不会无限等待。
- [x] 日志能回答失败位置、失败数量、耗时和恢复方式。
- [x] 大样本准备不重复读取完整 transcript。
- [x] 并发和清理均有安全上限。

## Phase 6：统一配置并拆分核心架构

### TF-033：建立单一、类型化 Settings 模型

**目标：** 消除三个 env loader、代码默认值和文档模板之间的漂移。

**实施内容：**

- 定义一个 Settings 模型，集中字段、类型、默认值、范围、secret 属性和说明。
- `.env`、环境变量和 CLI override 使用明确优先级。
- 配置解析支持布尔、整数、可选值和枚举，并对非法值快速失败。
- 纳入当前遗漏的 pagination 和 ASR retry 配置。
- 每次 run 保存非敏感规范快照和 settings schema version。

**验收标准：**

- [x] 所有运行脚本使用同一个 Settings loader。
- [x] 默认 ASR provider/model 在所有入口一致。
- [x] 非法整数、布尔和 endpoint 在启动前失败。
- [x] secret 字段不会进入普通序列化。

**验证命令：**

```powershell
python -m pytest tests/test_settings.py -q
```

**依赖：** TF-004、TF-015、TF-029。
**可能涉及文件：** `scripts/settings.py`、`scripts/build_creator_skill.py`、`scripts/provider_adapters.py`、`tests/test_settings.py`。
**规模：** M。

### TF-034：由 Settings 自动生成配置模板和文档表

**目标：** 根 `.env.example`、参考模板、配置文档和代码默认值保持单一事实来源。

**实施内容：**

- 提供生成或校验脚本，输出 `.env.example` 和配置参考表。
- 区分 generic 默认和 TikHub App V3 推荐 preset。
- 添加 CI drift test，生成结果与仓库文件不一致时失败。
- 标注 deprecated、unused 和 advanced 配置。
- `--include-config` 改为完整安全脱敏，不再展示 secret 片段。

**验收标准：**

- [x] 根模板与参考模板的差异均有意图说明。
- [x] 代码新增配置但未更新文档时 CI 失败。
- [x] 四个遗漏配置项进入 schema、模板和快照。

**验证命令：**

```powershell
python scripts/generate_config_docs.py --check
python -m pytest tests/test_config_docs_sync.py -q
```

**依赖：** TF-033。
**可能涉及文件：** `scripts/generate_config_docs.py`、`.env.example`、`references/configuration.md`、`tests/test_config_docs_sync.py`。
**规模：** M。

### TF-035：拆分 `creator_pipeline.py`

**目标：** 在行为已有回归保护后，把数据解析、媒体、构建和质量职责分开。

**实施内容：**

- metadata normalization 移入独立模块。
- download/media functions 移入 media 模块。
- transcript parsing 使用 TF-006 模块。
- skill draft builder 移入 builder 模块。
- quality 逻辑统一指向 quality engine。
- 原 CLI 文件保留兼容 facade，不复制逻辑。

**验收标准：**

- [x] `creator_pipeline.py` 主要只保留 CLI 路由和兼容导出。
- [x] 任何公共 CLI 参数和主要产物路径没有无说明变化。
- [x] 全部回归测试通过。

**验证命令：**

```powershell
python -m pytest -q
python scripts/self_test.py
```

**依赖：** TF-010、TF-018 至 TF-023、TF-033。
**可能涉及文件：** `scripts/creator_pipeline.py`、`scripts/metadata.py`、`scripts/media.py`、`scripts/skill_builder.py`。
**规模：** M，必要时拆成多个顺序子任务。

### TF-036：拆分 `prepare_host_refinement.py`

**目标：** 分离 corpus、signal、coverage、模板和 brief 渲染。

**实施内容：**

- corpus 和 transcript cache 使用 TF-031 模块。
- taxonomy/topic/entity 使用 Phase 4 模块。
- coverage 和 quality 派生逻辑放入 quality engine。
- Markdown/JSON 模板放入 templates 模块或 assets。
- `prepare_host_refinement.py` 只负责编排和写产物。

**验收标准：**

- [x] 主文件不再包含大段 schema/template 字符串和领域常量。
- [x] prepare 输出路径和 schema version 符合计划。
- [x] 跨领域和质量测试全部通过。

**验证命令：**

```powershell
python -m pytest tests/research tests/quality tests/integration -q
```

**依赖：** TF-024 至 TF-031、TF-035。
**可能涉及文件：** `scripts/prepare_host_refinement.py`、`scripts/refinement_templates.py`、`scripts/corpus.py`、`scripts/quality_engine.py`。
**规模：** M，必要时拆成多个顺序子任务。

### TF-037：处理遗留研究路径、死代码和死配置

**目标：** 删除或正式集成会误导维护者的旧实现。

**实施内容：**

- 审计 `scripts/research/quality_check.py` 的 `knowledge/research` 路径与当前 run 结构。
- 决定 celebrity prompts 是通用研究模板、可选 preset 还是应重命名。
- 删除或重新接入 `collect_transcript_corpus`、`style_research.json` 等孤立路径。
- 对 `AUTO_RESUME`、token budget、`ALI_ASR_APP_KEY` 明确实现、废弃或删除。
- 删除未使用依赖；如保留 `pypinyin`，必须有代码和测试用途。

**验收标准：**

- [x] 无未引用的配置项和运行依赖，或每个例外均有注释。
- [x] 旧 quality CLI 使用当前 run 结构或明确标记 deprecated。
- [x] `rg` 搜索不到无迁移说明的旧产物路径。

**验证命令：**

```powershell
python -m pytest -q
python -m ruff check .
python -m pip check
```

**依赖：** TF-034、TF-035、TF-036。
**可能涉及文件：** `scripts/research/quality_check.py`、`scripts/research/merge_research.py`、`requirements.txt`、`references/prompts/celebrity/**`。
**规模：** M。

### TF-038：增加 CLI 兼容测试和旧运行目录诊断

**目标：** 架构拆分后仍能安全处理现有用户命令和旧 run。

**实施内容：**

- 为每个 CLI 子命令增加 `--help`、合法参数和错误参数测试。
- 准备最小 legacy run fixture，检查读取、诊断和迁移提示。
- 新格式增加 schema version；旧格式不自动声称 verified。
- 提供 `inspect-run` 或等价诊断命令，输出格式版本、缺失 manifest 和建议动作。

**验收标准：**

- [x] README/SKILL 中现有命令仍可运行或有明确迁移替代。
- [x] legacy run 不会因缺 manifest 被误判 ready。
- [x] 所有 CLI 错误使用稳定非零退出码。

**验证命令：**

```powershell
python -m pytest tests/cli tests/integration/test_legacy_run.py -q
```

**依赖：** TF-035、TF-036、TF-037。
**可能涉及文件：** `scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`tests/cli/**`、`tests/integration/test_legacy_run.py`。
**规模：** M。

### Checkpoint 6：架构和配置收敛

- [x] 配置只有一个事实来源。
- [x] 两个超大核心文件已变成薄编排层。
- [x] 无未解释死代码、死配置和未使用运行依赖。
- [x] CLI 与旧 run 有自动化兼容证据。

## Phase 7：持续集成、文档和发布验收

### TF-039：建立跨平台 CI 质量门禁

**目标：** 每次提交自动执行与本计划完成定义一致的验证。

**实施内容：**

- CI 至少覆盖 Windows 和 Linux，以及项目声明的最低/主要 Python 版本。
- 执行 ruff、pytest、schema/config drift、pip check 和离线 self-test。
- 测试不得读取仓库 `.env` 或调用真实网络。
- 上传测试报告和覆盖率摘要，不上传 transcript fixture 原文以外的数据。
- 关键门禁失败阻止合并。

**验收标准：**

- [x] 新 clone 在两个平台均可通过 CI。
- [x] 故意制造配置漂移、schema 错误或测试失败时 CI 会红。
- [x] CI 日志不显示任何 secret。

**验证命令：**

```powershell
python -m ruff check .
python -m pytest --cov=scripts --cov-report=term-missing -q
python scripts/self_test.py
```

**依赖：** TF-001 至 TF-038。
**可能涉及文件：** `.github/workflows/ci.yml`、`pyproject.toml`、`README.md`。
**规模：** M。

### TF-040：重写开发者快速开始、故障排查和安全文档

**目标：** 用户不必“把仓库交给 AI”才能完成基本安装、离线测试和运行诊断。

**实施内容：**

- README 增加安装、虚拟环境、配置、离线 demo、真实运行、精修和质量检查最短路径。
- 增加常见失败表：TikHub 参数、ffmpeg、429、ASR endpoint、部分 transcript、stale artifact。
- 增加安全说明：提示注入、SSRF、凭证、OSS 生命周期、授权和删除。
- SKILL、pipeline、host refinement 文档与实际命令同步。
- 增加架构图和产物状态说明，但不重复所有实现细节。

**验收标准：**

- [x] 新用户可只按 README 完成离线自测。
- [x] 所有文档命令在干净环境验证过。
- [x] 不再要求重写 evidence 后手工执行未记录的隐含命令。

**验证命令：**

```powershell
python scripts/verify_docs_commands.py
```

**依赖：** TF-034、TF-038、TF-039。
**可能涉及文件：** `README.md`、`SKILL.md`、`references/pipeline.md`、`references/host_refinement.md`。
**规模：** M。

### TF-041：增加维护、披露和版本发布文件

**目标：** 为开源协作、漏洞披露和产物格式演进提供明确机制。

**实施内容：**

- 增加 `SECURITY.md`，说明漏洞报告和敏感日志处理。
- 增加 `CONTRIBUTING.md`，说明测试、fixture 脱敏和任务粒度。
- 增加 `CHANGELOG.md` 和语义版本策略。
- 明确 CLI、run schema、persona schema 和 taxonomy preset 的版本关系。
- 首个改进版发布前列出 breaking changes 和 legacy run 处理方式。

**验收标准：**

- [x] 安全报告有非公开渠道或明确流程。
- [x] 贡献指南要求新增行为必须有测试。
- [x] 所有 schema/preset 版本变化进入 changelog。

**验证命令：**

```powershell
python scripts/verify_release_metadata.py
```

**依赖：** TF-038、TF-039、TF-040。
**可能涉及文件：** `SECURITY.md`、`CONTRIBUTING.md`、`CHANGELOG.md`、`pyproject.toml`。
**规模：** M。

### TF-042：执行最终完成审计和发布候选验证

**目标：** 用当前代码、测试和产物证据证明本计划全部完成。

**实施内容：**

- 按第 9 节完成定义逐项审计，不以“测试绿”替代需求覆盖。
- 执行全量静态检查、单元测试、集成测试、跨领域测试和离线 self-test。
- 用失败 fixture 验证非零退出码、安全拒绝和质量 blocker。
- 用最小 legacy run 验证诊断和迁移。
- 如获用户授权，再执行一次受控真实 API smoke；未授权时明确标记未做，不影响离线完成项。
- 生成发布候选审计摘要，记录命令、版本和剩余风险。

**验收标准：**

- [x] `plan/TODO.md` 所有必需项有直接验证证据。
- [x] 所有 P0/P1 问题均关闭，没有以 TODO 注释代替修复。
- [x] 当前工作区没有意外生成物、secret 或无关改动。
- [x] 发布审计明确区分已验证、未验证和需外部授权的内容。

**验证命令：**

```powershell
python -m ruff check .
python -m mypy scripts
python -m pytest --cov=scripts --cov-report=term-missing -q
python scripts/self_test.py
python scripts/config_check.py --env .env --strict
git status --short --branch
```

**依赖：** TF-001 至 TF-041。
**可能涉及文件：** `plan/TODO.md`、`plan/RELEASE_AUDIT.md`。
**规模：** M。

## 8. 并行执行建议

只有在共享契约已经固定后才并行：

| 可并行组 | 前置条件 | 注意事项 |
|---|---|---|
| TF-004 与 TF-006 | TF-001/002 完成 | 分别修改 run creation 与 ASR parser，避免同时重构公共 IO |
| TF-011 与 TF-015 | 测试 fixture 完成 | 先约定 redaction 与 URL error 的接口 |
| TF-019 与 TF-020 | TF-018 计算接口固定 | 一个处理 coverage，一个处理 schema，不同时改 readiness 聚合 |
| TF-025 与 TF-027 | TF-024 preset 接口固定 | 共用 taxonomy contract，不直接修改对方模块 |
| TF-029 与 TF-031 | 前置功能稳定 | 一个处理 provider，一个处理本地 corpus |
| TF-040 与 TF-041 | CLI 和 schema 稳定 | 文档不得提前描述尚未实现行为 |

必须串行：

- TF-006 → TF-007 → TF-008。
- TF-018 → TF-019 → TF-021 → TF-022。
- TF-024 → TF-025/026/027 → TF-028。
- TF-035 → TF-036 → TF-037 → TF-038。
- TF-039 → TF-042。

## 9. 项目级 Definition of Done

只有下列条件全部满足，系统优化目标才算完成。

### 9.1 正确性

- [x] ASR 片段不重复遍历，合法重复话术保留，0 时间戳保留。
- [x] 多 chunk transcript 具有正确全局时间线。
- [x] 非法参数在创建运行产物前失败。
- [x] 同一秒并发创建 run 不碰撞。
- [x] 缓存复用由输入/配置/工具指纹证明。

### 9.2 失败语义

- [x] workflow 状态、步骤结果、质量报告和进程退出码一致。
- [x] 部分失败不会记录为 succeeded。
- [x] 基础质量失败默认返回非零。
- [x] 每个失败有稳定 error code 和最短修复提示。

### 9.3 安全与治理

- [x] SSRF、路径穿越、无限下载和伪装媒体测试通过。
- [x] transcript 提示注入被隔离为数据。
- [x] 日志、快照和研究包不含 secrets 或签名 URL。
- [x] OSS 与本地媒体有可审计保留/清理策略。
- [x] 每个 run 记录 rights basis 和来源边界。

### 9.4 质量门禁

- [x] coverage 在质量检查时是最新的。
- [x] 空 bucket 不产生虚高分数。
- [x] JSON Schema 在运行时验证。
- [x] evidence ID 全部属于 corpus 且类型匹配。
- [x] `ready_for_use` 必须依赖 `passed`。
- [x] 自填 `passed=true`、伪造 ID或堆字数不能绕过门禁。
- [x] transcript dump 使用内容重叠检测。

### 9.5 泛化

- [x] 科技 taxonomy 是可选 preset。
- [x] 默认 generic 流程不包含科技领域假设。
- [x] 至少两个非科技 corpus 通过端到端回归。
- [x] 主题、短语和实体均可追溯到视频证据。

### 9.6 工程质量

- [x] pytest、ruff、mypy、pip check 和离线 self-test 全部通过。
- [x] CI 覆盖 Windows、Linux 和声明的 Python 版本。
- [x] 两个超大核心脚本已拆成可测试模块。
- [x] 配置、模板和文档由单一 Settings 模型保持同步。
- [x] 无真实凭证、未授权长文本或运行产物进入 Git。

### 9.7 文档与兼容性

- [x] 新用户可以按 README 完成离线运行。
- [x] 旧 run 有明确 legacy 诊断，不被误判为 verified。
- [x] breaking changes、schema 版本和迁移方式进入 changelog。
- [x] 最终发布审计保存了所有验证命令和结果。

## 10. 风险与缓解措施

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 先大规模重构导致行为漂移 | 高 | TF-001 至 TF-003 先建立回归基线；重构放在 Phase 6 |
| 供应商真实响应与 fixture 不一致 | 高 | fixture 覆盖已知变体；真实 smoke 需显式授权；未知结构快速失败并保存脱敏响应 |
| 安全限制误伤合法短链/CDN | 中 | 来源域名与下载 CDN策略分离；提供可审计 allowlist 扩展 |
| 新质量门禁使旧成品全部变 false | 中 | 引入 schema version 和 legacy_unverified；不静默迁移 |
| 领域发现算法产生无意义主题 | 中 | 候选只作为线索；输出置信度和证据；宿主 Agent 可拒绝 |
| 依赖增加导致安装复杂 | 中 | 优先标准库；新增依赖必须说明用途、版本范围和 license |
| CI 跨平台 ffmpeg 不稳定 | 中 | 单元测试 mock 工具；仅对最小集成场景安装固定 ffmpeg |
| 计划任务过多导致跨会话失焦 | 中 | 每次只执行一个 TF 编号；在 TODO 记录验证结果和下一项 |

## 11. 提交与审查建议

- 每个 TF 任务建议形成一个独立、可回滚的提交或变更集。
- 纯重构与行为修改分开提交。
- 每个变更集优先控制在约 100 至 300 行人工逻辑改动；fixture 和自动生成 schema 可单独说明。
- 提交前检查 `git status`，只包含本任务相关文件。
- P0、安全和质量门禁任务必须进行独立代码审查。
- 不允许以“后续清理”方式合并会破坏正确性或安全边界的临时代码。

## 12. 计划维护规则

- 新发现的 blocker 先写入第 2.2 节，并关联新的或已有 TF 编号。
- 任务依赖变化时同时更新第 5 节和 `plan/TODO.md`。
- 只有验收命令实际通过后才能勾选完成。
- 任务被替代时标记“已被 TF-xxx 替代”，不得直接删除历史。
- 最终审计完成前，本文件状态保持“实施中”或“待实施”。
