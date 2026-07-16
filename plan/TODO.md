# 千人千面项目系统优化执行清单

> 主计划：`plan/PLAN.md`
> 使用方式：AI 每次只领取一个 TF 编号，确认依赖、实现、运行验收命令、记录证据，然后再勾选。
> 当前状态：42 / 42 个任务完成。

## 执行状态约定

- `[ ]`：尚未开始。
- `[~]`：实施中，但尚未满足全部验收标准。
- `[x]`：已完成，且验收命令实际通过。
- `[!]`：存在 blocker；必须在执行记录中说明，不得当作完成。
- `[-]`：经用户确认取消或被其他任务替代；必须记录理由和替代任务。

## AI 开始任务前检查

- [ ] 已读取 `plan/PLAN.md` 中对应任务的目标、实施内容和验收标准。
- [ ] 已确认所有依赖任务为 `[x]`。
- [ ] 已运行 `git status --short --branch` 并识别用户已有改动。
- [ ] 已决定需要新增或先修改哪些测试。
- [ ] 已确认不会读取、输出或提交 `.env`、token、签名 URL和真实用户长文本。
- [ ] 已把本次范围限制在一个 TF 编号内。

## Phase 0：可重复验证基线

- [x] **TF-001 建立隔离测试与开发工具基线**
  - 依赖：无。
  - 交付：`pyproject.toml`、开发依赖、pytest/ruff/mypy 基础配置、`tests/conftest.py`。
  - 必验：`pytest --collect-only`、ruff、虚拟环境内 `pip check`。

- [x] **TF-002 建立脱敏回归 fixture 矩阵**
  - 依赖：TF-001。
  - 交付：TikHub、ASR、恶意输入、非科技 corpus fixtures。
  - 必验：无网络、无 `.env` 可读取；secret 扫描无命中。

- [x] **TF-003 把离线自测提升为 pytest 集成测试**
  - 依赖：TF-001、TF-002。
  - 交付：可断言的 offline pipeline 集成测试；保留 `scripts/self_test.py`。
  - 必验：self-test 与 pytest 集成路径都通过，失败场景被正确断言。

### Checkpoint 0

- [x] 所有已确认 bug 都有失败测试或带理由的临时 xfail。
- [x] 单元/集成测试不调用真实网络。
- [x] `scripts/self_test.py` 与 pytest 共享 fixture 或公共 helper。

## Phase 1：正确性、状态和恢复

- [x] **TF-004 校验 CLI 输入并生成不可碰撞 Run ID**
  - 依赖：TF-001、TF-002。
  - 关键断言：1000 次 run ID 唯一；sample_count <= 0 在创建目录前失败。

- [x] **TF-005 实现原子写入和可恢复 workflow 状态**
  - 依赖：TF-004。
  - 关键断言：写入中断不破坏旧 JSON；workflow 损坏有明确错误。

- [x] **TF-006 重写 ASR 响应解析**
  - 依赖：TF-001、TF-002。
  - 关键断言：3 段仍为 3 段；不同时间重复话术保留；0 时间戳保留；未知结构失败。

- [x] **TF-007 修复音频分片合并和全局时间线**
  - 依赖：TF-006。
  - 关键断言：chunk offset 正确；时间戳单调；边界去重不误删合法重复。

- [x] **TF-008 为高成本产物增加输入与配置指纹**
  - 依赖：TF-005、TF-006、TF-007。
  - 关键断言：模型、参数、源文件变化后缓存失效；指纹不含 secret。

- [x] **TF-009 统一步骤结果、最终状态和退出码**
  - 依赖：TF-005、TF-008。
  - 关键断言：quality false 默认非零；workflow 与退出码一致；report-only 显式区分。

- [x] **TF-010 建立阶段覆盖率和部分失败门槛**
  - 依赖：TF-009。
  - 关键断言：selected=50/transcribed=1 不能 passed；离线 transcript 模式使用正确门槛。

### Checkpoint 1

- [x] ASR 重复、时间戳、Run ID、非法参数和退出码回归全部通过。
- [x] 关键步骤 partial/failed 不再记录为 succeeded。
- [x] 只有有指纹证据的产物能被自动复用。
- [x] 原离线 self-test 继续通过。

## Phase 2：安全与数据治理

- [x] **TF-011 实现网络访问策略并阻断 SSRF**
  - 依赖：TF-001、TF-002。
  - 关键断言：localhost、私网、metadata service、重定向到私网全部被拒绝。

- [x] **TF-012 限制下载资源并验证媒体文件**
  - 依赖：TF-011。
  - 关键断言：超限中止；伪装 HTML/JSON 被拒绝；有效媒体通过；重复 ID 不并发覆盖。

- [x] **TF-013 规范 video ID 并保证路径包含关系**
  - 依赖：TF-004。
  - 关键断言：`..`、绝对路径、设备路径和冲突 ID得到安全处理。

- [x] **TF-014 隔离 transcript 提示注入和 Markdown 控制内容**
  - 依赖：TF-002、TF-013。
  - 关键断言：恶意 transcript 只作为数据，不改变 brief 指令，不诱导读取 `.env`。

- [x] **TF-015 加强配置脱敏和研究数据最小化**
  - 依赖：TF-005。
  - 关键断言：快照不保留 secret 首尾；compact metadata 不含下载签名 URL；错误日志被 scrub。

- [x] **TF-016 实现 OSS 对象隔离、生命周期和清理**
  - 依赖：TF-008、TF-015。
  - 关键断言：跨 run 不覆盖；成功/失败均有清理状态；mock 删除流程通过。

- [x] **TF-017 增加 rights basis、来源溯源和保留策略**
  - 依赖：TF-004、TF-015、TF-016。
  - 关键断言：新 run 有 rights basis；ready 成品有来源边界；清理支持 dry-run。

### Checkpoint 2

- [x] 所有外部 URL、路径、标题、transcript 和 provider 响应按不可信输入处理。
- [x] 日志、快照、compact metadata 和 host research package 不含 secrets/签名 URL。
- [x] Agent 研究协议明确禁止执行语料中的指令。
- [x] OSS 和本地产物保留/清理均可审计。

## Phase 3：可信质量门禁

- [x] **TF-018 质量检查时重算或验证派生产物新鲜度**
  - 依赖：TF-008。
  - 关键断言：修改 evidence 后立即反映新覆盖；修改 transcript 后旧 signal 被判 stale。

- [x] **TF-019 修正 coverage denominator、N/A 和 evidence 解析**
  - 依赖：TF-002、TF-018。
  - 关键断言：零 evidence 不再得到 0.6；空 bucket 为 N/A；ID 使用结构化匹配。

- [x] **TF-020 执行 JSON Schema 运行时验证**
  - 依赖：TF-001、TF-018。
  - 关键断言：缺字段、错类型、多余字段、非法状态均失败；模板不能 ready。

- [x] **TF-021 验证 evidence/persona/corpus 引用完整性**
  - 依赖：TF-019、TF-020。
  - 关键断言：伪造 ID、重复 ID、缺 transcript 的表达证据均不能通过。

- [x] **TF-022 重定义 passed 与 ready，降低自我声明权重**
  - 依赖：TF-020、TF-021。
  - 关键断言：passed=false 时 ready 必为 false；手改 scorecard=true 无法绕过。

- [x] **TF-023 改进 transcript dump、版权重叠和乱码检查**
  - 依赖：TF-021、TF-022。
  - 关键断言：拆行复制仍能检出；短引用可过；正常代码块不被误伤。

### Checkpoint 3

- [x] 派生报告具备 freshness 证据。
- [x] 零 evidence、伪造 ID、自填通过和堆字数均不能 ready。
- [x] schema 验证和跨文件引用验证均为 blocker。
- [x] 质量报告区分 blocker、warning、N/A 和修复命令。

## Phase 4：跨领域泛化

- [x] **TF-024 将科技词典改为可选 taxonomy preset**
  - 依赖：TF-006、TF-019。
  - 关键断言：默认 generic；tech preset 保持效果；非科技样本不被强贴科技标签。

- [x] **TF-025 增加无领域假设的主题候选发现**
  - 依赖：TF-024。
  - 关键断言：候选主题带视频证据和置信度；证据不足时不编造。

- [x] **TF-026 修正中文词语和重复短语分析**
  - 依赖：TF-025。
  - 关键断言：整句中文不再充当 token；跨视频重复与单视频重复被区分。

- [x] **TF-027 让 ASR 专名复核可扩展并记录状态**
  - 依赖：TF-024、TF-026。
  - 关键断言：未处理高影响专名不能被视为已完成；修正结果可追溯。

- [x] **TF-028 增加跨领域端到端回归套件**
  - 依赖：TF-024、TF-025、TF-026、TF-027。
  - 关键断言：科技+两个非科技 corpus 均生成完整 draft/refinement package。

### Checkpoint 4

- [x] 默认 generic research 不含 AI/科技领域假设。
- [x] 两个非科技 corpus 通过端到端回归。
- [x] 主题、短语和专名均有真实视频证据与置信度。

## Phase 5：可靠性、性能和可观测性

- [x] **TF-029 统一网络重试、限流和 deadline**
  - 依赖：TF-011、TF-015。
  - 关键断言：429/5xx/timeout 分类正确；401 不重试；poll 不无限等待。

- [x] **TF-030 增加结构化日志、步骤耗时和错误代码**
  - 依赖：TF-009、TF-015、TF-029。
  - 关键断言：run summary 可见步骤耗时/数量/最短恢复方式；日志无 secret。

- [x] **TF-031 减少 host refinement 对 transcript 的重复读取**
  - 依赖：TF-006、TF-024。
  - 关键断言：单次 prepare 每个 transcript 只完整读取一次；输出语义不回退。

- [x] **TF-032 限制媒体并发并执行保留/清理策略**
  - 依赖：TF-008、TF-012、TF-017、TF-030。
  - 关键断言：下载/ffmpeg/ASR 独立限流；超大分片编码前拒绝；清理不越界。

### Checkpoint 5

- [x] 所有外部请求和异步轮询都有总 deadline。
- [x] 日志可用于定位瓶颈和恢复步骤。
- [x] 大样本 prepare 不重复读取完整 corpus。
- [x] 并发、内存和磁盘使用有安全上限。

## Phase 6：配置与架构收敛

- [x] **TF-033 建立单一类型化 Settings 模型**
  - 依赖：TF-004、TF-015、TF-029。
  - 关键断言：所有入口默认一致；非法配置快速失败；secret 不普通序列化。

- [x] **TF-034 由 Settings 生成配置模板和文档表**
  - 依赖：TF-033。
  - 关键断言：配置漂移测试生效；遗漏的 pagination/retry 配置进入快照和文档。

- [x] **TF-035 拆分 `creator_pipeline.py`**
  - 依赖：TF-010、TF-018 至 TF-023、TF-033。
  - 关键断言：主文件成为薄 CLI/facade；行为和产物路径保持兼容。

- [x] **TF-036 拆分 `prepare_host_refinement.py`**
  - 依赖：TF-024 至 TF-031、TF-035。
  - 关键断言：领域常量、模板、corpus、quality 从编排文件移出；输出不漂移。

- [x] **TF-037 处理遗留研究路径、死代码和死配置**
  - 依赖：TF-034、TF-035、TF-036。
  - 关键断言：旧 quality 路径有归属；死配置实现/废弃/删除；未使用依赖清理。

- [x] **TF-038 增加 CLI 兼容测试和旧 run 诊断**
  - 依赖：TF-035、TF-036、TF-037。
  - 关键断言：现有命令可用或有迁移；legacy run 不会误判 verified/ready。

### Checkpoint 6

- [x] Settings 是配置单一事实来源。
- [x] 两个超大脚本已成为薄编排层。
- [x] 无未解释的死代码、死配置和未使用运行依赖。
- [x] CLI 与 legacy run 有自动化兼容证据。

## Phase 7：CI、文档和发布验收

- [x] **TF-039 建立 Windows/Linux 跨平台 CI**
  - 依赖：TF-001 至 TF-038。
  - 关键断言：ruff、pytest、schema/config drift、pip check、self-test 均为门禁；CI 无真实网络/secret。

- [x] **TF-040 重写开发者快速开始、排障和安全文档**
  - 依赖：TF-034、TF-038、TF-039。
  - 关键断言：新用户可按 README 完成离线自测；所有文档命令已验证。

- [x] **TF-041 增加维护、漏洞披露和版本发布文件**
  - 依赖：TF-038、TF-039、TF-040。
  - 关键断言：SECURITY、CONTRIBUTING、CHANGELOG、schema/version 策略齐全。

- [x] **TF-042 执行最终完成审计和发布候选验证**
  - 依赖：TF-001 至 TF-041。
  - 关键断言：项目级 Definition of Done 全部有直接证据；生成 `plan/RELEASE_AUDIT.md`。

### Checkpoint 7

- [x] CI 在 Windows/Linux 全绿。
- [x] README、SKILL、pipeline、host refinement 与当前行为一致。
- [x] 所有 P0/P1 问题关闭。
- [x] 完成审计明确列出已验证、未验证和需外部授权项目。

## 每任务完成后必做检查

- [ ] 运行对应任务的专项测试。
- [ ] 运行受影响模块的相邻测试。
- [ ] 运行 `python scripts/self_test.py`，除非任务明确与运行链路无关；不运行时记录理由。
- [ ] 运行 `python -m ruff check .`。
- [ ] 检查 `git diff --check`。
- [ ] 检查 `git status --short`，确认没有 `.env`、运行产物、缓存、日志或无关文件。
- [ ] 更新本清单任务状态。
- [ ] 在下面执行记录中填写验证证据。

## 执行记录

每完成一个任务追加一条，禁止覆盖历史：

```text
### TF-XXX / YYYY-MM-DD

- 状态：completed / partial / blocked
- 修改摘要：
- 涉及文件：
- 验收命令：
- 命令结果：
- 新增测试：
- 剩余风险：
- 下一建议任务：
```

### TF-001 / 2026-07-15

- 状态：completed
- 修改摘要：建立独立开发依赖、pytest/Ruff/Mypy/coverage 配置和脱敏测试 fixture；补齐开发环境文档；修复静态检查发现的存量未使用变量与类型推断问题，不改变运行时业务行为。
- 涉及文件：`pyproject.toml`、`requirements-dev.txt`、`README.md`、`tests/conftest.py`、`tests/test_test_environment.py`、`tests/fixtures/README.md`、`scripts/config_check.py`、`scripts/creator_pipeline.py`、`scripts/prepare_host_refinement.py`、`scripts/provider_adapters.py`、`scripts/run_creator_skill_build.py`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest --collect-only`；`.\.venv\Scripts\python.exe -m pytest -q`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`git diff --check`。
- 命令结果：收集 4 项测试；4 passed；Ruff 全通过；Mypy 检查 11 个脚本无问题；依赖无冲突；离线 self-test 通过；diff whitespace 检查通过（仅 Git 提示现有 LF/CRLF 转换策略）。
- 新增测试：4 项环境基线测试，覆盖运行/开发依赖入口、fixture 脱敏约束、临时 run 目录仓库外隔离、虚拟凭证和测试 endpoint。
- 剩余风险：TF-002 的供应商响应、恶意输入和跨领域 fixture 矩阵尚未建立；未调用真实 TikHub/ASR/OSS，符合本计划离线基线范围。
- 下一建议任务：TF-002 建立脱敏回归 fixture 矩阵。

### TF-002 / 2026-07-15

- 状态：completed
- 修改摘要：建立版本化 `manifest.json` 和四类脱敏 fixture 矩阵；覆盖 TikHub 6 类响应、ASR 4 类响应及 6 个转写边界、3 个非科技 corpus、4 类恶意输入；增加路径包含、数据语义、清单完整性、文件大小、无网络、禁止读取 `.env` 和 secret/signed URL 的自动化契约。
- 涉及文件：`tests/test_fixtures.py`、`tests/fixtures/README.md`、`tests/fixtures/manifest.json`、`tests/fixtures/tikhub/**`、`tests/fixtures/asr/**`、`tests/fixtures/corpora/**`、`tests/fixtures/security/**`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_fixtures.py -q`；`.\.venv\Scripts\python.exe -m pytest -q`；`git grep --no-index -n -E '(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)' -- tests`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`git diff --check`。
- 命令结果：TDD RED 阶段因 manifest 缺失得到 2 passed、8 errors；补齐矩阵后专项 10 passed；全量 14 passed；要求的 secret 模式无命中；Ruff、Mypy、pip check 和离线 self-test 全通过；diff whitespace 检查通过（仅 Git 的 LF/CRLF 策略提示）。
- 新增测试：8 项 fixture 契约测试，参数化后覆盖 10 个测试节点；验证 18 组 fixture 清单、23 个必需场景、清单/文件一一对应、跨领域 metadata/transcript 对齐，以及安全样本保持惰性。
- 剩余风险：本任务只建立固定输入和契约，尚未将每类 fixture 接入具体解析器与安全策略的行为测试；后续由 TF-003、TF-004、TF-006、TF-011、TF-013、TF-014、TF-019 等任务消费。
- 下一建议任务：TF-003 把离线自测提升为可断言的 pytest 集成测试。

### TF-003 / 2026-07-15

- 状态：completed
- 修改摘要：新增可复用的离线场景执行与断言模块，将原自测的输入、subprocess 编排、产物检查和 host-refinement 检查收敛为单一实现；`self_test.py` 改为薄 CLI；增加完整、部分转写、无转写、空 metadata、损坏 metadata 和精修后仍未 ready 的 pytest 集成场景。
- 涉及文件：`scripts/offline_scenarios.py`、`scripts/self_test.py`、`tests/integration/test_offline_pipeline.py`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m pytest tests\integration\test_offline_pipeline.py -q`；`.\.venv\Scripts\python.exe -m pytest -q`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git diff --check`。
- 命令结果：TDD RED 阶段因 `offline_scenarios` 尚不存在而在收集期失败；边界切片 3 passed、2 xfailed；最终专项 4 passed、2 xfailed；全量 18 passed、2 xfailed；用户入口 self-test、Ruff、Mypy（12 个脚本）和 pip check 全部通过。
- 新增测试：成功路径断言 workflow、quality、selected/compact/profile、11 类 run_summary 产物计数、3 个 JSON Schema draft URI、persona model 版本与 draft 状态；失败路径断言无转写、空 metadata、损坏 JSON 的质量、workflow、步骤状态与退出码。
- 剩余风险：严格 xfail 保留两个已确认缺口——质量门禁失败仍返回 0（TF-009）和 selected=2/transcribed=1 仍被判为完成（TF-010）；未在本任务越权修复。Checkpoint 0 的“所有已确认 bug 都有失败测试或 xfail”仍未完成，其他 bug 将由后续专项任务补齐。
- 下一建议任务：TF-004 校验 CLI 输入并生成不可碰撞 Run ID。

### TF-004 / 2026-07-15

- 状态：completed
- 修改摘要：建立统一 CLI/环境数值验证契约并接入 bootstrap、端到端 runner、select-samples 和 resume；明确 sample/fetch/concurrency/retry/timeout/segment 范围及 project slug 约束；Run ID 改为 UTC 毫秒时间戳加 UUID，目录使用 `exist_ok=False` 排他创建并在碰撞时有限重试。
- 涉及文件：`scripts/input_validation.py`、`scripts/build_creator_skill.py`、`scripts/run_creator_skill_build.py`、`scripts/creator_pipeline.py`、`scripts/resume_creator_run.py`、`tests/test_run_creation.py`、`tests/test_cli_validation.py`、`.env.example`、`references/config.example.env`、`references/configuration.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_run_creation.py tests\test_cli_validation.py -q`；`.\.venv\Scripts\python.exe -m pytest -q`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git diff --check`。
- 命令结果：TDD RED 得到 39 failed、5 passed，并复现 1000 次创建仅 5 个目录；最终专项 44 passed；全量 62 passed、2 个既有 strict xfail；self-test、Ruff、Mypy（13 个脚本）和 pip check 全通过。
- 新增测试：1000 次真实目录唯一性、Run ID 格式、模拟碰撞重试、持续碰撞拒绝覆盖、普通/中文 slug；两个主入口的非法 sample/fetch/project 校验、17 组无效运行配置、底层 select-samples 和中文 CLI 兼容性。
- 剩余风险：JSON 写入失败仍可能留下半成品 run，workflow 原子性和恢复由 TF-005 处理；质量失败退出码与部分转写门槛仍由 TF-009/TF-010 的 strict xfail 跟踪；配置最终单一事实来源由 TF-033/TF-034 收敛。
- 下一建议任务：TF-005 实现原子 JSON 写入和可恢复 workflow 状态。

### TF-005 / 2026-07-15

- 状态：completed
- 修改摘要：新增单一 `atomic_write_text()` / `atomic_write_json()`，通过同目录临时文件、flush/fsync、`os.replace` 和失败清理保证单文件崩溃安全；迁移 bootstrap、pipeline、provider、离线场景及 host-refinement 的所有关键 JSON/Schema 产物；workflow 新增版本与生命周期字段，按步骤状态推导 `final_status`，缺失、损坏、结构非法或持久化失败时不再静默返回，而是写 stderr、原子保留恢复诊断并抛出 `WorkflowStateError`。
- 涉及文件：`scripts/io_utils.py`、`scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`scripts/provider_adapters.py`、`scripts/offline_scenarios.py`、`scripts/prepare_host_refinement.py`、`tests/test_atomic_io.py`、`tests/test_workflow_state.py`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`..venvScriptspython.exe -m pytest tests\test_atomic_io.py tests\test_workflow_state.py -q --basetemp <独立临时目录>`；`..venvScriptspython.exe -m pytest -q --basetemp <独立临时目录>`；`..venvScriptspython.exe scripts\self_test.py`；`..venvScriptspython.exe -m ruff check .`；`..venvScriptspython.exe -m mypy scripts`；`..venvScriptspython.exe -m pip check`；`git grep --no-index -n -E "(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)" -- scripts tests`；`git diff --check`。
- 命令结果：TDD RED 在隔离临时目录下得到 9 failed；原子 I/O 分片 4 passed，workflow 分片 5 passed，最终专项 9 passed；全量 71 passed、2 个既有 strict xfail；离线 self-test、Ruff、Mypy（14 个脚本）、pip check 均通过；敏感模式无命中；diff whitespace 检查通过（仅 Git 的既有 LF/CRLF 策略提示）。因本机 pytest 默认临时根目录存在历史权限异常，本轮 pytest 使用唯一 `--basetemp` 隔离验证，该异常不属于项目代码失败。
- 新增测试：原子 replace 中断保留旧 JSON、临时文件清理、fsync 先于同目录 replace、UTF-8 JSON 格式、单一 JSON writer 架构约束；新 workflow 生命周期字段、运行中/完成/失败终态推导、合法旧状态字段升级、损坏与缺失 workflow 的 stderr/异常/恢复记录。
- 剩余风险：原子性保证覆盖单个文件，但多个产物之间尚未形成事务或 manifest 指纹，后续由 TF-008 处理；`final_status` 与进程退出码的完整一致性仍由 TF-009 收敛；TF-009/TF-010 对应的 2 个 strict xfail 保持不变；未调用真实 TikHub/ASR/OSS。
- 下一建议任务：TF-006 重写 ASR 响应解析，保留真实片段、重复话术和零时间戳语义。

### TF-006 / 2026-07-15

- 状态：completed
- 修改摘要：新增不可变 `TranscriptSegment` 规范模型及 compatible chat、compatible audio transcriptions、DashScope 三个显式 adapter；按供应商时间单位统一为毫秒，使用 `is not None` 语义保留零时间戳，并按有效开始时间与 `source_index` 稳定排序；删除任意 JSON 无边界递归、启发式时间单位和纯文本去重；对父/result 镜像路径只删除跨路径完全相同的片段，不删除不同时间的同文话术；文件转换使用原子文本写入，未知结构抛出带原始 JSON 路径的 `ASRParseError`，不会生成伪 transcript。
- 涉及文件：`scripts/asr_parsers.py`、`scripts/creator_pipeline.py`、`tests/test_asr_parsers.py`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`..venvScriptspython.exe -m pytest tests\test_asr_parsers.py -q --basetemp <独立临时目录>`；`..venvScriptspython.exe -m pytest -q --basetemp <独立临时目录>`；`..venvScriptspython.exe scripts\self_test.py`；`..venvScriptspython.exe -m ruff check .`；`..venvScriptspython.exe -m mypy scripts`；`..venvScriptspython.exe -m pip check`；`git grep --no-index -n -E "(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)" -- scripts tests`；`git diff --check`。
- 命令结果：初始 RED 因 `asr_parsers` 不存在在收集期失败；首个 adapter 分片得到 8 passed、1 failed，证明旧入口仍会递归误判未知结构；镜像精确去重回归先得到 1 failed、9 passed，修复后最终专项 10 passed；全量 81 passed、2 个既有 strict xfail；离线 self-test、Ruff、Mypy（15 个脚本）、pip check 均通过；敏感模式无命中；diff whitespace 检查通过（仅 Git 的既有 LF/CRLF 策略提示）。pytest 继续使用唯一 `--basetemp` 隔离本机默认临时根目录的历史权限异常。
- 新增测试：规范模型字段、三类 provider fixture 显式解析、秒到毫秒转换、`start=0` 渲染、3 段不翻倍、父/result 镜像精确去重、不同时间同文保留、乱序及无时间片段稳定排序、未知结构失败且 raw JSON 原文不变。
- 剩余风险：本任务不处理音频 chunk offset、边界重叠和全局时间线，这些由 TF-007 完成；显式 adapter 只支持已有脱敏 fixtures 证明的结构，未识别的新供应商变体会安全失败并保留 raw JSON，需在真实 smoke test 获授权后用脱敏样本扩展；TF-009/TF-010 对应的 2 个 strict xfail 保持不变。
- 下一建议任务：TF-007 修复音频分片合并和全局时间线。

### TF-007 / 2026-07-15

- 状态：completed
- 修改摘要：为长音频分片新增原子 chunk manifest，记录源音频 SHA-256、源时长、分片配置及每片实际 start/end/duration；只有 `complete` 且源哈希、配置、边界和文件完整性全部匹配的分片缓存可复用，ffmpeg 失败、无产物或 chunk 时长不可测时清除半片、写 `failed` manifest 并停止，不再退化为整文件 ASR；新增结构化 chunk transcript 合并，局部时间加实际 chunk offset，按全局时间稳定排序并验证非空比例与单调性；跨片去重只比较紧邻前一 chunk，且必须同时满足边界时间窗、最短文本长度和相似度阈值；最终正文原子写入，chunk/局部索引/全局时间写入独立 `.segments.json`，不把调试元数据混入 transcript。
- 涉及文件：`scripts/asr_parsers.py`、`scripts/run_creator_skill_build.py`、`tests/test_audio_chunking.py`、`tests/test_transcript_merge.py`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`..venvScriptspython.exe -m pytest tests\test_audio_chunking.py tests\test_transcript_merge.py -q --basetemp <独立临时目录>`；`..venvScriptspython.exe -m pytest -q --basetemp <独立临时目录>`；`..venvScriptspython.exe scripts\self_test.py`；`..venvScriptspython.exe -m ruff check .`；`..venvScriptspython.exe -m mypy scripts`；`..venvScriptspython.exe -m pip check`；`git grep --no-index -n -E "(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)" -- scripts tests`；`git diff --check`。
- 命令结果：初始 RED 因 `ChunkTranscript` 尚不存在在收集期失败；纯合并首分片得到 5 passed、1 failed，单独证明边界重叠尚未删除，加入双条件判断后 6 passed；旧磁盘分片路径稳定复现 4 failed，manifest/失败安全实现后 4 passed；runner 端到端测试先得到 4 passed、1 failed并复现第二片仍显示局部 `[00:00:05]`，结构化接入后最终专项 11 passed；全量 92 passed、2 个既有 strict xfail；离线 self-test、Ruff、Mypy（15 个脚本）、pip check 均通过；敏感模式无命中；diff whitespace 检查通过（仅 Git 的既有 LF/CRLF 策略提示）。pytest 继续使用唯一 `--basetemp` 隔离本机默认临时根目录的历史权限异常。
- 新增测试：实际分片边界/时长与源哈希 manifest、ffmpeg 失败清理及 failed 状态、不完整缓存拒绝复用、未知音频时长失败；第二片 5 秒映射到 125 秒、真正边界镜像去重、时间窗外合法重复保留、边界内不同文本保留、乱序输入全局单调、低非空比例拒绝；mock provider 端到端验证最终正文及无正文复制的独立来源映射。
- 剩余风险：本任务的 ffmpeg/ffprobe 与供应商调用均以脱敏 mock 验证，未获授权执行真实媒体 smoke test；边界窗 2 秒、相似度 0.92 和最短 4 字为保守默认值，真实样本出现系统性误判时应新增脱敏 fixture 后调整；当前只验证 chunk 级窄缓存，下载/音频/ASR/摘要的统一配置与内容指纹由 TF-008 完成；TF-009/TF-010 对应的 2 个 strict xfail 保持不变。
- 下一建议任务：TF-008 为下载、音频、ASR 和摘要增加产物指纹。

### TF-008 / 2026-07-15

- 状态：completed
- 修改摘要：新增统一 artifact manifest schema、稳定 canonical fingerprint、文件 SHA-256、安全 URL/endpoint 身份、敏感字段拒绝和 `verified`/`legacy_unverified`/完整性失败原因；下载按 URL 指纹、白名单响应元数据和文件哈希复用，音频按源视频哈希、ffmpeg 版本及编码参数复用，ASR 原始响应和 transcript 分层认证并纳入 provider、endpoint、model、语言、分片与 parser version，摘要按全部 transcript 哈希复用；host-refinement 的 corpus、signal、coverage 写入上游指纹，成品质量门禁不再信任缺少 sidecar 的 legacy signal/coverage。
- 涉及文件：`scripts/artifacts.py`、`scripts/asr_parsers.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`scripts/prepare_host_refinement.py`、`tests/test_artifact_manifest.py`、`tests/test_resume_cache.py`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_artifact_manifest.py tests\test_resume_cache.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\test_audio_chunking.py tests\test_transcript_merge.py tests\test_asr_parsers.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git grep --no-index -n -E "(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)" -- scripts tests`；`git diff --check`。
- 命令结果：TDD RED 阶段两份专项测试均因 `artifacts` 模块不存在而在收集期失败；公共契约首个 GREEN 分片 8 passed；下载、音频、ASR、摘要集成后最终专项 13 passed；TF-006/TF-007 相邻回归 21 passed；全量 105 passed、2 个按 TF-009/TF-010 保留的 strict xfail；离线 self-test、Ruff、Mypy（16 个脚本）、pip check 和 diff whitespace 检查全部通过；限定 `scripts tests` 的敏感模式扫描无命中。
- 新增测试：manifest 往返与记录完整性、稳定指纹、模型变更、分片参数变更、源音频变更、产物篡改、空文件、截断 sidecar、legacy 无 sidecar、API key/Authorization/签名字段拒绝；下载 legacy 替换及安全响应元数据；音频源视频哈希失效；摘要全量 transcript 哈希失效；兼容 ASR 重复运行的 verified 复用。
- 剩余风险：未获授权调用真实 TikHub、ASR、OSS 或真实 ffmpeg 媒体 smoke，本任务以脱敏 mock 和离线流程验证；manifest schema 当前为 v1，旧 run 明确返回 `legacy_unverified` 且不会自动通过相关质量门禁，不做静默迁移；TF-009/TF-010 对应的退出码与阶段覆盖率 2 个 strict xfail 保持不变。
- 下一建议任务：TF-009 统一步骤结果、最终状态和退出码。

### TF-009 / 2026-07-15

- 状态：completed
- 修改摘要：新增不可矛盾的 `StepResult` / `PipelineResult` 公共契约，统一 `succeeded/partial/failed/skipped` 终态、输入/成功/失败/跳过计数、问题、输出路径、耗时、质量结论和退出码；为下载、音频、ASR、研究摘要、构建和质量检查增加结构化 step wrapper；主 runner 与 resume 均原子写入 `logs/pipeline_result.json`，基础质量失败、关键步骤 partial/failed 或缺少质量结论时返回非零，异常路径先写 workflow failed 和 pipeline error 再重新抛出；workflow 步骤把旧 `completed` 兼容别名规范为 `succeeded`，顶层 `status=completed` 保持兼容，`final_status` 与 PipelineResult 精确一致；Creator quality-check 和 research quality-check 默认严格退出，只有显式 `--report-only` 可在 `passed=false` 时返回 0。
- 涉及文件：`scripts/pipeline_models.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`scripts/resume_creator_run.py`、`scripts/research/quality_check.py`、`scripts/offline_scenarios.py`、`tests/test_step_results.py`、`tests/test_pipeline_exit_codes.py`、`tests/test_workflow_state.py`、`tests/integration/test_offline_pipeline.py`、`SKILL.md`、`references/pipeline.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_pipeline_exit_codes.py tests\test_step_results.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\integration\test_offline_pipeline.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git grep --no-index -n -E "(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)" -- scripts tests`；`git diff --check`。
- 命令结果：TDD RED 阶段因 `pipeline_models` 尚不存在在收集期失败；纯模型首个 GREEN 分片 4 passed；成功 runner、失败 draft 和异常持久化分片分别通过；workflow/专项阶段 15 passed，离线集成 5 passed、1 个 TF-010 strict xfail；最终 PLAN 专项 12 passed；全量 118 passed、1 个 TF-010 strict xfail；离线 self-test、Ruff、Mypy（17 个脚本）、pip check、敏感模式扫描和 diff whitespace 检查全部通过。
- 新增测试：StepResult 四类终态和计数自洽、verified cache 成功语义、PipelineResult 状态/退出码绑定、partial 非零、缺少质量结论失败关闭、六类 step wrapper 结构化返回；成功 runner 的 0/succeeded 一致性，空 metadata、无 transcript 的非零/failed 一致性，损坏 metadata 异常前持久化；Creator 与 research quality-check 的默认严格和显式 report-only JSON 语义。
- 剩余风险：TF-010 的阶段覆盖率仍未实现，因此 `selected=2/transcribed=1` 的现有 strict xfail 保留；本任务不定义样本覆盖率门槛，也不将离线 transcript 数与 selected 数做阶段比率比较；未调用真实 TikHub、ASR、OSS，符合本任务完全离线的结果语义验证范围；工作区已有变更仍未提交，用户未授权 commit/push。
- 下一建议任务：TF-010 建立阶段覆盖率和部分失败门槛。

### TF-010 / 2026-07-15

- 状态：completed
- 修改摘要：新增版本化 `stage_coverage` 契约，按 selected 视频逐项计算 selected/downloaded/audio/transcribed 的真实产物数量、比率、draft/ready 所需数量、阶段状态、来源与结构化问题码；在线 `online_media` 要求四阶段，`--transcripts-dir` 显式记录为 `offline_transcripts` 并仅要求 selected/transcribed；默认 draft 使用 2 条且 80%、ready 使用 5 条且 95%，实际门槛取绝对数量和比例数量的较大者并以 selected 为上限；阈值支持受范围和顺序校验的环境配置。质量报告和 run summary 纳入覆盖率，`passed` 依赖 draft，`ready_for_use` 同时依赖 ready；部分离线转写的 transcribe/normalize 步骤改为 `partial`，最终质量、workflow、PipelineResult 和退出码均为失败。
- 涉及文件：`scripts/stage_coverage.py`、`scripts/input_validation.py`、`scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`tests/test_stage_coverage.py`、`tests/test_cli_validation.py`、`tests/integration/test_offline_pipeline.py`、`.env.example`、`references/config.example.env`、`references/configuration.md`、`references/pipeline.md`、`SKILL.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`..venvScriptspython.exe -m pytest tests	est_stage_coverage.py -q --basetemp <独立临时目录>`；`..venvScriptspython.exe -m pytest tests	est_stage_coverage.py tests	est_cli_validation.py tests	est_pipeline_exit_codes.py tests	est_step_results.py testsintegration	est_offline_pipeline.py -q --basetemp <独立临时目录>`；`..venvScriptspython.exe -m pytest -q --basetemp <独立临时目录>`；`..venvScriptspython.exe scriptsself_test.py`；`..venvScriptspython.exe -m ruff check .`；`..venvScriptspython.exe -m mypy scripts`；`..venvScriptspython.exe -m pip check`；`git grep --no-index -n -E "(sk-[A-Za-z0-9_-]{16,}|BEGIN .* PRIVATE KEY)" -- scripts tests`；`git diff --check`。
- 命令结果：TDD RED 阶段因阈值校验入口尚不存在而在收集期失败；覆盖率专项最终 7 passed；配置、退出码、步骤结果和离线集成相邻回归 71 passed；原 TF-010 strict xfail 已删除并转为真实通过；全量 133 passed、无 xfail；离线 self-test、Ruff、Mypy（18 个脚本）、pip check、敏感模式扫描和 diff whitespace 检查全部通过。
- 新增测试：selected=50/transcribed=1 要求 40 条并失败；小样本绝对数量门槛；合法离线模式豁免 download/audio；在线缺 URL、下载失败、音频失败、ASR 跳过的稳定问题码和逐视频原因；真实失败日志优先于残留文件；阈值范围、ready≥draft 顺序和创建目录前失败；质量报告/run summary 接入；运行目录显式模式；部分转写返回非零且 workflow failed。
- 剩余风险：未获授权调用真实 TikHub、ASR、OSS 或真实 ffmpeg 媒体 smoke，本任务以脱敏状态日志、人工小产物和离线端到端场景验证；缺少 `execution_mode` 的旧 run 保守按在线模式处理，完整 legacy 诊断与迁移由 TF-038 完成；网络与媒体安全边界仍由 TF-011/TF-012 处理；工作区已有变更未提交，用户未授权 commit/push。
- 下一建议任务：TF-011 实现统一网络访问策略并阻断 SSRF。

### TF-011 / 2026-07-15

- 状态：completed
- 修改摘要：新增统一 `network_policy`，将外部地址按抖音来源、非受信远程资源和受信 provider endpoint 三类处理；仅允许 HTTP/HTTPS，拒绝嵌入凭证、本机名、全部非公网 DNS 结果以及十进制/十六进制/缩写形式的混淆回环地址；抖音来源使用后缀安全的显式 allowlist。urllib 请求关闭系统代理并把 TCP/TLS 连接固定到已验证 IP，同时保留原始 Host、TLS SNI 和证书主机名校验，消除校验后再次解析造成的 DNS rebinding 窗口；每跳重定向重新验证。带凭证的 provider 请求关闭并拒绝重定向，避免 Authorization 被重放；错误只暴露协议、主机和非默认端口，不回显路径、查询串或凭证。策略已接入创作者链接解析、TikHub、媒体下载、DashScope/compatible ASR、转写结果下载和 OSS endpoint，安全策略失败不重试。
- 涉及文件：`scripts/network_policy.py`、`scripts/creator_pipeline.py`、`scripts/provider_adapters.py`、`tests/security/test_url_policy.py`、`tests/test_resume_cache.py`、`references/configuration.md`、`references/pipeline.md`、`SKILL.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\security\test_url_policy.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；网络旁路模式扫描；敏感凭证模式扫描；`git diff --check`。
- 命令结果：TDD RED 阶段因 `network_policy` 尚不存在而在收集期失败；纯策略首轮 17 passed、3 failed，3 个失败准确暴露下载、provider 与来源入口尚未接入；接入后 20 passed，补齐 adapter、混淆地址、逐跳重定向和连接固定测试后最终专项 31 passed；受影响测试 50 passed；全量 164 passed、无 xfail；离线 self-test、Ruff、Mypy（19 个脚本）、pip check、网络旁路与敏感模式扫描全部通过；diff whitespace 检查通过（仅 Git 的既有 LF/CRLF 策略提示）。
- 新增测试：localhost、IPv4/IPv6 回环、RFC1918、link-local metadata、IPv6 ULA、非 HTTP 协议和三类混淆回环地址；抖音域名 allowlist 与攻击者后缀；所有 DNS 结果必须为公网、解析失败关闭；公网短链、相对重定向和公网转私网；provider 用户信息、重定向凭证防重放与错误脱敏；下载、JSON、compatible ASR 在网络调用前拒绝私网；HTTP 连接只使用已验证 IP，HTTPS 连接固定 IP 但保留原主机名 TLS 校验。
- 剩余风险：未获授权调用真实 TikHub、ASR、OSS 或真实公网 DNS/重定向 smoke，本任务全部使用脱敏 fixture、假 resolver 和 mock transport；第三方 SDK 及 `requests` 仅用于受信配置 endpoint，已做 URL/DNS 校验并禁止带凭证重定向，但其内部传输未像非受信 urllib 下载一样做 IP 固定；下载大小、MIME、媒体探测和资源耗尽保护由 TF-012 完成；工作区已有变更未提交，用户未授权 commit/push。
- 下一建议任务：TF-012 限制下载资源并验证媒体文件。

### TF-012 / 2026-07-15

- 状态：completed
- 修改摘要：新增下载资源门禁和独立媒体验证模块。下载默认限制单文件 512 MiB、响应头等待 30 秒、跨全部重试与退避的总 deadline 300 秒、ffprobe 30 秒，四项均进入统一配置校验和 artifact 指纹；deadline 不得短于响应头超时。响应体读取前要求完整 HTTP 200、允许的 video/octet-stream Content-Type 以及合法且不超限的 Content-Length；无长度头仍按 1 MiB 分块累计，读取前后检查 deadline，并把底层 socket 的下一次读取超时收敛到剩余时间。字节超限、长度不符、超时、网络错误或媒体验证失败均删除 `.part`，成功路径 flush/fsync 后先验证再原子替换。媒体验证先有界嗅探并拒绝 HTML/XML/JSON，再以禁用网络协议、限制 probe/analyze 预算和执行超时的 ffprobe 要求正时长视频流、有效尺寸；manifest 记录 SHA-256、大小、格式、时长、音视频流数、编码和分辨率。相同 video ID/URL 在单批次合并为一次下载并复用已验证结果，同 ID 不同 URL 在请求前整组失败；目标路径另有进程内锁防止直接并发调用覆盖。
- 涉及文件：`scripts/media_validation.py`、`scripts/creator_pipeline.py`、`scripts/input_validation.py`、`scripts/build_creator_skill.py`、`tests/security/test_download_limits.py`、`tests/test_media_validation.py`、`tests/test_cli_validation.py`、`tests/test_resume_cache.py`、`.env.example`、`references/config.example.env`、`references/configuration.md`、`references/pipeline.md`、`SKILL.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\security\test_download_limits.py tests\test_media_validation.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\security\test_download_limits.py tests\test_media_validation.py tests\security\test_url_policy.py tests\test_resume_cache.py tests\test_cli_validation.py tests\test_artifact_manifest.py tests\test_step_results.py tests\test_stage_coverage.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；本地 ffmpeg 生成 MP4 后调用真实 ffprobe；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；网络旁路/无界复制扫描；敏感凭证模式扫描；`git diff --check`。
- 命令结果：初始 RED 因 `media_validation` 不存在产生 2 个收集错误；加入媒体验证后 9 passed，下载边界保持 12 failed，准确暴露未接入的大小、状态、MIME、deadline 和重复 ID 问题；核心接入后专项 21 passed。配置/缓存 RED 为 49 passed、10 failed，统一配置和缓存适配后 59 passed；最终受影响回归 133 passed；全量 194 passed、无 xfail。真实本地烟测由 ffmpeg 生成 1 秒 MP4，实际 ffprobe 成功识别 `mov,mp4...`、1000 ms、mpeg4、160×120。离线 self-test、Ruff、Mypy（20 个脚本）、pip check、网络旁路/无界复制扫描、敏感模式扫描和 diff whitespace 检查均通过（仅 Git 的既有 LF/CRLF 策略提示）。
- 新增测试：声明长度预超限时不读取正文且清理旧 `.part`；无 Content-Length 的流式超限；206、HTML、JSON、缺失 MIME、非法长度和实际长度不符；下载 deadline；有效媒体原子发布、哈希和媒体元数据；ffprobe 失败不重试且不发布；相同 ID 单次下载及冲突 URL 请求前失败；HTML/JSON 内容嗅探、ffprobe 失败/非法 JSON/无视频流/零时长/超时；四项配置范围及 deadline/header 顺序。
- 剩余风险：未调用真实 TikHub、ASR、OSS 或公网媒体 URL，本任务的网络响应使用脱敏 fake transport，但本地 ffmpeg/ffprobe 真实媒体链路已验证；默认 512 MiB/30 秒/300 秒应结合生产样本与磁盘配额观察，特殊 CDN 若返回未列入的 MIME 会安全失败；同一批次去重和进程内目标锁已覆盖线程并发，不同进程同时恢复同一 run 的互斥尚未提供跨进程锁，正常唯一 run 目录不受影响；video ID 的路径规范化与碰撞语义由 TF-013 完成；工作区已有改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-013 规范 video ID 并保证路径包含关系。

### TF-013 / 2026-07-15

- 状态：completed
- 修改摘要：新增跨平台 `path_policy` 单一契约，严格区分原样保留、用于 evidence 的 `platform_video_id` 与只用于本地文件的 `artifact_id`；本地 ID 采用 NFKC/casefold、受限小写 ASCII 字符集、120 字符上限和稳定 SHA-256 冲突后缀。平台 ID 在任何网络或文件操作前拒绝路径穿越、绝对/盘符/UNC/设备路径、分隔符、控制字符、Windows 保留名及危险尾缀；`resolve_within` 同时检查跨平台绝对路径、父级穿越和解析后的符号链接逃逸。归一化和选择分别生成版本化 `video_id_map.json` / `selected.video_id_map.json`，corpus index 保留结构化双 ID 映射。下载、视频/音频、ASR 原始响应、分片缓存、转写、阶段覆盖和 host refinement 全部改用 `artifact_id` 派生路径，并验证根目录包含关系；被篡改的分片 manifest 外部路径和 selected ID 显式失败。合法抖音数字 ID、测试短 ID和 legacy ID 有确定性映射；旧转写可在 selected 映射下导入并改名，不安全旧文件名不会被下游静默信任。
- 涉及文件：`scripts/path_policy.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`scripts/resume_creator_run.py`、`scripts/stage_coverage.py`、`scripts/prepare_host_refinement.py`、`tests/security/test_path_containment.py`、`tests/test_video_ids.py`、`tests/test_audio_chunking.py`、`SKILL.md`、`references/pipeline.md`、`references/configuration.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\security\test_path_containment.py tests\test_video_ids.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；ID 派生路径静态扫描；敏感凭证模式扫描；`git diff --check`。
- 命令结果：初始 RED 因 `path_policy` 不存在产生 2 个收集错误；纯策略与包含关系首个 GREEN 分片 33 passed。接入元数据、下载、映射、离线转写、host corpus 和阶段覆盖后 PLAN 专项先稳定为 39 passed；传播审计新增的非法音频名、路径型音频格式、ASR 分片路径和篡改 manifest 4 项均先准确失败，收口后相邻专项 48 passed。最终 PLAN 指定专项 44 passed；全量 238 passed、无 xfail；离线 self-test、Ruff、Mypy（21 个脚本）和虚拟环境内 pip check 全部通过；路径派生与敏感模式扫描无未解释命中，diff whitespace 检查通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：抖音数字/短/legacy/Unicode ID 映射；归一化碰撞、重复 ID、长 ID、选择子集稳定性；`..`、POSIX/Windows 绝对路径、盘符相对路径、UNC/设备路径、保留名、全角分隔符、控制字符和符号链接逃逸；恶意 ID 在元数据落盘、网络下载和 ffmpeg 前失败；外部 transcript 按双 ID 映射；evidence 保留平台 ID 而本地读取 artifact 文件；阶段覆盖检测篡改 ID；ASR 分片缓存拒绝 manifest 指向根目录外文件。
- 剩余风险：本任务完全使用脱敏 fixture、mock transport 和离线流程，未调用真实 TikHub、ASR 或 OSS；`resolve_within` 能拒绝检查时已存在的符号链接逃逸，但不提供对恶意本机进程在“校验后、打开前”交换路径的内核级 `openat/O_NOFOLLOW` 防护，当前威胁边界仍假定运行目录不由并发恶意本地用户控制；没有映射文件且文件名不合规的旧 run 需要显式重新导入或由 TF-038 诊断，不做静默迁移；工作区已有改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-014 隔离 transcript 提示注入和 Markdown 控制内容。

### TF-014 / 2026-07-15

- 状态：completed
- 修改摘要：为“外部标题/ASR 转写/用户导入材料/网页与 JSON 字段 → 宿主 Agent Markdown”建立显式不可信语料边界。`brief.md` 在任何 creator/profile/title/transcript 数据之前固定输出 `Security: Untrusted Corpus Protocol`，禁止执行语料命令或工具调用、读取/泄露 `.env` 与本地配置、访问语料 URL、修改计划/工作流/权限/质量结论，并建议在无供应商凭证、最小工具权限上下文研究。新增统一 `markdown_data_inline`，将换行、表格、标题、链接、代码围栏、HTML 和 URL 控制字符转换为非活动数据实体；新增 `render_untrusted_markdown_block`，将保留段落结构的 transcript excerpt 放入可见 `BEGIN/END UNTRUSTED DATA` 缩进代码块。编码已覆盖 brief 的 creator/profile/标题/ID、evidence coverage、coverage gaps、short-form、timeline、ASR entity、transcript signals 和 signal matrix 等 Markdown 表面；代表性转写不再进入动态标题。主 `SKILL.md`、host refinement 说明和四份 celebrity 研究提示词均加入同一最小权限协议。
- 涉及文件：`scripts/prepare_host_refinement.py`、`tests/security/test_prompt_injection_isolation.py`、`SKILL.md`、`references/host_refinement.md`、`references/pipeline.md`、`references/prompts/celebrity/research.md`、`references/prompts/celebrity/persona_analyzer.md`、`references/prompts/celebrity/persona_builder.md`、`references/prompts/celebrity/merger.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\security\test_prompt_injection_isolation.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\security\test_prompt_injection_isolation.py tests\test_video_ids.py tests\test_artifact_manifest.py tests\test_fixtures.py tests\integration\test_offline_pipeline.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；动态 Markdown 旧式直插值扫描；六份宿主说明最小权限覆盖扫描；敏感凭证模式扫描；`git diff --check`。
- 命令结果：初始 RED 为 10 failed，分别证明统一编码器/数据容器不存在、brief 没有前置安全协议、恶意 profile 能创建真实 Markdown 标题、标题能插入表格列和 file 链接、研究说明缺少最小权限规则；核心接入后 10 passed，扩展真实多行标题、编号工具步骤和端到端 `.env` 访问守卫后最终专项 12 passed。host refinement/双 ID/artifact/fixture/离线集成相邻回归 50 passed；最终全量 250 passed、无 xfail；离线 self-test、Ruff、Mypy（21 个脚本）和虚拟环境 pip check 全部通过；六份研究说明均命中最小权限协议，旧式 `replace('|')`/换行直插值与敏感凭证模式无命中，diff whitespace 检查通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：六类 inline Markdown/HTML/URL 控制输入；围栏闭合、顶层标题和编号步骤只能留在缩进数据块；brief 安全协议必须早于任何语料；恶意 creator profile、视频标题、表格列、file/HTTP 链接和 transcript 不得生成活动结构；所有 host Markdown 报告保持结构完整；六份宿主研究说明必须声明 `.env`、URL、工具和最小权限边界；完整 `prepare_host_refinement.main()` 在恶意语料要求读取 `.env` 时由读取守卫证明未访问，并确认 secret sentinel 未进入任何生成文档。
- 剩余风险：提示注入无法只靠文字提示获得绝对安全，最终强制边界仍依赖宿主运行时实际提供最小工具权限；本任务已经在代码层消除 Markdown 结构控制，并在协议层禁止语料授权，但结构化 JSON 字符串仍会保留原始语料供分析，任何绕过 brief 直接读取 JSON 的 Agent 仍必须遵守主 `SKILL.md` 和研究提示词协议；未使用真实供应商或公网材料，全部验证基于人工恶意 fixture 和离线端到端流程；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-015 加强配置脱敏和最小化研究数据。

### TF-015 / 2026-07-15

- 状态：completed
- 修改摘要：新增统一 `scripts/redaction.py`，非空 secret 一律全量替换为固定 `<redacted>`，不再保留原值长度、首尾或任何可关联片段。配置快照除按字段名识别 API/app/private/access key、token、secret、password、Authorization、credential、signature、cookie、session 外，还会清理非 secret 配置值中嵌入的已配置凭证；HTTP(S) URL 统一删除 userinfo、fragment 及 token/key/signature/credential/auth/sig/policy 等敏感 query，同时保留普通 query。统一 scrubber 已接入 urllib/compatible ASR 供应商错误、`StepResult`/`PipelineResult`、workflow note 与恢复诊断、下载/音频/ASR 状态日志、音频分块失败 manifest，以及主运行和恢复入口的终端错误；异常类型标签保留，但原始异常链不再把 secret 重新打印。`selected.json` 继续作为内部下载与追溯数据保留 `download_url`，宿主读取的 `selected.compact.json` 删除该字段，改用 `download_available` 布尔值，并清理 `source_url` 的 userinfo、敏感 query 和 fragment。配置与流水线文档已同步固定占位符和 compact 最小化契约。
- 涉及文件：`scripts/redaction.py`、`scripts/build_creator_skill.py`、`scripts/provider_adapters.py`、`scripts/pipeline_models.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`scripts/resume_creator_run.py`、`tests/security/test_redaction.py`、`tests/test_compact_metadata.py`、`SKILL.md`、`references/configuration.md`、`references/pipeline.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\security\test_redaction.py tests\test_compact_metadata.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\test_run_creation.py tests\test_workflow_state.py tests\test_step_results.py tests\test_audio_chunking.py tests\test_pipeline_exit_codes.py tests\test_video_ids.py tests\test_resume_cache.py tests\test_artifact_manifest.py tests\test_stage_coverage.py tests\security\test_url_policy.py tests\security\test_prompt_injection_isolation.py tests\integration\test_offline_pipeline.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；旧式部分脱敏、高置信凭证形态、compact 字段和 scrubber 接入静态扫描；`git diff --check`。
- 命令结果：初始 RED 为 9 failed，分别证明配置快照仍暴露 secret 首尾、统一 redaction 模块不存在、userinfo/签名 query/Authorization/Bearer/本机路径未清理、供应商错误回显进入异常、workflow/pipeline/recovery 持久化泄露，以及 compact metadata 仍携带下载 URL。配置/URL/文本第一增量 3 passed，供应商与 workflow 第二增量 6 passed，基础专项 9 passed；扩展 `auth`/`sig`/`policy`/credential 别名和完整 runner 供应商失败场景后最终专项 11 passed。相邻回归首次为 108 passed、1 failed，定位为安全终端错误缺少 `JSONDecodeError` 类型标签；保留脱敏后的异常类型后目标回归 7 passed，最终相邻回归 109 passed。最终全量 261 passed、无 xfail；离线 self-test、Ruff、Mypy（22 个脚本）和 pip check 全部通过；旧首尾脱敏模式与生产/文档高置信凭证形态扫描无命中，compact 只输出 `download_available`，diff whitespace 检查通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：运行目录真实 `config.snapshot.json` 中 secret 固定占位且 endpoint/extra query 被清理；独立 URL 清除 userinfo、fragment、常见 token/签名别名但保留普通 query；文本 scrubber 清理 Authorization/Bearer、已配置 token、签名 URL 和 Windows/POSIX 本机路径；compatible ASR 401 响应回显凭证时异常不可恢复；workflow note、恢复诊断、`StepResult` 和 `pipeline_result.json` 不含供应商 token；完整 runner 在 TikHub 失败回显 token 时，终端、workflow 和全部 run 文件均无该 token；compact 单元和 `select_samples` 集成测试证明下载 URL 只留在内部 `selected.json`，宿主 compact 仅含可用性布尔值和清理后的来源 URL。
- 剩余风险：任意无标签、未出现在当前进程已配置 secret 集合中的随机敏感字符串无法由通用 scrubber 可靠识别，新增供应商若使用新字段名必须先补脱敏 fixture；本任务不会回写历史 run，旧 `config.snapshot.json`/日志/compact 需要由后续 TF-038 诊断或显式迁移；内部 `metadata/selected.json` 和供应商原始响应仍按媒体下载与追溯需要保留签名 URL，因此宿主研究必须继续只读取 `selected.compact.json`，并依赖 TF-017 的保留策略和 TF-016 的 OSS 生命周期进一步缩短暴露窗口；未调用真实 TikHub、ASR 或 OSS，全部验证使用人工凭证、mock provider 和离线流程；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-016 实现 OSS 对象隔离、生命周期和清理策略。

### TF-016 / 2026-07-15

- 状态：completed
- 修改摘要：新增独立 `oss_lifecycle` 契约，OSS object key 固定包含受限 project/run/video/chunk 段、源文件 SHA-256 和安全扩展名，跨 run 的同名同内容音频不再覆盖；删除入口同时校验受管 prefix、固定对象布局和 manifest bucket，拒绝任意 key 与错 bucket 删除。上传返回的签名 URL 只存在于 `repr=False` 的进程内 handle，runner 直接传给 ASR，生命周期清单、ASR 状态和 artifact manifest 只持久化对象身份、哈希与清理状态；DashScope 任务/结果若回显输入 URL 也会在落盘前脱敏。默认 `delete_after_asr` 在转写稿成功落盘后立即删除，ASR 失败按 60 秒至 30 天的有界窗口记录 `pending_expiry`；显式 `retain` 记录为 `retained`。新增 `oss-cleanup` sweep 删除已到期失败对象，并重试 `cleanup_failed`；删除异常全量脱敏后写入 `OSS_CLEANUP_FAILED` 并传播为 workflow issue，历史 issue 保留审计。生命周期、prefix、签名有效期和失败保留窗口均在创建 run 前校验，配置检查和中英文运维文档同步成本、隐私、最小权限与定时清理要求。
- 涉及文件：`scripts/oss_lifecycle.py`、`scripts/provider_adapters.py`、`scripts/run_creator_skill_build.py`、`scripts/pipeline_models.py`、`scripts/redaction.py`、`scripts/input_validation.py`、`scripts/build_creator_skill.py`、`scripts/config_check.py`、`tests/test_oss_lifecycle.py`、`tests/test_cli_validation.py`、`.env.example`、`references/config.example.env`、`references/configuration.md`、`references/pipeline.md`、`SKILL.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_oss_lifecycle.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\test_oss_lifecycle.py tests\test_cli_validation.py tests\test_step_results.py tests\security\test_redaction.py tests\test_audio_chunking.py tests\test_resume_cache.py tests\test_workflow_state.py tests\test_run_creation.py tests\test_artifact_manifest.py tests\test_pipeline_exit_codes.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`provider_adapters.py oss-cleanup --help`；旧文件名对象键与签名 URL 持久化点扫描；`git diff --check`。
- 命令结果：初始专项 RED 为 8 failed，证明生命周期模块、runner 清理状态和失败保留均不存在；对象键首个切片 1 passed，核心生命周期接入后 5 passed，runner 与 workflow issue 接入后 8 passed。配置边界新增 RED 7 failed，接入前置校验后 7 passed；到期 sweep 和清理失败重试分别先准确 RED，再最终形成 11 passed 的 OSS 专项。受影响回归 120 passed；最终全量 279 passed、无 xfail。离线 self-test、Ruff、Mypy（23 个脚本）、虚拟环境 pip check、清理 CLI help、旧文件名对象键/签名 URL 静态扫描和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：跨 run 同名音频对象键隔离与源哈希；manifest 不含签名 URL/AccessKey/Signature；成功立即删除、失败有界 `pending_expiry`、显式保留；到期前不删、到期 sweep 删除；任意 prefix 删除拒绝；删除失败脱敏、manifest issue、StepResult/workflow 传播及后续重试；完整 runner 成功上传/签名/转写/删除且全 run 无签名 URL；provider 失败在重新抛出前记录待清理；签名时长、失败保留窗口、策略和 prefix 在 run 创建前拒绝非法配置。
- 剩余风险：未获授权调用真实 OSS 或真实 DashScope，验证全部使用人工凭证和 mock OSS SDK；OSS SDK 的内部连接仍不像项目 urllib 下载链路那样固定到预验证 IP，此项继承 TF-011 已记录边界；`pending_expiry` 与 `cleanup_failed` 的最终删除依赖部署方按文档调度 `oss-cleanup`，应用未内置常驻调度器；manifest 使用进程内锁和原子替换，不提供多个进程同时维护同一 run 的跨进程互斥；`retain` 对象不会被 sweep，必须由有授权的责任人按独立保留制度显式删除；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-017 增加 rights basis、来源溯源和保留策略。

### TF-017 / 2026-07-15

- 状态：completed
- 修改摘要：新增统一 `provenance` 运行治理契约，每个新 run 都枚举记录 `unspecified`、`public_research`、`creator_authorized` 或 `team_owned`，并在 `input.json`、`metadata/provenance.json`、`skill/references/meta.json` 和最终 `skill/SKILL.md` 之间交叉核验来源平台、脱敏来源 URL、带时区采集时间、授权引用、保留策略、退出/下架联系和使用边界。明确产品门禁：`unspecified` 仅允许 draft；`public_research` 可在治理与内容完整时成为限定用途成品但不得商业交付；只有带联系渠道的 `team_owned` 或同时带授权引用和联系渠道的 `creator_authorized` 才可能得到 `commercial_delivery_ready=true`。授权文件只验证安全相对路径存在，run 只保存引用且不读取/复制私密正文。新增 dry-run-first 本地保留工具，支持 `retain_media`、`transcripts_only` 和 `final_skill_only`，输出确定性相对删除清单、字节数和 inventory digest；显式 `--apply` 前重验 run、provenance、已记录策略和清单新鲜度，限制删除范围并写 `logs/retention.json`。主运行、恢复和 quality CLI 显示商业交付状态，中英文流程、配置、宿主精修、Skill 和 README 边界已同步。
- 涉及文件：`scripts/provenance.py`、`scripts/retention.py`、`scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`scripts/resume_creator_run.py`、`tests/test_provenance.py`、`tests/test_retention_policy.py`、`README.md`、`SKILL.md`、`references/pipeline.md`、`references/configuration.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_provenance.py tests\test_retention_policy.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <run/workflow/security/offline/provenance/retention 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\retention.py --help`；`git diff --check`。
- 命令结果：provenance 初始 RED 为 12 failed，retention 初始 RED 为 7 failed；追加的最终 Skill 边界缺失和 input/manifest 保留策略篡改审计各自先准确失败。最终 PLAN 专项 22 passed；受影响回归 211 passed；全量 301 passed、无 xfail。离线 self-test、Ruff、Mypy（25 个脚本）、虚拟环境 pip check、retention CLI help 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：默认 run 的可枚举未声明权利；授权引用安全 ID/相对路径与私密正文零复制；非法权利/保留值、路径穿越、绝对路径和多行联系信息在 run 创建前失败；四类权利依据的 ready/商业门禁；input、provenance、meta 和最终 Skill 篡改降级；公开 CLI 参数持久化；三种保留策略精确白名单；默认 dry-run 零副作用；显式应用、审计回执与幂等；非 run、策略不一致、清单 stale 和 provenance 篡改拒绝。
- 剩余风险：代码只验证声明格式、引用存在性和跨产物一致性，不验证授权引用的真实性、授权范围或法律效力，商业交付前仍需有权限的人员独立审核；本地清理是文件级删除，不保证底层磁盘安全擦除、备份/云同步副本或取证不可恢复；`authorization_note_path` 按启动命令的当前工作目录解析，部署包装层应固定工作目录或提供统一引用登记；真实 TikHub/ASR/OSS 和真实授权材料均未使用，全部验证为脱敏 fixture、人工 sentinel 和离线/mock 流程；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-018 在质量检查时重算或验证派生产物新鲜度。

### TF-018 / 2026-07-15

- 状态：completed
- 修改摘要：新增 `scripts/quality_engine.py` 作为只读当前状态与 freshness 引擎，统一构造 prepare 与 quality-check 共用的 corpus、signal matrix、transcript signals、coverage JSON/Markdown manifest 契约，避免生产端与校验端算法版本/producer 配置漂移。每次 quality-check 都基于当前 `selected.compact.json`、规范化 transcript 和 evidence index 重算内存中的 corpus/signals/coverage，并用当前输入重建期望 manifest；持久化报告未被篡改但输入已变化时也会明确标记 `fingerprint_mismatch` 或 `upstream_stale`。质量报告新增脱敏最小化的 `computed_from`（相对路径、角色、大小、SHA-256）与 `freshness`（当前计数/覆盖、逐产物状态、stale 列表、固定修复命令），不会把标题、转写片段或本机绝对路径复制进日志。evidence 修改可立即看到当前覆盖数，旧 coverage 仍保持只读并被判 stale；transcript 修改会级联失效 corpus、signal matrix、signals 和 coverage。persona diagnostics 拆成无写入计算入口与原子落盘包装，每次质量检查按当前 persona model/evidence/Markdown 实时重算并记录输入哈希。最终 `ready_for_use` 和 `commercial_delivery_ready` 增加独立、不可由其他门禁绕过的 `freshness.fresh` 条件；draft `passed` 语义保持不变。文本质量输出增加 `FRESHNESS`、`STALE_ARTIFACTS` 和唯一 `REPAIR` 命令，中英文流水线、配置、宿主精修和 Skill 文档同步为“按输出修复”，无需用户记忆额外 prepare 步骤。
- 涉及文件：`scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`scripts/prepare_host_refinement.py`、`tests/quality/test_freshness.py`、`tests/test_provenance.py`、`SKILL.md`、`references/pipeline.md`、`references/configuration.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\quality\test_freshness.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\test_artifact_manifest.py tests\integration\test_offline_pipeline.py tests\test_provenance.py tests\test_stage_coverage.py tests\test_step_results.py tests\test_pipeline_exit_codes.py tests\security\test_prompt_injection_isolation.py tests\test_video_ids.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git diff --check`。
- 命令结果：初始专项 RED 因 `quality_engine` 不存在产生 1 个收集错误；只读 corpus/signals/coverage 入口首个切片 1 passed。随后 persona diagnostics 无写入入口、文本修复提示、最终 ready 独立门禁和质量日志语料最小化分别先准确 RED（缺函数、缺 `FRESHNESS STALE`、stale 仍被判 ready、报告复制转写），收口后 PLAN 专项 9 passed。受影响回归 73 passed；最终全量 310 passed、无 xfail。离线 self-test、Ruff、Mypy（26 个脚本）、虚拟环境 pip check 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：evidence 修改后实时覆盖数与旧持久化 coverage 分离；transcript 修改级联失效六类关键产物；固定 prepare 命令修复且不覆盖人工 evidence；persona model 修改后 diagnostics 与输入 SHA 同步；corpus/signals/coverage 和 persona diagnostics 计算入口无写入副作用；CLI 列出 stale 产物和最短命令；即使内容、阶段、治理被独立证明 ready，stale 仍强制最终 ready/商业状态为 false；质量报告保留哈希/指标但不复制标题、转写或绝对路径。
- 剩余风险：当前 evidence 覆盖仍沿用已有 substring 匹配和零类别计分语义，TF-019 将改为结构化 evidence 与 applicable denominator；质量检查为获得当前结果会读取 transcript 多次，大样本性能与单次读取复用由 TF-031 处理；输入哈希与派生计算基于单进程/单写者假设，不提供并发本机进程修改同一 run 时的跨文件快照锁，发生竞态时应重新 quality-check；本任务只为 corpus、signal matrix、signals、coverage 和实时 persona diagnostics 建立关键 freshness 门禁，其他 review 报告通过这些上游 stale 门禁被间接阻断并由同一 prepare 命令一起重建；legacy run 缺 sidecar 时会安全降级为 stale，不做静默迁移；未调用真实 TikHub/ASR/OSS，全部验证使用人工离线数据；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-019 修正 coverage denominator、N/A 和结构化 evidence 解析。

### TF-019 / 2026-07-15

- 状态：completed
- 修改摘要：将 evidence coverage 从全文 substring 扫描改为保守的 Markdown 结构化表格解析，只识别明确的 `Video ID`/`视频 ID` 列；无状态列的旧表格兼容为 accepted，有状态列时只接受明确的 accepted/采用或 rejected/拒绝。`rejected` 必须带非空理由，不计证据分数但从 coverage gap 中关闭；空理由、未知状态和接受/拒绝冲突不会形成证据。coverage bucket 在空集合时返回 `status=not_applicable`、`ratio=null`，主题空类别也保留为 N/A；overall score 只平均 applicable 的四类 bucket 与主题簇指标，零证据不再由空类别抬升到 0.6，并继续报告覆盖视频绝对数量。所有采样阈值改为命名配置并随解释写入 JSON/Markdown，coverage artifact 算法版本提升到 v2。初始 Creator Skill、gap 指引、宿主精修与 persona builder 文档统一为 `Video ID / Status / Reason / Finding` 契约。
- 涉及文件：`scripts/prepare_host_refinement.py`、`scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`tests/quality/test_evidence_coverage.py`、`tests/quality/test_freshness.py`、`references/host_refinement.md`、`references/pipeline.md`、`references/prompts/celebrity/persona_builder.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\quality\test_evidence_coverage.py tests\quality\test_freshness.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\security\test_prompt_injection_isolation.py tests\integration\test_offline_pipeline.py tests\quality\test_evidence_coverage.py tests\quality\test_freshness.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy`；`.\.venv\Scripts\python.exe -m pip check`；`git diff --check -- <TF-019 文件>`。
- 命令结果：TDD RED 为 5 failed，准确复现无证据得 0.6、空 bucket 参与平均、正文/长 ID 子串误命中、rejected 被当作证据和 Markdown 无 N/A；实现后 coverage+freshness 专项 14 passed，安全/离线/quality 受影响集合 32 passed。最终全量 315 passed；离线 self-test、Ruff 全仓、Mypy（26 个脚本）、pip check 和限定文件 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：零证据和 applicable denominator；空短视频/边界/主题 bucket 的 N/A；旧式无状态结构表兼容；正文精确 ID 与 `123`/`1234` 子串隔离；带理由拒绝关闭 gap、空理由拒绝保持 missing；中英文表头/状态；Markdown 的 N/A/rejected 展示；命名阈值与 coverage algorithm v2 manifest。
- 剩余风险：结构化解析有意只接受标准 Markdown pipe table，历史 bullet/prose evidence 必须按文档迁移后才计分；未知 corpus ID、重复/冲突引用目前会保守地忽略或保持缺口，但跨 evidence/persona/corpus 的完整 blocker 由 TF-021 统一实现；persona diagnostics 内部仍有旧的宽松 ID 提取路径，将随 TF-021 收敛；未调用真实 TikHub/ASR/OSS，全部验证使用离线人工数据和 mock 流程；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-020 执行 JSON Schema 运行时验证。

### TF-020 / 2026-07-15

- 状态：completed
- 修改摘要：新增统一的 Draft 2020-12 运行时校验模块，并把 `jsonschema` 固定为运行时依赖 `>=4.23.0,<5.0.0`。persona model、evaluation suite 和 reverse identification schema 现在都带独立 `$id` 与 `x-schema-version=1.0.0`，所有对象层级默认禁止未声明属性；顶层通过 `draft_template` 与 `completed` 两个显式分支区分可生成模板和可交付完成产物，完成分支继续执行最低数量、布尔完成标志和通过状态等约束。质量检查不再按 schema 文件大小判断，而是先验证 schema 契约和元 schema，再校验 JSON 文档；三类产物的 schema 结果全部进入 content readiness 和顶层 quality report，任何缺字段、错类型、多余字段、非法状态、损坏/过期 schema 都会阻断对应 ready 条件。诊断使用 JSON Pointer、校验关键字和受控短消息，不输出绝对路径，也不回显非法文档值。宿主精修模板、离线场景、集成断言和中英文使用说明已同步完成状态约定与修复方式。
- 涉及文件：`requirements.txt`、`requirements-dev.txt`、`scripts/schema_validation.py`、`scripts/prepare_host_refinement.py`、`scripts/creator_pipeline.py`、`scripts/offline_scenarios.py`、`tests/quality/test_json_schemas.py`、`tests/integration/test_offline_pipeline.py`、`SKILL.md`、`references/host_refinement.md`、`references/pipeline.md`、`references/prompts/celebrity/persona_builder.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\quality\test_json_schemas.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\quality\test_json_schemas.py tests\quality\test_freshness.py tests\integration\test_offline_pipeline.py tests\test_provenance.py tests\security\test_prompt_injection_isolation.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git diff --check`。
- 命令结果：初始专项 RED 因 `scripts/schema_validation.py` 不存在产生 1 个收集错误；首个 schema 切片随后以 7 个失败准确暴露未版本化和对象不严格，质量门禁接入前 2 个集成测试失败；新增敏感值不回显断言后又先得到 1 个准确失败。收口后 schema 专项 12 passed，受影响回归 53 passed，全量 327 passed、无 xfail。离线 self-test、Ruff 全仓、Mypy（27 个脚本）和虚拟环境 pip check 全部通过。
- 新增测试：三类 schema 的 Draft、版本、ID 与递归 `additionalProperties: false` 契约；合法模板可验证但不可 ready；三类合法 completed 文档通过；缺字段、错类型、多余字段和非法状态失败并给出 JSON Pointer；运行时依赖存在；大文件但缺 schema 版本仍失败；三类 schema 任一无效都会进入质量报告并阻断 ready；错误诊断不复制非法文档值。
- 剩余风险：TF-020 最初引入的 schema 版本为 `1.0.0`，TF-022 已因声明字段语义变化显式升级为 `1.1.0`；schema 只证明单文档结构与完成状态，evidence/persona/corpus 的跨文件引用真实性由 TF-021 继续收敛，人工 scorecard 自声明绕过由 TF-022 处理；旧 run 中没有版本字段或仍为 `1.0.0` 的 schema 会安全失败，需要重新执行 host refinement prepare 生成；未调用真实 TikHub/ASR/OSS，全部验证使用离线人工数据和 mock 流程；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-021 验证 evidence/persona/corpus 引用完整性。

### TF-021 / 2026-07-15

- 状态：completed
- 修改摘要：新增 `scripts/evidence_model.py` 作为无原文复制、只读且确定性的跨文件引用校验器。每次质量检查都从当前 `selected.compact.json` 与实际 transcript 重建 corpus，不信任旧 `corpus_index.json`；再交叉读取结构化 `evidence_index.md`、`persona_model.json`、`evaluation_suite.json` 和 `reverse_identification.json`。所有证据 ID 必须属于当前 corpus 并进入唯一、无冲突的 accepted evidence 行；persona 的 15 条最低门槛只统计不同且完整映射到 metadata/evidence index/所需 transcript 的有效锚点，伪造 ID、重复锚点和重复表格行不能凑数。topic model 的两条证据必须来自不同视频；script template、expression DNA/judgment/anti-pattern evaluation 引用与 reverse-identification marker 必须有非空 transcript。无 transcript 视频仅在 anchor role 显式使用 `metadata:`/`元数据:` 前缀时才能支撑元数据结论，含糊角色保守按 transcript 证据处理。质量报告顶层新增 `evidence_integrity`，包含输入相对路径/大小/SHA-256、逐 artifact 有效性、anchor mappings、计数，以及带 JSON Pointer 的 `orphan_references`、`missing_references`、`duplicate_references`、`type_mismatches`；文本模式显示完整性状态和四类错误数量。persona、evaluation、reverse 和 content readiness 均有独立 blocker，coverage 解析契约因新增 duplicate 诊断升级到算法 v3。
- 涉及文件：`scripts/evidence_model.py`、`scripts/quality_engine.py`、`scripts/prepare_host_refinement.py`、`scripts/creator_pipeline.py`、`scripts/offline_scenarios.py`、`tests/quality/test_evidence_integrity.py`、`tests/quality/test_evidence_coverage.py`、`tests/integration/test_offline_pipeline.py`、`SKILL.md`、`references/host_refinement.md`、`references/pipeline.md`、`references/prompts/celebrity/persona_builder.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\quality\test_evidence_integrity.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\quality\test_evidence_integrity.py tests\quality\test_evidence_coverage.py tests\quality\test_freshness.py tests\quality\test_json_schemas.py tests\integration\test_offline_pipeline.py tests\test_provenance.py tests\security\test_prompt_injection_isolation.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git diff --check`。
- 命令结果：初始专项 RED 因 `evidence_model` 不存在产生 1 个收集错误；运行目录解析、Markdown duplicate 和 content blocker 接入前为 3 failed；有效锚点计数与 evaluation/reverse 独立门禁为 2 failed；质量文本/输入审计为 1 failed；含糊 metadata role 和重复 evidence 行仍计锚点为 2 failed；coverage 契约版本更新为 1 failed。各切片收口后 TF-021 专项 11 passed，evidence coverage+integrity 16 passed，质量/安全/离线受影响回归 69 passed；最终全量 338 passed、无 xfail。离线 self-test、Ruff 全仓、Mypy（28 个脚本）、虚拟环境 pip check 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：合法跨文件引用；15 个伪造 anchor 计数为 0；topic 同一 ID 两次不满足不同视频规则；metadata-only 视频不能支撑 script/evaluation/reverse 或含糊角色锚点；model/evaluation/reverse 的 orphan/unaccepted ID；重复 evidence 表格行及其锚点失效；当前 metadata/transcript/三份 JSON 的运行时重算；content、persona、evaluation 和 reverse 独立 blocker；顶层报告持久化、输入哈希、绝对路径零复制及文本错误计数；coverage algorithm v3。
- 剩余风险：`metadata:` 是新的显式角色契约，历史 persona anchor 的含糊 role 会安全地默认要求 transcript，必要时需人工迁移；当前只验证引用身份、唯一性、accepted 状态和 transcript 是否非空，不判断 transcript/metadata 内容是否真的支持对应结论，也不验证授权或事实真实性；evaluation 的证据类型根据其声明的 persona 字段分类，Agent 自填字段、case 事实和 scorecard 的独立 evaluator verdict 由 TF-022 收敛；非空但低质量或错误 ASR 仍需结合 ASR entity review 和人工精修判断；未调用真实 TikHub/ASR/OSS，全部验证使用离线人工数据和 mock 流程；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-022 重定义 passed 与 ready，降低自我声明权重。

### TF-022 / 2026-07-15

- 状态：completed
- 修改摘要：新增确定性的 evaluator 与最终状态组合器。`passed` 现在只表示确定性流水线最低完整性；`ready_for_use` 同时要求 `passed=true`、content readiness、ready 阶段覆盖、治理、freshness、三份 runtime schema、跨文件 evidence integrity 和 evaluator verdict 全部通过，`commercial_delivery_ready` 继续严格蕴含 ready。evaluator 每次直接读取当前 persona/evaluation/reverse JSON 与当前 schema，按三份文档 `status=completed`、六个固定 case、实质输入/输出、persona 字段、证据或安全规则、置信度、边界拒绝、style generic marker、反向识别行数、两类唯一 marker 数量、字段/证据/verdict 可追溯性重算，不接受外部 schema verdict 注入，也不复制生成正文。evaluation/reverse 的 case/scorecard `passed`、声明计数、Markdown 结论，以及 usage probe、reviewer、audit 的人工建议全部进入 `advisory_checks`，不再单独翻转硬门禁；文件缺失、空模板或未实质填写仍可阻断。最终 JSON 与文本报告列出 `blocking_checks`、`failed_blockers`、`advisory_checks` 及结构化证据；失败指针统一最多保留 50 项，超限时给出总数和截断标记，evidence 无引用错误但缺锚点时也会显示具体 failed checks。evaluator 的 `computed_from` 覆盖三份当前文档及三份 schema 的相对路径、大小和 SHA-256，兼容 UTF-8 BOM，不含绝对路径。evaluation/reverse scorecard 字段在 schema `1.1.0` 中仅保留类型约束，不再要求 true 或信任声明 marker 数量；旧 `1.0.0` schema 安全失败并需重新 prepare。宿主模板、Skill 和中英文流程说明已同步新语义。
- 涉及文件：`scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`scripts/prepare_host_refinement.py`、`scripts/schema_validation.py`、`scripts/offline_scenarios.py`、`tests/quality/test_readiness_semantics.py`、`tests/quality/test_json_schemas.py`、`tests/integration/test_offline_pipeline.py`、`tests/test_provenance.py`、`SKILL.md`、`references/host_refinement.md`、`references/pipeline.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\quality\test_readiness_semantics.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\quality\test_readiness_semantics.py tests\quality\test_json_schemas.py tests\quality\test_evidence_integrity.py tests\quality\test_freshness.py tests\test_provenance.py tests\integration\test_offline_pipeline.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`git diff --check`。
- 命令结果：基础 evaluator/组合器首轮 RED 为 5 failed，真实 run/advisory 接入 RED 为 2 failed，schema 声明语义、draft status、文本解释、BOM 兼容和 blocker 证据补强均分别先准确失败；独立对抗审查又发现并修复 4 项问题：外部 schema verdict 注入、缺失 freshness 默认放行、usage probe 自评仍作硬门禁、失败指针无统一上限。最终 TF-022 专项 16 passed；核心受影响回归 64 passed；最终全量 355 passed。离线 self-test、Ruff 全仓、Mypy（28 个脚本）、虚拟环境 pip check 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：完整事实在全部自评 false 时仍由 evaluator 通过；把所有自评改 true 不能让空 case 通过；不安全边界输出失败；`passed=false` 强制 ready/商业状态 false；reviewer ready 不能覆盖 schema/evidence failure；draft template 不能伪装完成；真实 run 只读当前 JSON/schema 身份且不复制输出/绝对路径；UTF-8 BOM 兼容；生产入口不可注入 schema verdict；缺 freshness 证明默认阻断；usage/reviewer/audit 建议为 advisory；JSON/text 报告解释 blocker；指针证据限长；schema `1.1.0` 接受 false 声明但继续拒绝错类型。
- 剩余风险：当前 evaluator 是确定性的结构/引用/固定断言检查，能阻止布尔自声明绕过，但不能证明输出事实真实、证据内容在语义上确实支持结论，也不能替代人工授权、法律或内容质量审核；长度与正则断言仍可能被刻意构造文本满足，后续质量任务应继续引入更强的语义评测。usage probe 的通过结论已降为 advisory，其内容完整性仍主要靠模板空值和文件规模检查，真正任务能力由固定 evaluation/reverse evaluator 兜底。`1.0.0` legacy schema 不静默迁移，需重新运行 prepare；本轮未调用真实 TikHub/ASR/OSS，验证均为离线 fixture/mock；doubt-driven 单模型独立审查已完成，自动续跑上下文中未获得外部 CLI 单独授权，因此未执行 cross-model review；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-023 改进 transcript dump、版权重叠和乱码检查。

### TF-023 / 2026-07-15

- 状态：completed
- 修改摘要：新增 `scripts/content_safety.py`，自动发现 final Skill 下全部 `.md`、`.txt`、`.json`、`.yaml`、`.yml`，并与当前全部 transcript 做严格 UTF-8 与版权重叠检查。文本先执行 NFKC、常见裸/括号/SRT 时间戳、空白和标点归一化；以 48 个字符为最小精确匹配，通过逐 transcript 后缀自动机计算真实连续子串，最长重叠不再把不同来源或不相邻片段拼接，总体复制比例按目标覆盖并集计算。普通 Skill 与 evidence/research summary 使用不同阈值，报告只保留相对路径、指标、失败原因和 16 位不可逆指纹，不复制原文、非法字节或绝对路径。编码门禁覆盖非法 UTF-8、replacement character、代码围栏外异常问号密度；逐行围栏解析支持 LF/CRLF、相同标记和 CommonMark 合法的更长关闭围栏，错类型/未闭合围栏不能隐藏异常文本。输入内容只读取一次，同一批字节直接计算 SHA-256/大小和分析指标；POSIX 逐级 `openat` + `O_NOFOLLOW`，Windows 在读取前校验已打开句柄的最终路径，缺失、逃逸、竞态或不可读输入均安全失败。`creator_quality_check` 新增完整 `content_safety_passed` 硬门禁，文本 CLI 输出版权最长重叠、总体比例、失败文件与编码结论；宿主模板和中英文说明同步。
- 涉及文件：`scripts/content_safety.py`、`scripts/creator_pipeline.py`、`scripts/prepare_host_refinement.py`、`tests/quality/test_copyright_overlap.py`、`tests/quality/test_encoding.py`、`SKILL.md`、`references/pipeline.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\quality\test_copyright_overlap.py tests\quality\test_encoding.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <quality/security/offline/provenance/stage/exit 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`git diff --check`。
- 命令结果：初始 TDD RED 因 `content_safety` 尚不存在在收集期失败；核心接入后先以集成失败证明旧 quality-check 未使用新结果，文本 CLI、可选结构化 Skill、顶层输入身份等切片也分别先准确失败。独立对抗审查第一轮 7 个 RED 复现了时间戳绕过、跨来源虚假最长重叠、漏扫嵌套 Skill 文本、分析字节与哈希身份不一致、路径交换不安全、缺失输入异常和 CRLF 围栏误判；第二轮 3 个 RED 固化了中间目录竞态、顶层未硬阻断完整 content-safety 失败和错类型围栏隐藏；第三轮 1 个 RED 固化 CommonMark 更长关闭围栏。三轮修复后的独立复审结论为无 P0/P1 阻断项。最终 TF-023 专项 29 passed；受影响回归 160 passed；最终全量 384 passed。Ruff 全仓、Mypy（29 个脚本）、虚拟环境 pip check、离线 self-test 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：100 字拆行复制；短引用与改写；短 transcript；证据摘要差异阈值；无关代码块；报告无原文/绝对路径；纯分析确定性；裸、括号、毫秒和 SRT 时间戳；不同 transcript 片段不虚假拼接；creator 质量日志、ready 与文本 CLI 硬阻断；结构化 persona 和任意嵌套 YAML 自动发现；replacement character、非法 UTF-8、问号密度、合理问句；LF/CRLF 围栏、错类型围栏和更长合法关闭围栏；精确分析字节身份；缺失输入；最终文件及中间目录符号链接竞态；任意 content-safety 输入失败的顶层硬门禁。
- 剩余风险：当前检测证明的是归一化后的精确序列重叠，不识别语义等价的深度改写、跨语言翻译或同义替换，阈值仍需用真实合规语料持续校准；后缀自动机内存与运行时间对单份超大 transcript 仍近似线性，大规模基准和整体 quality-check 读取复用留给 TF-031；本机只实际执行了 Windows 句柄路径验证，POSIX `openat` 分支通过静态检查和单元逻辑审计但未在本轮 Linux 环境实跑；异常问号仍是启发式指标，罕见的问号密集自然语言可能需要人工判断；16 位匹配指纹不含原文但仍可用于同输入相关性比对；未调用真实 TikHub/ASR/OSS，验证均为离线 fixture/mock；doubt-driven 单模型独立审查已完成，自动续跑上下文中未获得外部 CLI 单独授权，因此未执行 cross-model review；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-024 将科技研究词典改造成可选 taxonomy preset。

### TF-024 / 2026-07-15

- 状态：completed
- 修改摘要：新增 `scripts/research_taxonomy.py`，以冻结 dataclass 和只读 mapping 定义可版本化、不可被调用方污染的 `TaxonomyPreset` 公共契约。原有 THEME/HOOK/ARGUMENT/ENDING/JUDGMENT/ENTITY 词典及主题贡献/边界规则完整迁入显式 `tech_creator@1.0.0`；默认新增只包含教程、案例、观点、风险边界等跨领域结构信号且不预置科技实体的 `generic_zh_creator@1.0.0`。两个 run 创建 CLI 统一支持 `--taxonomy-preset` / `--taxonomy-version`，在创建目录前校验未知 preset 和版本，并把解析后的精确名称/版本写入 `input.json`；两个字段都缺失的 legacy run 按 generic 兼容，只存在其中一个则以可操作错误拒绝。宿主精修的 corpus、逐条 signals、signal matrix、evidence coverage、ASR entity review 和 brief 全部使用同一 preset 并留存 identity；quality artifact manifest 同步加入名称/版本，使运行输入被修改或 preset 切换后旧派生产物失效。README、主 Skill、配置、流水线和宿主精修文档已同步默认、显式 tech 用法、版本语义和核对要求。
- 涉及文件：`scripts/research_taxonomy.py`、`scripts/build_creator_skill.py`、`scripts/run_creator_skill_build.py`、`scripts/prepare_host_refinement.py`、`scripts/quality_engine.py`、`tests/research/test_taxonomy_presets.py`、`README.md`、`SKILL.md`、`references/configuration.md`、`references/pipeline.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\research\test_taxonomy_presets.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <taxonomy/freshness/evidence/security/CLI/stage/ID/offline 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`git diff --check`。
- 命令结果：最初因 `research_taxonomy` 不存在产生 1 个收集错误；建立接口后完整契约出现 8 failed / 2 passed，准确暴露 prepare、run input、manifest 和双 CLI 尚未接入。只读 mapping 与不完整 run identity 又分别先产生 1 个准确失败。最终 TF-024 专项 11 passed，受影响回归 141 passed。全量首次完整执行得到 394 passed / 1 failed，失败为 Windows `os.replace` 的一次 `WinError 5`；该 TF-018 既有路径在隔离目录连续复跑 6/6 通过，随后新目录全量复跑 395 passed，因此判定为不可复现的瞬时文件占用，未在本任务内猜测性修改原子写实现。Ruff 全仓、Mypy（30 个脚本）、虚拟环境 pip check、离线 self-test 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：默认 preset 身份、通用词典无科技实体、注册 mapping 不可变；tech fixture 的七类旧主题、hook、论证、贡献类型和 OpenAI/Agent 专名保持；非科技/legacy corpus 默认不产生 AI/Agent 主题；默认与显式 run 精确记录 taxonomy；研究产物 manifest 携带 identity；未知 preset、错误版本和部分缺失的 run metadata 给出可操作诊断；两个公开 CLI 均在创建 run root 前拒绝非法 taxonomy。
- 剩余风险：preset 目前仍是人工维护的确定性关键词启发式，不会从新领域自动发现主题，证据化候选发现由 TF-025 继续完成；两个字段都缺失的历史 run 会按新规则落到 generic，若要复现迁移前科技词典效果应创建或迁移为显式 `tech_creator@1.0.0`，当前不会自动回写旧 run；`creator_pipeline.py` 的成品丰富度启发式仍含“实验/教程/现场/产业/灰区/风险/工具/产品”等类别词，它不参与本任务的 AI/Agent 主题标注，但其跨领域适用性需在 TF-028 的多领域端到端回归中验证；本轮未调用真实 TikHub/ASR/OSS，全部为离线 fixture/mock；工作区已有混合暂存改动未提交，用户未授权 commit/push。
- 下一建议任务：TF-025 增加无领域假设的主题候选发现。

### TF-025 / 2026-07-16

- 状态：completed
- 修改摘要：新增完全离线、确定性的 `scripts/topic_discovery.py`，从标题和 transcript 计算词频、标题频率、视频级文档频率与严格共现，按真实视频集合生成版本化主题候选；输出 provisional label、区分词、代表视频 ID、覆盖率、证据量和 low/medium/high 置信度，并明确候选不是最终人格结论。通用高频口语、时间戳和无区分内容进入版本化 filter；空语料或无有效区分词返回 `unclassified/insufficient`，单视频证据保持 low，至少覆盖一半语料且跨三个视频才可进入 high，三条视频但只覆盖 3/20 的稀疏小簇会降为 `low_corpus_coverage`。新增可审计决策台账，宿主可 accepted、renamed、merged、rejected；重命名必须提供新标签，合并必须指向另一个现存候选，重新 prepare 不覆盖既有人工决策。候选 JSON/Markdown 已进入 artifact manifest、freshness 重算与 host refinement readiness，transcript 或 taxonomy 输入变化会令旧候选失效；宿主协议、Skill 和中英文流程说明已同步候选回查边界。
- 涉及文件：`scripts/topic_discovery.py`、`scripts/prepare_host_refinement.py`、`scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`tests/research/test_topic_discovery.py`、`README.md`、`SKILL.md`、`references/configuration.md`、`references/pipeline.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\research\test_topic_discovery.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <topic/taxonomy/freshness/evidence/schema/readiness/content-safety/security/offline 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`git diff --check`。
- 命令结果：TDD 首轮因 `topic_discovery` 不存在产生收集错误；补充接口后缺主发现函数、审计模板、prepare 集成、manifest/current derivation、freshness 和 readiness 校验的切片均先准确失败。宿主非法 rename 一度被接受、Markdown 汇总表被候选详情打断、3/20 稀疏小簇被错误提升为 high、低覆盖率 warning 被错误表述为单视频，这四项也分别由失败测试复现后修正。最终 TF-025 专项 9 passed，受影响回归 121 passed；全量 404 passed。Ruff 全仓、Mypy（31 个脚本）、虚拟环境 pip check、离线 self-test 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：餐饮、法律、亲子三类单视频非科技 fixture 能发现源内领域词但只给 low；空/通用词语料不编造候选；跨三个真实视频的共现主题具有稳定 ID、真实代表视频和逐词来源；输入顺序不影响结果；3/4 与 3/20 覆盖率置信度分级；重复 video ID 拒绝；决策模板来源身份和允许动作；Markdown 汇总完整性；prepare 生成候选与 manifest、保留人工 reject、readiness 接入、非法 rename 阻断、transcript 变化触发 stale。
- 剩余风险：当前轻量抽取器使用重叠的中文 2–4 gram 和严格相同视频集合共现，能保证确定性与证据可回查，但可能产生词片段、漏掉同义主题或把语义相近主题拆开；中文分词、跨视频短语质量和原始片段定位由 TF-026 专门收敛。候选决策只校验结构、候选身份和必需字段，不证明 `reviewed_by` 的真实身份，也不把候选自动提升为 persona 事实。未调用真实 TikHub、ASR、OSS 或在线模型，全部验证使用脱敏 fixture、离线数据和 mock；工作区包含此前任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-026 修正中文词语和重复短语分析。

### TF-026 / 2026-07-16

- 状态：completed
- 修改摘要：新增 `scripts/text_analysis.py` 作为确定性文本信号单一契约，使用固定 `jieba==0.42.1` 精确模式和随包本地 HMM 识别未登录词，不下载在线模型；移除项目中无任何代码用途的 `pypinyin`。中文、英文和中英混合语料统一切分为 title/transcript 片段，词语按视频级 document frequency、标题 DF、总频次依次排序，连续中文句子不再整体充当 token。短语仅从词边界上的连续 2–6 token 窗口生成，至少来自两个不同视频才输出；同视频多次重复只增加 `total_frequency`，不能满足跨样本门槛。每个词语/短语保留真实 `representative_video_ids` 和稳定的 `<video_id>#title` / `<video_id>#transcript:NNNN` 片段 ID，短语另含覆盖率与 low/medium/high 置信度。`topic_discovery` 算法升级至 `1.1.0` 并复用统一分词，不再生成重叠 2–4 gram 随机词片段；topic candidates、signal matrix、transcript signals/Markdown 均输出 tokenizer/stopword/minimum-video 版本和片段证据。五类派生产物的 manifest、freshness current summary 和 host readiness 已纳入精确分析契约；缺 `phrase_analysis`、伪造单视频短语或逐视频 `reusable_phrases` 不一致时安全失败。README、主 Skill、配置、流水线、宿主精修说明和生成式 brief/audit 已同步。
- 涉及文件：`scripts/text_analysis.py`、`scripts/topic_discovery.py`、`scripts/prepare_host_refinement.py`、`scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`tests/research/test_chinese_signals.py`、`requirements.txt`、`README.md`、`SKILL.md`、`references/configuration.md`、`references/pipeline.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\research\test_chinese_signals.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <chinese/topic/taxonomy/freshness/readiness/security/offline/artifact/provenance 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe -m pip show jieba`；`git diff --check`。
- 命令结果：首轮 RED 因 `text_analysis` 不存在产生收集错误；最小实现后 4 passed / 1 failed，证明关闭 HMM 会把常见未登录词“食材”错误拆成单字，依据本地确定性 Viterbi 行为改为精确模式 + HMM 后 5 passed。topic/host 接入先得到 2 个准确失败；manifest 版本契约、缺失 `phrase_analysis` 的 readiness 旁路、freshness current 缺短语摘要和控制字符 video ID 又分别先由失败测试复现后修复。TF-026 基础与集成专项共 11 个 pytest case（含 3 个 ID 参数边界），受影响回归 94 passed；最终全量 415 passed。Ruff 全仓、Mypy（32 个脚本）、虚拟环境 pip check、离线 self-test 和 diff whitespace 检查全部通过；`pip show` 确认实际安装 `jieba 0.42.1`、MIT 许可、无额外依赖（diff 仅有 Git 既有 LF/CRLF 策略提示）。五轴代码审查未留 Critical/Required 项。
- 新增测试：中文句子被真实分词且不成为整句 token；高 TF 单视频词排在更高视频 DF 词之后；同视频重复六次不生成跨样本短语；两视频共同短语记录独立 DF、累计 TF、置信度、视频与逐句片段 ID；输入顺序不影响结果；中英混合/纯英文不报错；topic candidates 公开 tokenizer 与词语片段契约；prepare JSON/Markdown、manifest、freshness 和 readiness 端到端接入；缺 `phrase_analysis` 即使伪造 freshness 也不能通过；依赖清单使用真实 tokenizer 且不保留 pinyin；首尾空格、`#` 和控制字符 ID 被拒绝。
- 剩余风险：`jieba` 默认词典与随包 HMM 是通用语言模型，仍可能拆错罕见人名、品牌和领域术语；TF-027 会为专名增加 preset/项目词典和人工处理状态，宿主在此之前必须依据片段 ID 回查。当前短语检测只识别归一化后的精确 token 序列，不识别同义改写、语序变化或跨语言等价表达；低覆盖候选保持 low，不自动升级为 persona。片段 ID 是由当前标题和标点切句生成的稳定定位符，不是供应商原始 ASR segment ID；转写编辑可能重编号，但输入哈希会同时令旧产物 stale。prepare 仍会为 topic、signals、matrix 分别执行分词，语义正确但大 corpus 的读取/计算复用由 TF-031 收敛。未调用真实 TikHub、ASR、OSS，全部验证为脱敏 fixture、离线数据和 mock；工作区包含此前任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-027 让 ASR 专名复核可扩展并记录状态。

### TF-027 / 2026-07-16

- 状态：completed
- 修改摘要：新增 `scripts/entity_review.py` 作为版本化 ASR 专名检测与人工复核单一契约。taxonomy preset 的现有专名与 run 内 `research/entity_dictionary.json` 项目扩展合并，项目词典可登记非科技品牌、人物、机构、地点、产品和专业术语，并声明 canonical term、显式别名、类别、high/medium/low 影响级别与说明；NFKC、casefold 和空格/点/横线/斜线/中点压缩统一大小写、全半角、分隔写法和中英文混写，同一归一化别名跨实体冲突时拒绝。词典边界限制为 1 MiB、1000 个实体和每实体 50 个别名，额外 ASCII 候选只保留按视频 DF/频次排序的前 60 项。每个候选生成稳定 ID、实际命中形式、影响级别、视频 ID、title/transcript 片段 ID、artifact 路径和 raw ASR 引用；检测报告与 Markdown 可重建，`asr_entity_decisions.json` 作为独立持久修正层记录 `unresolved/confirmed/corrected/ignored`、处理说明、审查者和时间。prepare 按稳定 ID 保留已有决策、给新增候选补 unresolved，并把消失/重复旧项移入 orphan；不改 `transcripts/*.txt`。corrected 项必须填写正确写法及最终 `skill/` 的 path/locator，质量检查动态验证报告/台账而非信任声明：高影响 unresolved 阻断，中低影响 unresolved 为 warning，所有必审项完全未开始也阻断。项目词典、selected metadata 或 transcript 变化会使专名 JSON/Markdown manifest stale；报告与决策路径、计数、blocker/warning、修正映射进入 host/content readiness。Markdown 对不可信 canonical term 做数值实体编码，项目词典和额外候选均有资源上限。README、主 Skill、配置、流水线、宿主精修、生成式 brief/audit 与离线产物契约已同步。
- 涉及文件：`scripts/entity_review.py`、`scripts/prepare_host_refinement.py`、`scripts/quality_engine.py`、`scripts/creator_pipeline.py`、`scripts/offline_scenarios.py`、`tests/research/test_entity_review.py`、`README.md`、`SKILL.md`、`references/configuration.md`、`references/pipeline.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\research\test_entity_review.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <entity/taxonomy/topic/chinese/freshness/offline 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`git diff --check`。
- 命令结果：TDD 首轮因 `entity_review` 不存在产生收集错误；独立契约实现后 6 项中 5 项通过，剩余 1 项准确暴露 host readiness 尚未读取人工状态。接入 prepare/readiness/manifest 后专项 7 passed，taxonomy、topic、中文信号、freshness 与离线集成受影响回归 53 passed。五轴收尾审查发现并修复 Markdown 活动内容编码和项目词典资源无上限两项 Required 问题，并补充矛盾 unresolved 字段、重叠别名重复计数和 `review_required` 篡改校验；最终 TF-027 专项 8 passed。审查修复后的第一次全量为 422 passed / 1 failed，唯一失败是 TF-024 已记录过的 Windows `os.replace` 瞬时 `WinError 5`，落点仍为既有 `persona_model_diagnostics.json` 原子写而非专名链路；同一单测用独立目录复现 3 次为 2 passed / 1 failed，因此未把它误判为 TF-027 回归，也未越界修改 TF-005 公共原子写语义。随后全新目录全量复跑 423 passed。Ruff 全仓、Mypy（33 个脚本）、虚拟环境 pip check、离线 self-test 和 diff whitespace 检查全部通过（仅 Git 既有 LF/CRLF 策略提示）。
- 新增测试：preset + 项目词典合并；非科技品牌/人物/医学术语；大小写、全半角分隔、显式别名和中英文混写；同一片段重叠别名不重复计数；别名冲突与别名数量上限拒绝；不可信 canonical Markdown 编码；全 unresolved 审计、伪造 `review_required=false` 和矛盾 unresolved 字段不能完成；high blocker 与 non-high warning；confirmed/corrected 四态校验；corrected 缺最终文件失败，完整时保留原始片段到最终 Skill 的映射；raw ASR 字节不改；host readiness 不再按文件存在放行；prepare 保留人工状态；词典变化只令专名报告 stale，corpus 保持 fresh；专名 JSON/Markdown manifest 可复用。
- 剩余风险：专名检测仍依赖人工维护的 canonical/alias 列表与字面匹配，无法自动判断同音错字、语义别名或事实上的正确写法；自动 ASCII 候选只是有界启发式，中低影响未处理只告警，仍需要宿主结合最终用途审查。`reviewed_by`/`reviewed_at` 只验证非空，不能证明真实身份或时间真实性；`final_references.locator` 保留人工定位文本，不验证它是否语义支持修正。片段 ID 仍来自当前标点切句而非供应商原始 segment ID，转写变更会用 manifest stale 强制重审。Windows 下既有 `io_utils.atomic_write_text` 偶发 `os.replace WinError 5` 已确认可间歇复现，应在独立可靠性任务中按有界重试/文件占用诊断处理；本轮最终全量已通过但不代表该风险消失。未调用真实 TikHub、ASR、OSS 或在线模型，全部验证为脱敏 fixture、离线数据和 mock；工作区包含此前任务的混合暂存/未暂存改动，用户未授权 commit/push。代码审查 skill 引用的 security/performance 补充清单在本地技能包缺失，已依据主五轴清单和项目既有不可信语料规范完成同等审查。
- 下一建议任务：TF-028 增加跨领域端到端回归套件。

### TF-028 / 2026-07-16

- 状态：completed
- 修改摘要：新增科技、美食、亲子沟通三套各 3 条的人工原创短 corpus，三域均通过真实离线 runner、host refinement 和 quality recheck；每域检查 taxonomy identity、主主题候选、Hook、论证、边界样本、贡献类型、证据覆盖和 ready 前置条件。科技域显式使用 `tech_creator`，美食与亲子域保持默认 `generic_zh_creator`，并断言后两者不产生科技主题或 preset 专名；美食主候选稳定为“口感/火候/食材”，亲子主候选稳定为“情绪/选择/沟通”，三域重复短语均有 3 视频 high confidence 和片段来源。默认 pytest 会直接收集该套件，无 slow/skip 标记，本机三域专项约 14.6 秒。代码审查将重复 subprocess 编排收敛为 `run_offline_corpus()` 公共 helper，原 self-test 与跨领域回归继续共享同一 runner/产物定位路径。Checkpoint 复核发现专名此前只有 impact/status 而无显式置信度，因此将专名算法升级为 `1.1.0`：注册词典命中为高识别置信，自动 ASCII 候选按视频级证据分级，JSON/Markdown 同步记录，审计会拒绝篡改后的 confidence；该置信度只描述识别信号，不替代事实核查。
- 涉及文件：`tests/fixtures/corpora/tech/**`、`tests/fixtures/corpora/food/**`、`tests/fixtures/corpora/parenting/**`、`tests/fixtures/manifest.json`、`tests/fixtures/README.md`、`tests/test_fixtures.py`、`tests/integration/test_cross_domain_pipeline.py`、`scripts/offline_scenarios.py`、`scripts/entity_review.py`、`tests/research/test_entity_review.py`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\integration\test_cross_domain_pipeline.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <fixture/taxonomy/topic/chinese/entity/evidence/readiness/offline/cross-domain 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；secret 模式扫描；`git diff --check`。
- 命令结果：TDD 首轮因科技 corpus 缺失得到 1 failed；补齐 fixture 后清单/脱敏契约 12 passed。三域初跑的真实流水线均成功，测试先后用 3 个和 1 个失败暴露 `signals_used` 名称假设、科技分词粒度与第二条科技 Hook fixture 不匹配，校正测试/样本后专项 11 passed。受影响回归 88 passed；共享 helper 重构后旧+新集成 17 passed。Checkpoint 的专名 confidence 契约先准确得到 2 failed，最小实现与防篡改校验后专名专项 8 passed，三域专项再次 11 passed。最终全量两次均为 435 passed（最终 108.82 秒）；Ruff 全仓、Mypy（33 个脚本）、虚拟环境 pip check、离线 self-test、secret 扫描和 diff whitespace 全部通过，仅有 Git 既有 LF/CRLF 策略提示。五轴代码审查未留 Critical/Required 项；skill 引用的 security/performance 补充清单在本地技能包缺失，已按主五轴、fixture 资源上限和项目不可信输入规范完成同等审查。
- 新增测试：三域短小/人工构造/ID 对齐契约；三套完整 draft/refinement 产物；taxonomy 在 input/corpus/signals/coverage/entities 间一致；主题候选的通用发现信号、high confidence、视频 DF 和片段来源；逐条 Hook/论证/贡献与域内边界；非科技主题和专名无科技 preset 污染；跨三视频重复短语的 high confidence 与来源；空 evidence 保持 score 0 且不能 ready；科技 OpenAI/Agent 专名有来源与置信度；注册/自动专名 confidence 分级、Markdown 展示和篡改拒绝。
- 剩余风险：三域证据均为刻意短小的人工 fixture，只证明确定性离线泛化，不替代真实账号授权 smoke test；主题与短语依赖精确分词/重复，不能覆盖同义改写和隐含语义。专名 confidence 表示“字面命中/重复信号的识别置信度”，不证明实体事实正确，仍须人工审计。正式跨平台 CI workflow 由 TF-039 建立；当前通过默认 pytest testpaths 和全量收集证明套件已进入标准测试路径。Windows 原子 `os.replace` 偶发 `WinError 5` 的既有风险仍存在，但本轮两次最终全量均未复现。未调用真实 TikHub、ASR、OSS 或在线模型；工作区仍含此前任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-029 统一网络重试、限流和 deadline。

### TF-029 / 2026-07-16

- 状态：completed
- 修改摘要：新增 `scripts/retry_policy.py` 作为统一、纯函数可测的 provider 恢复策略，最大尝试数、单次 timeout、总 deadline、指数退避、jitter 和 `Retry-After` 均有硬上限；429、500/502/503/504、连接超时、读取超时与 SDK 嵌套网络异常分类重试，401 等参数/认证 4xx 立即返回调用方处理。`RetryError` 保留稳定错误码、实际尝试次数和脱敏限长摘要；迟到的成功响应也按总 deadline 失败并关闭。TikHub JSON/抖音短链、OpenAI-compatible chat/multipart ASR、DashScope 提交/查询以及 OSS 上传/删除/回滚已接入同一策略，multipart 每次重试重新打开文件，OSS 每次尝试把剩余 timeout 下传给 SDK。新增 `scripts/dashscope_polling.py` 独立承载异步任务状态机，`PENDING/QUEUED/RUNNING/PROCESSING` 可继续，`FAILED/CANCELED` 立即失败，未知/空状态 fail closed；旧 `wait` 配置兼容地转为本地有界轮询，避免当前 DashScope SDK 接收但不执行 `wait_timeout` 的无界实现。统一参数进入 run 配置白名单、默认值、数值/关系校验和三份配置文档，旧 `ALI_ASR_RETRY` 仅作为未设置统一次数参数时的兼容后备。五轴代码审查将轮询状态机从已超 1000 行的 adapter 中抽离，并补上 DashScope 非重试 SDK 异常的脱敏边界，未留 Critical/Required 项。
- 涉及文件：`scripts/retry_policy.py`、`scripts/dashscope_polling.py`、`scripts/provider_adapters.py`、`scripts/build_creator_skill.py`、`scripts/input_validation.py`、`tests/providers/test_retry_policy.py`、`tests/providers/test_asr_polling.py`、`tests/test_oss_lifecycle.py`、`tests/test_cli_validation.py`、`.env.example`、`references/config.example.env`、`references/configuration.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\providers\test_retry_policy.py tests\providers\test_asr_polling.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <provider/OSS/URL/redaction/CLI/cache/audio/offline/cross-domain 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m ruff check scripts tests`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；secret 模式扫描；`git diff --check`。
- 命令结果：TDD 首轮因 `retry_policy` 不存在产生收集错误；纯策略实现后 16 passed，接入 provider 的四项用例先以缺少 `retry` 参数准确失败，适配后重试目标套件转绿。DashScope 九项轮询用例先全部因接口不存在失败；源码核对发现当前 SDK `wait()` 仅透传 `**kwargs` 且内部仍为 `while True`，因此改为受控本地轮询并增加每次 fetch 剩余时限。抖音与 OSS 两项接入也分别先以缺少接口参数失败，再转绿。严格 deadline 的“成功恰好到达时限”边界先得到 2 个失败，修正为闭区间后通过；DashScope `FAILED` 无产物、SDK 异常脱敏与 OSS timeout 下传均有直接回归。最终专项/核心配置集合 125 passed，网络与脱敏受影响集合 92 passed，缓存/分片/CLI/离线跨领域回归 103 passed；全量 492 passed（119.92 秒）。Ruff 全仓、Mypy（35 个脚本）、虚拟环境 pip check、离线 self-test、secret 扫描和 diff whitespace 全部通过；secret 扫描只命中测试中显式命名的 synthetic 假密钥，Git 仅提示既有 LF/CRLF 策略。代码审查 skill 引用的 security/performance 补充清单在本地技能包缺失，已按主五轴、项目 SSRF/脱敏规范和 provider 资源上限完成同等审查。
- 新增测试：429 遵守秒数 `Retry-After` 并钳制后续 timeout；过长等待不越过总 deadline；持续 503 的指数退避、响应关闭与实际尝试计数；401 单次请求；连接/读取超时分码；jitter 和非法策略边界；迟到成功失败；SDK 503 异常分类；错误摘要路径/密钥脱敏与长度上限；TikHub JSON、抖音解析 503 后恢复；compatible 401/503；multipart 重试重开文件；DashScope 成功、FAILED、未知状态、无界 RUNNING、非法时限、迟到成功、旧 wait 配置、本地适配器无产物与异常脱敏；OSS 上传/删除 503 后恢复并接收逐次 timeout；新增配置字段越界和 max-backoff 小于 base-backoff 时在创建 run 前失败。
- 剩余风险：未调用真实 TikHub、DashScope、compatible ASR 或 OSS，provider 行为只以脱敏 fake/mock 和本机已安装 SDK 源码/签名验证；真实服务的非标准状态码、响应头和 SDK 异常形状仍需获授权后 smoke test。总 deadline 依赖底层调用遵守下传 timeout；当前 urllib、requests、DashScope `request_timeout` 与 OSS `bucket.timeout` 均已接入，但第三方库若自身忽略 timeout，Python 外层无法强制中断正在执行的同步调用。结构化尝试事件、耗时和 run summary 由 TF-030 接续；类型化单一 Settings 和自动生成配置文档由 TF-033/TF-034 收敛。Windows 原子 `os.replace` 偶发 `WinError 5` 的既有风险仍存在，本轮全量未复现。工作区继续包含此前任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-030 增加结构化日志、步骤耗时和错误代码。

### TF-030 / 2026-07-16

- 状态：completed
- 修改摘要：新增 `scripts/logging_utils.py` 作为本地运行可观测性的单一事件模型；主运行和恢复运行按同一 `correlation_id` 原子写入 `logs/pipeline_events.json`，并从同一 `RunEvent` 渲染控制台 `[telemetry]` 行。每个步骤记录 timezone-aware 开始/完成时间、单调时钟耗时以及 input/succeeded/failed/skipped 计数；`pipeline_result` 升级为 schema v2 并保存稳定低基数错误码。异常统一分类为 `NETWORK_TIMEOUT`、`RATE_LIMIT`、`PROVIDER_UNAVAILABLE`、`INVALID_MEDIA`、`ASR_PARSE_FAILED`、`STALE_ARTIFACT`、`INVALID_JSON`、`INVALID_INPUT`、`WORKFLOW_STATE_ERROR` 和受控 fallback；错误摘要使用既有 scrubber 脱敏并限制为 500 字符。`run_summary.json.execution` 新增总/逐步耗时、最慢步骤、失败步骤、事件数和下一条可复制命令，异常中止时也会落盘。恢复前校验历史 schema、run_id、correlation_id 和连续序号，拒绝向损坏事件流继续追加。五轴审查通过先红后绿的测试修复了未知顶层异常丢失 `UNEXPECTED_ERROR`、损坏历史事件被接受、成功步骤可携带错误码三项 Required 问题，未留 Critical/Required 项。使用、流水线、配置与 README 文档已同步。
- 涉及文件：`scripts/logging_utils.py`、`scripts/pipeline_models.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`scripts/resume_creator_run.py`、`tests/test_structured_logging.py`、`tests/test_step_results.py`、`tests/integration/test_offline_pipeline.py`、`README.md`、`SKILL.md`、`references/pipeline.md`、`references/configuration.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_structured_logging.py -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest <structured/step/pipeline/workflow/stage/redaction/offline 受影响集合> -q --basetemp <独立临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；运行代码/用户文档 secret 模式扫描；`git diff --check`。
- 命令结果：专项首轮在 `logging_utils` 尚不存在时于收集期准确 RED；分类、事件和离线集成分段转绿。五轴审查追加的 4 个回归节点先得到 4 failed，收紧边界后 4 passed。最终 TF-030 专项 12 passed，受影响回归 51 passed。首轮全量为 504 passed / 1 failed，唯一失败是已记录的 Windows F 盘 `os.replace WinError 5`，落点为既有 TF-018 `persona_model_diagnostics.json` 而非 TF-030；同一用例迁移到系统临时盘后 1 passed，随后系统临时盘全量 505 passed（121.01 秒）。Ruff 全仓、Mypy（36 个脚本）、虚拟环境 pip check、离线 self-test、运行代码/用户文档敏感信息扫描和 diff whitespace 全部通过，仅 Git 提示既有 LF/CRLF 策略。审查 skill 引用的 security/performance 扩展检查表在本机不存在，已按主五轴清单、项目脱敏规范和边界测试完成同等审查。
- 新增测试：JSON/控制台共享事件语义；步骤时间、耗时和四类计数不变式；网络超时、限流、无效媒体、ASR 解析、stale 和未知异常稳定分类；顶层与步骤错误码聚合；已知密钥、Authorization 和签名 URL 脱敏/限长；不同 correlation 或损坏历史日志拒绝追加；失败步骤可恢复性与下一命令；成功、损坏元数据和恢复运行端到端产物；成功步骤不得伪造错误码；旧离线失败用例改为断言终态摘要确实落盘。
- 剩余风险：未调用真实 TikHub、ASR 或 OSS，结构化日志与恢复行为均以脱敏 fixture、fake clock 和离线子进程验证。当前是单机 run 内的小型 JSON 事件流，没有接入外部日志/metrics/tracing 后端；这是本任务的明确边界，不影响本地运维摘要。结果中的显式 `run_dir`、产物路径和可复制命令仍可包含本机路径，但错误摘要会脱敏；使用者应按 run 目录本身的访问级别保护这些运维字段。Windows F 盘上既有原子 `os.replace` 仍可受文件占用影响，系统临时盘全量已通过，本轮未越界改写 TF-005 公共 I/O 语义。工作区继续包含前 29 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-031 减少 host refinement 对 transcript 的重复读取。

### TF-031 / 2026-07-16

- 状态：completed
- 修改摘要：新增 `scripts/corpus.py` 作为单次 prepare 内的有界、不可变、run 绑定语料快照；每份 transcript 用一次二进制流式读取同时完成 UTF-8 BOM 解码、分析文本归一化、字节数、SHA-256 和修改时间身份计算。corpus index、topic candidates、transcript signals、signal matrix、ASR entity review、brief 和 artifact manifest 显式共享同一快照，quality derivation 在自己的独立读取执行中也只建一份快照。默认单文件 500,000 字符、总 corpus 5,000,000 字符；超限安全失败且返回按高互动/长转写/短转写/边界风险/其余样本分层的 `hierarchical_batch_index` 与超大单文档连续分段策略，不静默截断。快照拒绝跨 run、run 外文档和加载后变更；不可读文件和输入竞态使用稳定错误码且不泄露绝对路径。使用、流水线和宿主精修文档已同步。
- 涉及文件：`scripts/corpus.py`、`scripts/prepare_host_refinement.py`、`scripts/quality_engine.py`、`tests/performance/test_corpus_loading.py`、`SKILL.md`、`references/pipeline.md`、`references/host_refinement.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\performance\test_corpus_loading.py -q -s --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m pytest <topic/chinese/entity/taxonomy/freshness/security/artifact/ID/offline/cross-domain 受影响集合> -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；任务文件敏感模式扫描；`git diff --check`。
- 命令结果：初始单次读取 RED 准确证明旧路径每份 transcript 打开 7 或 8 次；完整契约在 `corpus` 模块尚不存在时于收集期 RED。分层容量、语义等价、跨 run/变更、伪造来源、不可读错误和 CLI 无部分输出错误边界均经过先红后绿。最终 TF-031 专项 9 passed（21.72 秒）；50 份中等语料的等价基准为旧路径 7.9160 秒、快照路径 5.7370 秒，比值 0.7247，约快 27.5%；受影响回归 99 passed；系统临时目录全量 514 passed（168.18 秒）。离线 self-test、Ruff 全仓、Mypy（37 个脚本）、虚拟环境 pip check、任务文件敏感模式扫描和 diff whitespace 检查全部通过，仅 Git 提示既有 LF/CRLF 策略。五轴审查通过回归测试修复了 run 外伪造快照、并发变更 traceback、不可读文件冒泡和超限建议容量混淆四项 Required 问题，未留 Critical/Required 项。审查 skill 引用的 security/performance 扩展清单在本机技能包中缺失，已按完整主五轴、项目路径边界和资源上限规则完成同等审查。
- 新增测试：真实 prepare 的逐文件一次读取计数；七类转写消费者与旧路径深度语义等价；单文件/总语料字符上限与不截断层级策略；跨 run 快照、变更输入和 run 外伪造文档拒绝；不可读错误脱敏；生成中变更时稳定 CLI 失败且不留 corpus 部分输出；50 份中等语料的前后耗时和输出等价基准。
- 剩余风险：性能比较为稳定离线工作负载，通过每次 transcript open 模拟 4 ms 慢存储延迟，未代替不同磁盘、杀毒软件和真实大样本的现场基准。快照同时保留源文和规范化文本以维持 brief 完全等价，但已由 500,000/5,000,000 字符硬上限约束；这两个上限目前是有文档的代码默认值，等 TF-033 统一 Settings 时再决定是否开放安全配置。超限时本任务保证失败安全并输出层级策略，不在单次 prepare 中自动启动多批次编排。工作区继续包含前 30 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-032 限制媒体并发并实现本地产物保留策略。

### TF-032 / 2026-07-16

- 状态：completed
- 修改摘要：将下载、FFmpeg 和 ASR 分别约束为独立 worker pool；下载沿用默认 6、硬上限 32，新增 FFmpeg 默认 2、硬上限 8，ASR 沿用默认 4、硬上限收紧为 16，FFmpeg 结果按输入 ID 稳定排序以保持缓存与清单语义。OpenAI-compatible chat 在 Base64 前使用有界读取检查分片大小，默认单片 8 MiB、硬上限 32 MiB，并限制“并发数 × 单片上限”的原始音频预算不超过 128 MiB；file-url/DashScope 路径不错误套用 Base64 预算。retention policy 覆盖视频、音频、ASR chunks、分片结果和 raw provider JSON；apply 会重新生成并严格比对 dry-run 计划，在首次删除前完整预检所有相对路径，并在每个 unlink 前再次验证父路径和目标仍位于 run 内。删除中途发生目录 symlink/junction 置换时停止后续删除、保全 run 外文件，并写入脱敏的 `partial` 审计回执。配置模板、使用说明和流水线文档已同步。
- 涉及文件：`scripts/input_validation.py`、`scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`scripts/run_creator_skill_build.py`、`scripts/provider_adapters.py`、`scripts/retention.py`、`tests/performance/test_concurrency_limits.py`、`tests/test_retention_policy.py`、`tests/test_cli_validation.py`、`.env.example`、`references/config.example.env`、`references/configuration.md`、`references/pipeline.md`、`README.md`、`SKILL.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\performance\test_concurrency_limits.py tests\test_retention_policy.py -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\test_cli_validation.py <TF-032 专项> -q --basetemp <系统临时目录>`；受影响的下载/媒体/分片/缓存/provider/安全/清单/日志/OSS/离线流水线回归；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；真实本地 FFmpeg 三视频烟测；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；任务文件敏感模式扫描；`git diff --check`。
- 命令结果：TDD 首轮为 3 failed / 2 passed，分别暴露 FFmpeg 仍串行、超大音频先 Base64 后检查、伪造清理计划可删除 run 外文件；配置边界首轮 6 failed，证明三个并发值和 Base64 单片上限没有安全范围；组合预算、provider 适用范围、父目录 symlink 置换和 partial 回执也都先由失败测试复现后收口。最终 TF-032 专项 16 passed，专项加 CLI 配置边界 98 passed，受影响回归 160 passed；系统临时目录全量 527 passed（145.34 秒）。真实本地 FFmpeg 烟测将 3 个短 MP4 并发转换为 3 个 MP3，状态均为 `extracted` 且 3 份相邻 manifest 完整。Ruff 全仓、Mypy（37 个脚本）、虚拟环境 pip check、离线 self-test、任务文件敏感模式扫描和 diff whitespace 检查全部通过；敏感模式仅命中 3 个既有测试文件中的合成假凭证，Git 仅提示既有 LF/CRLF 策略。
- 新增测试：下载/FFmpeg/ASR 三组独立峰值并发计数；FFmpeg 多输入输出与并发 2 上限；compatible 超大分片在 `b64encode` 调用前失败；并发 16 × 单片 32 MiB 的组合预算在创建 worker 前失败；file-url provider 不误用 Base64 预算；各配置的零值和过大值在 run 创建前失败；dry-run/实际列表相等；视频、音频、chunk、分片结果、文本和 raw provider JSON 的策略覆盖；伪造 `../` 计划整批预检失败且零删除；父目录置换为 run 外 symlink 时即时复检、停止删除并写 partial 回执。
- 剩余风险：并发峰值测试使用可控本地工作负载，真实烟测确认了 FFmpeg 产物但未替代不同 CPU、磁盘和杀毒环境下的吞吐调参；未调用真实 TikHub、ASR 或 OSS。128 MiB 上限约束的是编码前原始音频字节，Base64、JSON 和 HTTP 客户端仍会产生额外但有界的内存开销。Windows 缺少基于目录句柄的 `unlinkat` 等同语义，每项删除已缩短为“即时复检后 unlink”，但无法从语言层完全消除最后极短的 TOCTOU 窗口；该工具仍应只对本机、单操作者控制的 run 使用。三套配置加载器和默认值漂移由下一项 TF-033 收敛。工作区继续包含前 31 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-033 建立单一、类型化 Settings 模型。

### TF-033 / 2026-07-16

- 状态：completed（计划总进度 33/42）。
- 修改摘要：新增不可变、类型化的 `scripts/settings.py`，以约 75 项 `SettingSpec` 集中声明字段类型、默认值、范围、可选性、secret、枚举、endpoint 类型和说明；明确默认值 < `.env` 文件 < 进程环境变量 < 显式 CLI override 的优先级，并拒绝未知 CLI override。布尔、整数、浮点、枚举、绝对 HTTP(S) endpoint 和 TikHub 相对 endpoint 在任何运行工作前解析并快速失败；pagination 三项与 ASR retry 全部进入 Settings，旧 `ALI_ASR_RETRY` 只在统一重试次数未显式设置时兼容回填。普通序列化、`repr` 和 run 快照省略 secret 字段，并清理非 secret 字段中误嵌的凭证；快照新增 `settings_schema_version=1`。六个运行入口和 bootstrap/config-check 均迁移到同一 loader，旧 loader 定义只保留在 Settings 中作为兼容别名。默认 ASR 组合统一为 `openai-compatible` / `qwen3-asr-flash`；显式选择 `aliyun` 且未配置模型时，由同一规则派生 `fun-asr`，显式模型仍优先。五轴审查通过先红后绿的测试修复了未知 CLI override 被忽略、相对 endpoint 穿越、Settings repr 泄密、普通序列化中嵌入 secret、旧 retry 未生效、legacy 快照被无关历史字段阻断，以及 provider/model 默认组合漂移，未留 Critical/Required 项。
- 涉及文件：`scripts/settings.py`、`scripts/build_creator_skill.py`、`scripts/config_check.py`、`scripts/creator_pipeline.py`、`scripts/provider_adapters.py`、`scripts/run_creator_skill_build.py`、`scripts/resume_creator_run.py`、`scripts/input_validation.py`、`tests/test_settings.py`、`tests/test_cli_validation.py`、`tests/security/test_redaction.py`、`.env.example`、`references/config.example.env`、`references/configuration.md`、`references/pipeline.md`、`README.md`、`SKILL.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_settings.py -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\test_cli_validation.py -q --basetemp <系统临时目录>`；ASR/provider/cache 相邻测试；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；任务文件高置信 secret 模式扫描；重复 loader/default 静态扫描；`git diff --check`。
- 命令结果：TDD 首轮因 `settings` 模块不存在在收集期 RED；首个模型增量为 13 passed / 2 failed，准确暴露运行创建尚不接收 Settings 和旧 loader 未移除。后续审查测试分别复现相对 endpoint 穿越、未知 override、repr 泄密、legacy retry、嵌入 secret、历史快照过度校验和 `aliyun` 错用兼容模型，均转绿。最终 Settings 专项 25 passed，CLI 启动校验 93 passed，ASR/provider/cache 相邻回归 69 passed；系统临时目录全量 563 passed（153.56 秒）。Ruff 全仓、Mypy（38 个脚本）、虚拟环境 pip check、离线 self-test、高置信 secret 扫描和 diff whitespace 检查全部通过；Git 仅提示既有 LF/CRLF 策略。`ruff format --check` 会要求重排 62 个既有文件，超出本任务最小范围，因此未做全仓机械格式化，项目既有 Ruff lint 门禁已通过。技能包引用的 definition-of-done/security/performance 扩展清单在本机不存在，已按各主技能清单、项目安全边界和实际质量门禁完成同等验证。
- 新增测试：配置四层优先级、类型化访问与规范环境值；整数/布尔/枚举/绝对及相对 endpoint 非法值；字段元数据完整性和旧 CONFIG_KEYS/default 漂移；未知 CLI override；默认及显式 aliyun 的 provider/model 组合；普通序列化、repr、run 快照和嵌入 secret 清理；pagination/ASR retry 快照；旧 loader 静态消失和六个入口共享 loader；四个辅助 CLI 在工作前拒绝非法配置；legacy 平面快照只校验当前步骤相关字段。
- 剩余风险：未使用真实 TikHub、DashScope、compatible ASR 或 OSS 做在线 smoke test；Settings schema 与两份 env 模板目前仍需人工同步，自动生成和 CI drift test 由 TF-034 接续。为兼容旧 import，`settings.load_env_file` 仍作为薄别名保留；死配置和正式废弃策略由 TF-037 处理。`.env` 中与项目无关或未知的键会被忽略，显式 CLI override 的未知键会拒绝；若要把 env 拼写错误也升级为强校验，需要先定义第三方环境变量命名空间边界。当前 Settings 不回写历史 run，旧快照迁移与诊断由 TF-038 处理。工作区继续包含前 32 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-034 由 Settings 自动生成配置模板和文档表。

### TF-034 / 2026-07-16

- 状态：completed（计划总进度 34/42）。
- 修改摘要：新增 `scripts/generate_config_docs.py`，从当前 `SETTING_SPECS` 确定性生成根 `.env.example`、generic `references/config.example.env`、`references/configuration.md` 的标记区块和 `references/settings.schema.json`；默认写入使用既有原子文本替换，`--check` 只比较并列出漂移文件，不修改磁盘。根模板显式应用唯一命名的 TikHub App V3 preset，参考模板保持 generic Settings 默认；测试证明两者字段全集一致，赋值差异恰好等于五个 preset 字段，模板头部同时解释意图。Settings 元数据新增 `group/tier/status/replacement`，当前 75 项字段中 52 项标为 advanced、`ALI_ASR_RETRY` 标为 deprecated 并指向统一重试键，`ALI_ASR_APP_KEY`、`AUTO_RESUME`、`MAX_INPUT_TOKENS`、`MAX_OUTPUT_TOKENS` 按真实运行消费者审计标为 unused；两份模板中的 deprecated/unused 键保留为带状态说明的注释赋值。生成的 Draft 2020-12 JSON Schema 精确覆盖 75 个规范字段、类型、默认值、范围、枚举、endpoint、secret、层级与生命周期元数据，并可验证普通非敏感 Settings 序列化。配置文档删除手写 env 默认值和重复范围副本，只保留自动表、行为说明、跨字段关系及 CLI 专属边界。`Settings.diagnostic_dict()` 以显式 secret 元数据输出完整安全诊断：已配置 secret 固定为 `<redacted>`、未配置 secret 为空，非 secret 中嵌入的凭证和签名 query 继续由统一 scrubber 清理；`config_check.py --include-config` 已迁移到该接口。README、SKILL 和 pipeline 文档已加入生成/校验工作流。五轴审查未留 Critical/Required 项。
- 涉及文件：`scripts/settings.py`、`scripts/generate_config_docs.py`、`scripts/config_check.py`、`tests/test_config_docs_sync.py`、`.env.example`、`references/config.example.env`、`references/settings.schema.json`、`references/configuration.md`、`references/pipeline.md`、`README.md`、`SKILL.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe scripts\generate_config_docs.py --check`；`.\.venv\Scripts\python.exe -m pytest tests\test_config_docs_sync.py -q --basetemp <系统临时目录>`；Settings/CLI/run 创建/脱敏/退出码/离线流水线受影响回归；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；手写 env 赋值副本扫描；任务文件高置信 secret 扫描；`git diff --check`。
- 命令结果：TDD 首轮因 `generate_config_docs` 尚不存在在收集期准确 RED；生成器首个增量得到 5 passed / 2 failed，其中一项证明四个提交产物全部漂移，另一项暴露测试把 preset 表与字段表同名行误计为重复，收窄断言后生成产物转绿。加入 Draft 2020-12 schema 自校验和真实 `config_check.py --include-config` 子进程脱敏后，最终专项 9 passed；受影响回归 152 passed。系统临时目录全量 572 passed（156.54 秒）；Ruff 全仓、Mypy（39 个脚本）、虚拟环境 pip check、离线 self-test、生成器 `--check`、手写 env 副本扫描、高置信 secret 扫描和 diff whitespace 检查全部通过，Git 仅提示既有 LF/CRLF 策略。技能包引用的 definition-of-done/testing/security/performance 扩展清单在本机缺失，已按技能正文完整清单、项目安全边界和实际门禁完成等价验证。
- 新增测试：SettingSpec 的 advanced/deprecated/unused 分类与 replacement；generic/App V3 模板字段全集、默认值、secret 空值及唯一 preset 差异；四个历史遗漏键同时进入 schema、模板和 snapshot；字段表每个 Setting 恰好一行；JSON Schema 自身合法并接受规范非敏感 Settings；仓库四个生成产物逐字节同步；模拟新增 Setting 后四产物全部 drift；临时根目录 `--check` 报告漂移且零写入；内部函数和真实 CLI 两层 `--include-config` 对 secret、URL token 及签名 query 的不可恢复脱敏。
- 剩余风险：正式 Windows/Linux CI workflow 要到 TF-039 才建立，本任务提供的是默认 pytest 可收集的 drift test 和独立 `--check` 门禁；字段/default/range/status 已无手写副本，但生成区块之外的行为解释仍需代码审查保持语义一致。unused/deprecated 标签基于当前代码消费者事实，不等同于立即删除承诺，最终实现、废弃或移除决策由 TF-037 完成。生成 schema 描述规范化后的类型化 Settings，不直接验证全部字符串形态的 `.env` 文件；真实加载仍由 Settings loader 严格解析。未调用真实 TikHub、ASR 或 OSS；工作区继续包含前 33 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-035 拆分 `creator_pipeline.py`。

### TF-035 / 2026-07-16

- 状态：completed（计划总进度 35/42）。
- 修改摘要：将约 2760 行的 `creator_pipeline.py` 收敛为 513 行稳定 CLI/兼容 facade。新增 `creator_metadata.py` 负责供应商结构发现、元数据归一化、artifact ID、创作者资料与抽样；新增 `creator_media.py` 负责有界下载、媒体验证、FFmpeg 并发抽取、ASR JSON 转换和 transcript summary，并直接复用 `asr_parsers.parse_asr_response`；新增 `skill_builder.py` 负责确定性 Skill 初稿；新增 `creator_quality.py` 承载 Creator 领域 readiness 适配并统一调用 `quality_engine`、阶段覆盖、证据与治理引擎。旧模块名继续显式导出所有实际消费者使用的函数；仅为 `download_videos`、`extract_audio`、`creator_quality_check` 保留三处依赖注入式薄包装，以维持 facade 上既有 `download_one`、`ffmpeg_version`、`creator_content_readiness` 和 `evaluate_stage_coverage` 替换接缝。四个 owner 模块均不回引 facade，未形成循环依赖；CLI 命令、参数、退出码、错误输出语义、artifact producer 名称和主要产物路径保持不变。README 与 pipeline 脚本地图已同步。五轴审查未留 Critical/Required 项。
- 涉及文件：`scripts/creator_pipeline.py`、`scripts/creator_metadata.py`、`scripts/creator_media.py`、`scripts/skill_builder.py`、`scripts/creator_quality.py`、`tests/test_creator_pipeline_architecture.py`、`README.md`、`references/pipeline.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_creator_pipeline_architecture.py -q --basetemp <系统临时目录>`；creator pipeline 的 metadata/media/cache/workflow/quality/security/performance 相邻回归；`.\.venv\Scripts\python.exe -m pytest tests\test_creator_pipeline_architecture.py tests\test_cli_validation.py tests\test_pipeline_exit_codes.py -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe scripts\generate_config_docs.py --check`；任务文件敏感模式扫描；owner 反向依赖静态扫描；`git diff --check`。
- 命令结果：TDD 首轮架构契约为 3 failed，准确暴露四个 owner 模块不存在且主文件仍含全部实现；迁移后架构契约 4 passed。facade monkeypatch、工作流、元数据、媒体、ASR、缓存、质量、路径和并发相邻回归 236 passed；架构、CLI 参数与退出码契约 103 passed；系统临时目录全量 576 passed（164.43 秒）。Ruff 全仓、Mypy（43 个脚本）、虚拟环境 pip check、离线 self-test、配置生成 drift 检查、任务文件敏感模式扫描、owner 无 facade 回引检查和 diff whitespace 检查全部通过；Git 仅提示工作区既有 LF/CRLF 策略。
- 新增测试：四个职责 owner 可导入且 facade 的无状态导出与 owner 是同一函数；ASR 转换复用 TF-006 parser；owner 模块禁止导入 `creator_pipeline`；主文件函数集合只允许工作流、CLI 与三处兼容包装且不超过 700 行；九个公开子命令及各自参数、顶层 `--env` 的真实子进程 help 契约。
- 剩余风险：`creator_quality.py` 仍有约 1100 行 Creator 领域诊断，这是从 CLI 中移出的独立适配层而非共享引擎副本；后续若继续增长，应按 schema/evidence/refinement 领域再拆，但本任务不改变其已有判定顺序。facade 仍保留 workflow 状态写入、运行摘要和面向人的详细 quality CLI 输出，因为它们属于稳定编排/呈现契约；TF-037/TF-038 再处理死兼容面和 legacy 诊断。未调用真实 TikHub、ASR、OSS 或在线模型；外部 provider 行为仍待授权 smoke test。工作区继续包含前 34 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-036 拆分 `prepare_host_refinement.py`。

### TF-036 / 2026-07-16

- 状态：completed（计划总进度 36/42）。
- 修改摘要：将约 2600 行的 `prepare_host_refinement.py` 收敛为 353 行稳定 CLI、兼容导出和产物写入编排。新增 102 行 `refinement_common.py` 统一 JSON/文本读取、共享评分、惰性 transcript fallback 和不可信 Markdown 数据边界；530 行 `refinement_coverage.py` 负责 evidence index 解析及证据覆盖、缺口、短视频和时间线派生；546 行 `refinement_signals.py` 直接复用不可变 `corpus.CorpusSnapshot`、taxonomy、topic discovery、entity review 和 text analysis，生成 corpus index、topic candidates、逐条信号和 signal matrix；432 行 `refinement_schemas.py` 集中严格 evaluator/persona schema 与 JSON 空白模板；780 行 `refinement_templates.py` 只渲染 Markdown 报告、review 模板和宿主 brief，不执行文件写入。facade 对原有公开及私有 helper 均显式重导出，原 `main()` 的目录创建、生成顺序、路径、schema/template 内容、artifact producer/version 和 stdout 路径顺序保持。`quality_engine.compute_current_derivations()` 与 `evidence_model.evaluate_run_evidence_integrity()` 不再反向导入 CLI facade，改为直接依赖 coverage/signal owner；运行库除可复制 CLI 字符串外已无 `prepare_host_refinement` 导入。owner 依赖图单向且无重复实现或循环。README 与 pipeline 脚本地图已同步。五轴审查未留 Critical/Required 项；Checkpoint 6 的两个超大脚本薄编排条件现已满足。
- 涉及文件：`scripts/prepare_host_refinement.py`、`scripts/refinement_common.py`、`scripts/refinement_coverage.py`、`scripts/refinement_signals.py`、`scripts/refinement_schemas.py`、`scripts/refinement_templates.py`、`scripts/quality_engine.py`、`scripts/evidence_model.py`、`tests/test_prepare_host_refinement_architecture.py`、`README.md`、`references/pipeline.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：`.\.venv\Scripts\python.exe -m pytest tests\test_prepare_host_refinement_architecture.py -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m pytest tests\research tests\quality tests\integration -q --basetemp <系统临时目录>`；corpus 性能、提示注入、ID、日志相邻回归；schema 与 evidence 重建专项；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；`.\.venv\Scripts\python.exe scripts\generate_config_docs.py --check`；任务文件敏感模式扫描；owner 依赖/重复实现静态扫描；运行库 facade 反向依赖扫描；`git diff --check`。
- 命令结果：TDD 首轮架构契约为 3 failed / 1 passed，准确暴露 owner 模块缺失和主文件仍含全部职责；schema owner、quality engine facade 反向依赖、evidence rebuild facade 反向依赖又各自先产生 1 个准确失败后转绿。最终架构契约 6 passed；研究、质量、集成、corpus 性能、提示注入、ID 与结构化日志合并回归 185 passed；schema/架构专项 18 passed，evidence/架构专项 17 passed。系统临时目录全量 582 passed（164.78 秒）。Ruff 全仓、Mypy（48 个脚本）、虚拟环境 pip check、离线 self-test、配置生成 drift、敏感模式、owner 无循环/无重复实现、运行库无 facade 反向导入和 diff whitespace 检查全部通过；Git 仅提示工作区既有 LF/CRLF 策略。
- 新增测试：六个职责 owner 可导入，facade 导出与 owner 是同一实现；signals 显式复用 TF-031 corpus、Phase 4 taxonomy/topic/text-analysis；owner 禁止回引 CLI facade；主文件仅允许 `main`、不含 500 字符以上模板且不超过 500 行；四个公开 CLI 参数真实 help 契约；quality/evidence 当前状态重建必须直接依赖 signal/coverage owner，不得借道 CLI。
- 剩余风险：`refinement_templates.py` 仍有 780 行，但其内容是集中、纯渲染的 Markdown 模板与 brief，不包含 schema、I/O 或质量派生；后续模板继续增长时可迁入独立 assets，但当前拆分后所有代码文件低于 1000 行。`refinement_common.transcript_excerpt()` 为直接调用 `build_brief` 且不传 snapshot 的兼容路径保留惰性文件读取；真实 prepare 主链始终传同一不可变 snapshot，逐 transcript 一次读取契约仍由性能测试覆盖。未调用真实 TikHub、ASR、OSS 或在线模型；外部服务仍待授权 smoke test。工作区继续包含前 35 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-037 处理遗留研究路径、死代码和死配置。

### TF-037 / 2026-07-16

- 状态：completed（计划总进度 37/42）。
- 修改摘要：将 `scripts/research/quality_check.py` 收敛为 deprecated 薄兼容入口，位置参数改为当前 run 目录，stderr 给出替代命令并统一转发 `creator_pipeline.py quality-check`，不再维护另一套 `knowledge/research` 指标算法；`merge_research.py` 只解析当前 run 或直接 `research/` 目录。通用中文创作者提示词从误导性的 `references/prompts/celebrity/` 迁移至 `references/prompts/creator/`，SKILL、安全测试和 pipeline 迁移说明同步。删除无调用方的 `collect_transcript_corpus`、无生产者的 `style_research.json` 读取/运行摘要字段，初稿在没有该旧 JSON 时保持原默认文本。Settings 删除从未生效的 `ALI_ASR_APP_KEY`、`AUTO_RESUME`、`MAX_INPUT_TOKENS`、`MAX_OUTPUT_TOKENS`，移除 unused 生命周期和空 research 分组，schema 升至 v2；显式 mapping、`.env` 或 CLI override 使用退役键时快速失败并给出 ASR 凭证、显式恢复或宿主预算迁移说明，整份进程环境仍忽略同名未知键以避免跨应用冲突。同步重生成两份 env 模板、配置表和 JSON Schema，并删除 config-check 的伪 token-budget 检查。静态 AST 契约证明当前 `requirements.txt` 的 `dashscope`、`jieba`、`jsonschema`、`oss2`、`requests` 均有运行代码消费者，因此未删除有效依赖；`pypinyin` 已在此前任务移除。五轴复核未留 Critical/Required 项。
- 涉及文件：`scripts/research/quality_check.py`、`scripts/research/merge_research.py`、`scripts/settings.py`、`scripts/generate_config_docs.py`、`scripts/config_check.py`、`scripts/skill_builder.py`、`scripts/creator_pipeline.py`、`references/prompts/creator/**`、`references/configuration.md`、`references/pipeline.md`、`references/settings.schema.json`、两份 env 模板、`SKILL.md`、`tests/test_legacy_cleanup.py` 及相邻配置、CLI、集成和安全测试。
- 验收命令：TDD RED/定向测试；`rg` 遗留路径与退役设置扫描；运行依赖 AST 消费者契约；`..venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`..venv\Scripts\python.exe -m ruff check .`；`..venv\Scripts\python.exe -m mypy scripts`；`..venv\Scripts\python.exe -m pip check`；`..venv\Scripts\python.exe scripts\generate_config_docs.py --check`；`..venv\Scripts\python.exe scripts\self_test.py`；生产文件高置信 secret 扫描；`git diff --check`。
- 命令结果：首轮遗留契约准确得到 4 failed / 1 passed，分别复现死设置仍在目录、current run 无法被 merge 识别、孤立 transcript/style 路径仍存在和提示词旧目录歧义；依赖消费者契约首轮即通过。迁移后配置/schema 专项 50 passed，最终相关 CLI/提示词/离线链路 34 passed；最终系统临时目录全量 590 passed（165.23 秒）。Ruff 全仓、Mypy（48 个脚本）、虚拟环境 pip check、离线 self-test、配置生成 drift、遗留路径、生产文件 secret 和 diff whitespace 检查全部通过；Git 仅提示工作区既有 LF/CRLF 策略。
- 新增测试：退役设置不再属于 CONFIG_KEYS、Settings schema v2、所有 active/deprecated 生命周期闭合且 deprecated replacement 存在；四个退役键的 mapping 迁移错误，以及 `.env`/CLI override 拒绝但进程环境同名键不越权；merge 接受 current run/research 并拒绝 `knowledge/research`；builder 不再导出孤立函数或读取 style JSON；creator 提示词目录唯一；每个运行依赖都可由 scripts 的真实 AST import 证明用途；旧 quality CLI 的严格退出码、report-only、deprecated stderr 和统一 current-run 语义。
- 剩余风险：本任务只处理已确认的遗留研究/配置面；所有公开 CLI 子命令矩阵、旧 run schema/manifest 诊断和 `inspect-run` 仍由 TF-038 完成。Settings v2 对四个从未生效字段是有意 breaking cleanup，迁移已进入配置和 pipeline 文档，但 changelog/version 发布策略待 TF-041。未调用真实 TikHub、DashScope、compatible ASR、OSS 或在线模型；外部服务仍待明确授权的 smoke test。工作区继续包含前 36 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-038 增加 CLI 兼容测试和旧运行目录诊断。

### TF-038 / 2026-07-16

- 状态：completed（计划总进度 38/42）。
- 修改摘要：新增只读 `scripts/run_diagnostics.py`，以现有 `input.json` 作为唯一 run 描述文件，并为新 run 固定写入 `run_format=thousand-faces.creator-run`、`schema_version=1`；同时有界读取并校验 `config.snapshot.json`、`workflow.plan.json` 与 `metadata/provenance.json` 的根 schema 字段，输出 `current_verified`、`current_incomplete`、`legacy_unverified`、`unsupported`、`invalid`、`not_found` 六类稳定状态、缺失/无效清单和建议动作。`creator_pipeline.py` 新增可测试的公共 parser factory 与第十个 `inspect-run` 子命令；JSON/文本输出均区分格式验证和持久化质量验证，只有当前格式、当前版本质量报告且报告内绑定相同 run format 时才可能诊断为 ready。最小 legacy fixture 主动携带伪造的历史 `ready_for_use=true` 报告，诊断固定标记 `ignored_unverified`，质量检查返回 run-format blocker、不得覆盖旧文件。构建 Skill、run summary、resume、host refinement、retention、OSS upload/cleanup 七个写入口在任何写入或远端调用前共用 `RUN_FORMAT_UNVERIFIED` 守卫；Settings 错误仍保持先于 run 格式错误的原兼容优先级。README、SKILL 与 pipeline 文档加入 v1 格式、只读诊断、非原地迁移和新建 run 替代流程。五轴审查未留 Critical/Required 项。
- 涉及文件：`scripts/run_diagnostics.py`、`scripts/build_creator_skill.py`、`scripts/creator_pipeline.py`、`scripts/creator_quality.py`、`scripts/quality_engine.py`、`scripts/resume_creator_run.py`、`scripts/prepare_host_refinement.py`、`scripts/retention.py`、`scripts/provider_adapters.py`、`tests/cli/test_creator_pipeline_cli.py`、`tests/integration/test_legacy_run.py`、`tests/fixtures/runs/legacy_v0/**`、fixture 清单/契约、既有 current-run 测试工厂、`README.md`、`SKILL.md`、`references/pipeline.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：TDD RED/定向测试；`.\.venv\Scripts\python.exe -m pytest tests\cli tests\integration\test_legacy_run.py -q --basetemp <系统临时目录>`；CLI/legacy/fixture/架构/provider/OSS 相邻回归；质量、研究、性能、安全、Settings 和阶段覆盖回归；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；`.\.venv\Scripts\python.exe scripts\generate_config_docs.py --check`；`.\.venv\Scripts\python.exe scripts\self_test.py`；任务文件高置信 secret 扫描；`git diff --check`。
- 命令结果：TDD 首轮为 36 failed / 11 passed，准确暴露公共 parser、`inspect-run`、run format 字段和统一写守卫尚不存在。首轮实现后的核心/相邻回归 102 passed / 2 failed，两个失败均为既有质量测试工厂未声明 v1；升级测试工厂后核心 56 passed，legacy fixture 与诊断 25 passed，CLI/legacy/fixture/架构/provider/OSS 106 passed。第一次系统临时目录全量得到 614 passed / 14 failed，13 项为手工 current-run 工厂缺少 v1 根清单，1 项揭示 resume 配置错误优先级漂移；补齐 v1 工厂并恢复错误优先级后，相邻回归 110 passed。计划指定命令最终 38 passed，系统临时目录最终全量 628 passed（177.79 秒）。Ruff 全仓、Mypy（49 个脚本）、虚拟环境 pip check、离线 self-test、配置生成 drift、任务文件高置信 secret 和 diff whitespace 检查全部通过；Git 仅提示工作区既有 LF/CRLF 策略。
- 新增测试：十个 `creator_pipeline` 子命令和顶层 `--env` 的真实 `--help`，每个子命令合法参数、缺少必需参数和非法参数的 parser 退出码；新 run 格式字段与无质量报告时的保守诊断；缺失 workflow、损坏 config、未来 schema 和不存在目录的稳定非零诊断；legacy 缺清单、伪造旧 ready、只读 quality report 和整树字节级零修改；七个写入口对 legacy 的稳定错误、迁移提示和零副作用；fixture 清单完整性继续保持无凭证、无网络。
- 剩余风险：本任务未调用真实 TikHub、DashScope、compatible ASR、OSS 或在线模型；外部 provider 仍待明确授权 smoke test。v1 格式验证只证明根描述和必需清单具备受支持的结构版本，不替代治理、freshness、schema、evidence 和内容质量门禁；因此 `format_verified=true` 本身永远不等于 ready。旧 run 不提供自动或原地迁移是有意的安全边界，继续使用必须从原始来源创建新 run；正式 changelog/version 发布策略由 TF-041 处理。工作区继续包含前 37 项任务的混合暂存/未暂存改动，用户未授权 commit/push。
- 下一建议任务：TF-039 建立 Windows/Linux 跨平台 CI。

### TF-039 / 2026-07-16

- 状态：completed（GitHub 托管 CI 与 `main` required checks 已外部验收，计划总进度 41/42）。
- 修改摘要：新增 `.github/workflows/ci.yml`，在 `main` push、Pull Request 和手动触发时，以 `ubuntu-latest` / `windows-latest`、仓库声明的 Python 3.11 运行依赖安装与 `pip check`、Ruff、Mypy、配置/schema drift、638 项 pytest 覆盖率测试和离线 self-test；matrix 不 fail-fast，job 设 15 分钟上限，并用 concurrency 取消同分支陈旧运行。workflow 只授予 `contents: read`，checkout 禁止持久化凭证，不引用 secrets 或 `.env`，三个官方 action 均固定到完整 commit SHA；pip 缓存绑定两份 requirements。无论测试成败仅上传 `reports/` 中 JUnit、Coverage XML/JSON 摘要，保留 14 天，不上传 run、fixture 或 transcript 目录。README 增加 CI badge、本地等价命令、Windows/Linux 说明和 required checks 配置要求；新增 workflow 合同测试，锁定触发器、版本矩阵、权限、不可变 action、全部门禁、无失败抑制、无 provider 凭证/真实网络命令和有界报告路径。
- 跨平台修复：真实 Ubuntu 3.11 干净副本先暴露 `content_safety.py` 的 Windows `ctypes/msvcrt` API 在 Linux Mypy 下不可检查；改为 Mypy 官方支持的顶层 `sys.platform == "win32"` 条件定义，并新增 `linux`/`win32` 双目标 Mypy 回归。Linux 又复现 DashScope 首次 request timeout 因总 deadline 正确收缩到略小于 5 秒，修正依赖墙钟分辨率的精确等值测试为合法 `(0, 5]` 范围。最后稳定复现 WSL 墙钟微小回拨令 `completed_at < started_at`、失败处理无法写 `run_summary.json`；日志器现以 `max(墙钟结束, 开始 UTC + 单调耗时)` 生成有序结束时间，并增加墙钟回拨回归及离线失败场景诊断信息。五轴审查未留 Critical/Required 项。
- 涉及文件：`.github/workflows/ci.yml`、`README.md`、`scripts/content_safety.py`、`scripts/logging_utils.py`、`tests/test_ci_workflow.py`、`tests/test_cross_platform_typing.py`、`tests/providers/test_asr_polling.py`、`tests/test_structured_logging.py`、`tests/integration/test_offline_pipeline.py`、`plan/TODO.md`。
- 验收命令：TDD RED/GREEN 的 CI 合同、双平台 Mypy 与墙钟回拨专项；官方 `actionlint 1.7.12`（发布包 SHA-256 校验后临时执行）；Windows `pip check`、Ruff、Mypy、配置 drift、全量覆盖 pytest、self-test；WSL Ubuntu 24.04 临时干净副本 + 临时 Python 3.11.15 执行同一套门禁；20 次 Linux 概率回归；JUnit/Coverage XML/JSON 生成与解析；任务文件敏感模式扫描；`git diff --check`。
- 命令结果：CI 合同首轮因 workflow/README 不存在得到 1 failed / 6 errors，最终合同与双平台类型专项 9 passed；`actionlint 1.7.12` 零错误，下载包 SHA-256 为 `6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9`。Windows 最终全量 638 passed（325.43 秒）、覆盖率 79%，self-test 通过；Linux 全新 Python 3.11.15 环境先后准确暴露并修复 2 个 Mypy 错误、1 个微秒 timeout 断言和 1 个墙钟回拨失败，最终 20/20 概率回归、638 passed（216.66 秒）、覆盖率 79%，self-test 通过，整个无缓存临时验证 382 秒。两平台 `pip check`、Ruff、Mypy（49 个脚本）、配置/schema drift 均通过。JUnit、Coverage XML/JSON 均成功生成并由 XML/Python JSON 解析器验证；diff whitespace 仅有工作区既有 LF/CRLF 策略提示。
- 新增测试：CI 的 main/PR/manual 触发、并发取消、15 分钟 timeout、Windows/Linux + Python 3.11 matrix；最小权限、checkout 凭证禁存、三个官方 action 完整 SHA/版本注释；所有门禁无 `continue-on-error` 等抑制；无 secrets/`.env`/provider live command；仅上传有界 reports；README 本地等价命令；从任意当前 OS 强制 Mypy 检查 `linux` 与 `win32`；墙钟回拨而单调钟前进时步骤结束时间仍有序；离线无 transcript 场景缺汇总时输出可诊断的脱敏子进程证据。
- 剩余风险：workflow 仍是未提交文件，用户尚未授权 commit/push，因此没有 GitHub 托管 runner 的实际 run URL/日志，也不能确认或配置 `main` 分支保护中的两个 required status checks；TF-039 的三条 PLAN 验收标准据此继续保持未勾选。TF-040 已在不依赖远端权限的范围内独立完成本地实现与双平台干净环境验收，但这不替代 TF-039 的托管 CI 证据。若用户授权提交并推送，需要等待两个 matrix job 成功、检查日志无 secret，并由有仓库管理权限的人将两个 `quality` check 设为 required 后，才能把 TF-039 更新为 completed；未调用真实 TikHub、ASR、OSS 或在线模型，工作区继续包含前 38 项任务的混合暂存/未暂存改动，本轮未 commit/push。
- 远端再审计（2026-07-16）：只读核验确认 origin/main 与本地 HEAD 仍同为初始提交 `cd0adc88741c4fcfe1b251a310cfa0f5c86e5ee9`，GitHub Actions API 返回 `0` 个 workflow、`0` 次 run，branch protection API 明确返回 `Branch not protected`，rules API 为空。当前登录主体对仓库具有 admin/push 能力，但该能力不构成用户对外部写入的授权。TF-041 接入发布元数据门禁后，当前 CI/跨平台/版本合同 19 passed，配置 drift、JSON Schema 和 CI 负向合同 29 passed；新增发布校验在 WSL Ubuntu 的 Python 3.12.3 下读取同一工作区并验证 20 个版本源通过。当前 PATH 没有 actionlint，本次再审计未声称重复执行；TF-039/040 已记录的 v1.7.12 官方校验结果仍是最近一次该工具证据。
- 下一动作：获得用户对当前整批工作区 commit/push 的明确授权后，先审计准确提交范围并触发 GitHub Actions；两个 matrix job 通过且日志无 secret 后，再配置并读取验证 `main` required checks。未满足这些外部证据前不得勾选 TF-039，也不得开始依赖它的 TF-042。
- 托管闭环（2026-07-16）：用户明确授权审计、提交、推送和配置分支保护。TF-001～TF-041 聚合提交为 `61b53e076c0ec77df13ab3e64bfb7b8a3e0f49fe`；首轮托管 CI 准确暴露 Windows 临时目录别名导致的绝对/相对路径不一致，以及全局 `runs/` / `logs/` 忽略规则漏提交 legacy fixture 两个真实问题。修复提交 `60d8dbed86e1608b93515f87fc3c860d255d0eb3` 统一解析 run 根与产物路径并增加别名回归，`26dbbf6e6fab7db709485da1760054dc5492fa9f` 精确放行并跟踪 4 个脱敏 legacy fixture，同时新增 manifest 文件必须由 Git 跟踪的契约。
- 托管结果：最终 GitHub Actions 运行 `29464470089`（`https://github.com/lem1272536013/thousand-faces/actions/runs/29464470089`）在提交 `26dbbf6e6fab7db709485da1760054dc5492fa9f` 上整体成功。`quality (ubuntu-latest, Python 3.11)` 为 success，662 passed / 1 warning / 271.53 秒；`quality (windows-latest, Python 3.11)` 为 success，662 passed / 420.98 秒。两个完整 job 日志经高置信凭证模式复核均为 0 命中；workflow 不注入 provider secrets，不读取 `.env`，不执行真实供应商网络命令。
- 分支保护：`main` 已启用严格 required status checks，精确绑定 GitHub Actions App ID `15368` 的 `quality (ubuntu-latest, Python 3.11)` 与 `quality (windows-latest, Python 3.11)`；`strict=true`，force push 与 branch deletion 均禁用。为完成依赖 TF-039 的 TF-042 审计文档直推，管理员强制执行暂保持关闭；最终审计提交绿后再启用 `enforce_admins` 并回读验证。未执行真实 TikHub、ASR 或 OSS smoke，按 TF-042 明示为需额外授权项，不影响离线 CI 完成。

### TF-040 / 2026-07-16

- 状态：completed（计划总进度 39/42；TF-039 仍为独立的外部待验收项）。
- 修改摘要：README 删除“把仓库交给 AI”的隐含前置条件，新增 Python/venv 安装、无凭证 self-test、保留产物的 fixture demo、严格真实运行、宿主精修和项目质量门禁最短路径；加入可信控制面/不可信数据面的 Mermaid 架构图、pipeline/draft/ready/commercial/freshness/legacy 状态表、`run_summary.json` 诊断入口、TikHub 参数、ffmpeg/ffprobe、429/RATE_LIMIT、ASR endpoint、部分 transcript 与 STALE_ARTIFACT 排障表，以及提示注入、SSRF、凭证、授权、OSS 生命周期和本地删除安全表。SKILL、pipeline、host refinement 统一使用真实 CLI，明确修改 evidence/transcript/selected 后只有“重新 prepare → 再次 quality-check”的规范闭环，不再依赖未记录的 merge/schema/manifest 命令。新增标准库实现的 `verify_docs_commands.py`：把 PowerShell/Bash fence 当作不可信数据，只允许白名单脚本/模块，以真实 `--help` 验证脚本、子命令、长短参数；默认在系统临时目录执行固定 fixture demo、只读 run 诊断、host prepare、严格 quality-check、配置漂移检查和 self-test，绝不读取 `.env` 或调用供应商。CI 在 pytest 前新增该门禁。五轴审查发现并修复 Bash fence 漏扫及 `python -m` 参数未验证两个 Required 问题，最终无 Critical/Required 项。
- 涉及文件：`README.md`、`SKILL.md`、`references/pipeline.md`、`references/host_refinement.md`、`scripts/verify_docs_commands.py`、`tests/test_documentation_contract.py`、`.github/workflows/ci.yml`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：文档契约 TDD RED/GREEN；`python scripts/verify_docs_commands.py`；全新 Windows/Ubuntu 源码副本与 Python 3.11 venv 重新安装 `requirements-dev.txt` 后执行 `pip check` 和文档校验；`python -m pip check`、`python -m ruff check .`、`python -m mypy scripts`、`python scripts/generate_config_docs.py --check`、`python -m pytest --cov=scripts --cov-report=term-missing -q --basetemp <系统临时目录>`、`python scripts/self_test.py`；官方 actionlint 发布校验和核验后检查 workflow；任务文件 credential-shaped pattern 与 `git diff --check`。
- 命令结果：初始文档契约准确得到 5 failed；补齐文档和校验器后 5 passed，文档/CI/配置相邻回归 25 passed。五轴审查新增的 Bash fence 反例先 1 failed 后 2 passed；未知 pipeline 子命令和 pytest 参数反例先 2 failed 后 3 passed。最终本地校验器识别 53 条 Python 命令，实际离线工作流通过；Windows Python 3.11.0 全新源码/venv 副本 104.5 秒通过，Ubuntu 24.04 + Python 3.11.15 全新副本 76.2 秒通过，两边均为 `No broken requirements found`。Windows 全量 650 passed（343.79 秒），覆盖率 79%；Ruff 全仓、Mypy 50 个脚本、配置 drift 和独立 self-test 全部通过。actionlint v1.7.12 零错误，官方资产 SHA-256 为 `6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9`。敏感模式无命中，diff 无 whitespace error，临时 Windows/Linux 目录均已核验清理。
- 新增测试：README 独立 onboarding、架构/状态/诊断、六类常见故障和六类安全边界；四份操作文档共享 prepare、quality 和 verifier；离线 verifier 是 CI 阻断门禁；PowerShell 与 Bash 多行命令解析；非 Python fence 内容不执行；非白名单脚本、拼错 pipeline 子命令和未知模块参数安全失败；当前 CLI 参数对照；项目 Settings 从校验子进程环境彻底移除。
- 剩余风险：文档校验器有意不执行真实 TikHub、ASR、OSS、真实 `.env` 或删除 `--apply` 命令，只验证它们的 CLI 形态；真实供应商行为仍需用户明确授权的 smoke test。Windows 全新安装出现 jieba/crcmod/部分阿里云依赖使用旧式 `setup.py install` 的上游弃用提示，但安装、依赖健康和运行均成功；当前不是功能 blocker，可在后续依赖发布支持 wheel/PEP 517 时再评估。TF-039 的 GitHub 托管 runner 和 required checks 仍待 commit/push 授权，与本任务完成状态分开记录；本轮未 commit/push。
- 下一建议任务：TF-041 增加维护、漏洞披露和版本发布文件；其本地交付物可继续实现，最终发布验收仍须保留 TF-039 外部待办。

### TF-041 / 2026-07-16

- 状态：completed（计划总进度 40/42；TF-039 的 GitHub 托管 CI 与 required checks 仍为独立外部待验收项）。
- 修改摘要：新增 `SECURITY.md`，按远端 API 实际返回的 `private vulnerability reporting=false` 采用“公开 issue 只请求私密交接、不得附漏洞细节，维护者随后创建 draft security advisory”的明确流程，并规定 API key、签名 URL、完整 transcript、个人信息和真实运行产物的最小披露、撤销/轮换及协调公开要求。新增 `CONTRIBUTING.md`，固定新增/改变行为先写失败测试、一个 PR 一个 TF、synthetic/redacted fixture、`example.invalid`、无真实网络/`.env`、schema/preset 变更六步清单和完整本地门禁。新增 `references/versioning.md`，区分项目/CLI、run format、Settings snapshot、persona schema 族、taxonomy preset、内部持久化 schema 与 producer/algorithm 七类版本轴；当前 `0.x` 的不兼容变化至少升 MINOR，严格 persona schema 按旧 reader 的实例兼容判断，taxonomy 按名称与精确版本解析且不能静默替换。新增 Keep a Changelog 结构的 `CHANGELOG.md`，把首个候选 `0.1.0` 的 Added/Changed/Deprecated/Removed/Fixed/Security、breaking changes、Settings v2 和 `legacy_unverified` 非原地迁移策略写入 `[Unreleased]`。
- 版本门禁：新增纯标准库 `scripts/verify_release_metadata.py`，通过 `tomllib` 和 Python AST 只读 `pyproject.toml` 以及所有模块级 `*_SCHEMA_VERSION` / `*_PRESET_VERSION` 字面量，不导入运行代码、不读取 `.env`、不访问 Git 或网络。当前自动发现项目/CLI 版本加 19 个 schema/preset 版本源，逐项比对 changelog 当前清单；五个对外版本轴还必须与版本策略基线一致。校验同时锁定安全交接、敏感日志、测试义务、fixture 脱敏、任务粒度、首发 breaking/legacy 说明和 SemVer 语法。`verify_docs_commands.py` 已纳入四份维护文档并允许发布校验脚本；CI 在 pytest 前新增发布元数据阻断门禁，README 增加本地等价命令与维护入口。
- 涉及文件：`SECURITY.md`、`CONTRIBUTING.md`、`CHANGELOG.md`、`references/versioning.md`、`scripts/verify_release_metadata.py`、`tests/test_release_metadata.py`、`scripts/verify_docs_commands.py`、`tests/test_ci_workflow.py`、`.github/workflows/ci.yml`、`README.md`、`plan/PLAN.md`、`plan/TODO.md`。
- 验收命令：GitHub 仓库可见性与 private vulnerability reporting 状态只读 API 核验；TDD RED/GREEN 的发布元数据、文档与 CI 契约；`.\.venv\Scripts\python.exe scripts\verify_release_metadata.py`；`.\.venv\Scripts\python.exe scripts\verify_docs_commands.py`；`.\.venv\Scripts\python.exe scripts\generate_config_docs.py --check`；`.\.venv\Scripts\python.exe -m pytest tests\test_release_metadata.py tests\test_ci_workflow.py tests\test_documentation_contract.py -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m pytest -q --basetemp <系统临时目录>`；`.\.venv\Scripts\python.exe -m ruff check .`；`.\.venv\Scripts\python.exe -m mypy scripts`；`.\.venv\Scripts\python.exe -m pip check`；任务文件高置信 secret 扫描；marker 唯一性与校验器网络/环境依赖扫描；`git diff --check`。
- 命令结果：TDD 首轮因发布校验模块不存在在收集期准确 RED；首个文档/校验实现得到 7 passed / 1 failed，失败准确暴露文档白名单和 CI 尚未接入，接入后维护/CI/文档契约 27 passed。五轴审查又用两个先红测试发现并修复候选版本 `0.1.0` 被写死、反序 marker 抛 `ValueError` 两个 Required 问题，最终发布专项 10 passed，合并维护/CI/文档契约 29 passed。发布校验通过并发现 20 个版本源；完整文档校验静态检查 67 条 Python 命令且实际无凭证离线工作流通过；系统临时目录全量 660 passed（240.53 秒）。Ruff 全仓、Mypy（51 个脚本）、虚拟环境 pip check、配置生成 drift、高置信 secret、marker/依赖扫描和 diff whitespace 检查全部通过；Git 仅提示工作区既有 LF/CRLF 策略。
- 新增测试：版本收集覆盖五个公开轴和内部 schema；源码/changelog/versioning 全清单一致；未记录的 run schema 版本漂移失败；候选项目版本未来提升不依赖硬编码；反序 marker 稳定报错而不崩溃；首发 breaking/legacy/Settings v2 说明；安全无细节公开交接与敏感日志规则；贡献测试/fixture/PR 粒度义务；独立版本轴、严格 schema 与 taxonomy 精确解析规则；发布校验进入文档白名单并在 CI pytest 前运行。
- 剩余风险：仓库当前未启用 GitHub Private Vulnerability Reporting，本任务没有用户授权去修改远端安全设置，因此使用官方允许的“无细节公开联络后转私密 advisory”流程；将来启用时必须同步修改 SECURITY 标记与测试。`0.1.0` 仍是 `[Unreleased]` 候选，本任务没有创建 tag、GitHub Release、commit 或 push。TF-039 的 hosted runner 成功记录与 `main` required checks 仍待明确的提交/推送及仓库管理授权；本地 CI 文件和发布门禁通过不能替代该外部证据。未调用真实 TikHub、ASR、OSS 或在线模型；工作区继续包含前 40 项任务的混合暂存/未暂存改动，根目录既有未跟踪 `.coverage` 留待 TF-042 归属审计，未擅自删除。
- 下一建议任务：先在获得 commit/push 与分支保护授权后闭合 TF-039；随后执行 TF-042 最终审计并生成 `plan/RELEASE_AUDIT.md`。

### TF-042 / 2026-07-16

- 状态：completed（计划总进度 42/42；离线发布候选验证通过）。
- 审计摘要：生成 `plan/RELEASE_AUDIT.md`，按 PLAN 第 9 节 34 项 Definition of Done 逐项建立“要求、结果、直接测试/命令证据”映射。审计没有用全量测试绿替代需求覆盖，额外核验失败退出码、安全拒绝、质量 blocker、legacy 只读诊断、跨领域证据、Git 跟踪范围、敏感模式、运行产物、生产代码未解决标记、托管日志和分支保护。首轮托管 CI 发现的 Windows 路径别名与 Linux legacy fixture 漏提交均已通过根因修复和回归测试关闭，当前无 P0/P1、Critical 或 Required 遗留项。
- 最终本地门禁：Ruff 全仓 PASS；Mypy 51 个源文件 PASS；`pip check` 无损坏依赖；配置/schema drift PASS；发布元数据 20 个版本源 PASS；文档 67 条静态命令及完整离线工作流 PASS；系统临时目录全量 662 passed（410.60 秒），Coverage 79.16% / 49 文件；离线 self-test PASS。退出码、CLI、stage coverage、legacy、安全、readiness、evidence 和 copyright 负向审计 259 passed（49.15 秒）。安全示例配置的严格 live 检查按预期返回非零，证明缺真实 TikHub/ASR endpoint/OSS 配置时不会误报 live-ready。
- 托管与保护：GitHub Actions 运行 `29464470089` 在代码基线 `26dbbf6e6fab7db709485da1760054dc5492fa9f` 上成功；Ubuntu Python 3.11 为 662 passed / 1 warning / 271.53 秒，Windows Python 3.11 为 662 passed / 420.98 秒。两个完整日志的高置信凭证扫描均为 0 命中。`main` 已启用 `strict=true` 的两个精确 required checks，均绑定 GitHub Actions App ID `15368`；force push 与 branch deletion 禁用。管理员强制执行在最终审计文档提交和双平台复验后启用并回读。
- 工作区审计：生产代码 `TODO/FIXME/HACK/XXX` 为 0；精确检查没有真实 `.env`、`.coverage`、非 fixture `runs/`、`logs/` 或 `output/` 被跟踪；4 个 legacy run 文件是清单声明、synthetic-only 的测试资源并有 Git 跟踪契约。3 个凭证形状命中全部位于显式 fake/test 数据，相关脱敏测试和全量 suite 通过。`.env` 只作为本地忽略文件存在，未读取、输出或提交。
- 未验证/需授权：未调用真实 TikHub、DashScope/兼容 ASR 或 OSS；未读取真实 `.env`；未创建 tag 或 GitHub Release；未验证真实账号内容的事实准确性、版权授权和商业可交付性；未启用 GitHub Private Vulnerability Reporting。这些边界已在发布审计中逐项列明，符合 TF-042“未授权时明确标记且不阻塞离线完成”的要求。
- 剩余风险：真实供应商响应和限流仍可能漂移；Windows 原子替换曾在本机文件占用条件下瞬时出现 `WinError 5`，但本轮本地及托管 Windows 全量均通过；上游 `jieba`/`crcmod`/部分阿里云包仍有弃用或构建提示；中文主题、实体和内容重叠含启发式判断，高风险商业使用必须人工复核。领域 owner 模块仍有进一步拆分空间，定为 P2 可维护性优化，不构成发布 blocker。
- 交付收尾：提交本次 `plan/PLAN.md`、`plan/TODO.md`、`plan/RELEASE_AUDIT.md` 后等待最终 required checks 成功，再启用 `enforce_admins`、回读保护规则并核对本地/远端 SHA；未经新授权不扩大到真实 provider smoke 或正式 Release。

## 最终验收命令

```powershell
python -m ruff check .
python -m mypy scripts
python -m pytest --cov=scripts --cov-report=term-missing -q
python scripts/self_test.py
python scripts/config_check.py --env .env --strict
git diff --check
git status --short --branch
```

真实 TikHub/ASR/OSS smoke test 仅在用户明确授权后执行；未执行时必须在 `plan/RELEASE_AUDIT.md` 中标为外部未验证项，不能伪造结果。
