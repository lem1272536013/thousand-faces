# 宿主 Agent 精修流程

## 目标

确定性流水线只负责采集、下载、ASR、初稿和可恢复产物。真正可用的 Creator Skill 必须经过宿主 agent 的研究与改写。不要把 `ready_for_use=true` 理解为“文件存在”，而要理解为“已经能稳定指导选题、脚本、改写和风格批评”。

## 必做步骤

### 1. 准备研究包

在流水线完成后运行：

```powershell
python scripts/prepare_host_refinement.py `
  --run-dir .\runs\<project-name>\<run-id>
```

脚本会生成：

```text
research/host_refinement/brief.md
research/host_refinement/corpus_index.json
research/host_refinement/transcript_signal_matrix.md
research/host_refinement/transcript_signals.json
research/host_refinement/transcript_signals.md
research/reviews/evidence_coverage.json
research/reviews/evidence_coverage.md
research/reviews/coverage_gaps.json
research/reviews/coverage_gaps.md
research/reviews/short_form_coverage.json
research/reviews/short_form_coverage.md
research/reviews/timeline_shift.json
research/reviews/timeline_shift.md
research/reviews/asr_entity_review.json
research/reviews/asr_entity_review.md
research/reviews/usage_probe.md
research/reviews/evaluation_suite.md
research/reviews/evaluation_suite.schema.json
research/reviews/evaluation_suite.json
research/reviews/reverse_identification.md
research/reviews/reverse_identification.schema.json
research/reviews/reverse_identification.json
research/reviews/reviewer_findings.md
research/reviews/refinement_audit.md
skill/references/persona_model.schema.json
skill/references/persona_model.json
research/reviews/persona_model_diagnostics.json
```

这些文件的分工：

- `brief.md`：研究入口，包含创作者档案、样本范围、互动最高视频、全量标题索引、代表性转写片段、当前 skill 文件体量和待回答问题。
- `corpus_index.json`：全量样本索引，包含每条视频的互动、转写长度、主题标签、开头、结尾和排序线索。
- `transcript_signal_matrix.md`：全量语料信号矩阵，包含主题分布、高频词、开头词、结尾词、重复短语和逐视频指标。
- `transcript_signals.json` / `transcript_signals.md`：逐条 ASR 结构信号，包含 hook 类型、核心问题、转折点、论证方式、结尾方式、价值判断、贡献类型和风险样本标记。
- `evidence_coverage.json` / `evidence_coverage.md`：根据 `evidence_index.md` 中的视频 ID 计算证据覆盖评分，检查高互动、长转写、短转写、主题簇和边界样本覆盖。
- `coverage_gaps.json` / `coverage_gaps.md`：覆盖缺口推荐器，列出下一轮最应该补读、补证据或明确拒绝采用的视频。
- `short_form_coverage.json` / `short_form_coverage.md`：短视频专项分析，检查短转写样本的快速 hook、快速结尾和证据强度。
- `timeline_shift.json` / `timeline_shift.md`：按发布时间切分样本，检查哪些结论是长期稳定内核，哪些可能是近期热点。
- `asr_entity_review.json` / `asr_entity_review.md`：ASR 专名复核清单，列出英文模型名、品牌名、公司名、产品名和疑似误识别项。
- `usage_probe.md`：反向生成测试模板。必须用最终 skill 完成选题筛选、文稿改写、不像样本批评和完整脚本大纲。
- `evaluation_suite.md` / `evaluation_suite.json`：固定评测集模板。必须覆盖热点选题筛选、30 秒脚本、普通文案改写、不像样本批评、边界请求处理和证据解释，并让 JSON scorecard 通过。
- `reverse_identification.md` / `reverse_identification.json`：反向识别模板。必须证明生成结果中哪些是 creator-specific marker，哪些只是 generic AI marker，并回溯到 `persona_model.json` 和视频 ID。
- `reviewer_findings.md`：二次审稿模板。必须记录证据不足、过度抽象、模板太泛、身份越界和 ASR 专名风险，并说明修复状态。
- `refinement_audit.md`：宿主 agent 完成深加工后必须填写的审计清单。模板状态不能作为成品。
- `persona_model.schema.json`：结构化人格模型约束，供宿主 agent 和质量检查使用。
- `persona_model.json`：机器可读人格模型，供下游 agent 调用和程序化诊断。
- `persona_model_diagnostics.json`：质量检查自动生成，记录 persona model 是否字段完整、证据充足、与 Markdown 对齐。

### 2. 读取材料

宿主 agent 必须读取：

- `research/host_refinement/brief.md`
- `research/host_refinement/corpus_index.json`
- `research/host_refinement/transcript_signal_matrix.md`
- `research/host_refinement/transcript_signals.json`
- `research/reviews/evidence_coverage.md`
- `research/reviews/coverage_gaps.md`
- `research/reviews/short_form_coverage.md`
- `research/reviews/timeline_shift.md`
- `research/reviews/asr_entity_review.md`
- `metadata/selected.compact.json`
- `research/merged/summary.md`
- 当前 `skill/SKILL.md`
- 当前 `skill/references/*.md`
- 必要时按 brief 指定的视频 ID 读取 `transcripts/<video_id>.txt`

不要一次性把所有完整转写稿复制进最终 skill。需要更多证据时，按视频 ID 有选择地读原文。

### 3. 五轮深读协议

宿主 agent 必须按下面顺序处理，不得只根据 summary 或初稿改几段文字：

1. **语料地图轮**：读取 `corpus_index.json`、`transcript_signal_matrix.md` 和 `transcript_signals.json`，确认样本数量、转写覆盖、长短样本、主题分布、高互动样本、逐条结构信号和异常样本。
2. **代表样本轮**：至少深读 8 条完整转写。选择必须覆盖高互动、最长转写、短视频、现场/教程/实验/风险边界等不同类型。短视频选择参考 `short_form_coverage.md`。
3. **模型抽象轮**：分别抽取选题模型、脚本结构、表达 DNA、判断启发式、安全边界和阶段变化。每个重要结论至少绑定 2 个视频锚点；只有 1 个锚点的结论必须标为推断。
4. **阶段与专名审计轮**：读取 `timeline_shift.md` 和 `asr_entity_review.md`，避免把近期热点写成永久人格，并标出 ASR 专名复核项。
5. **反例审计轮**：主动寻找与初步结论冲突的视频，记录矛盾、变化和证据缺口。不要为了“像”而抹平材料内部差异。
6. **反向生成轮**：用最终 skill 完成 `usage_probe.md`，验证它能筛选选题、改写文稿、批评不像样本、生成脚本大纲，并能解释证据依据。
7. **结构化模型轮**：填写 `skill/references/persona_model.json`，把核心身份、选题模型、脚本模板、判断启发式、表达 DNA、反模式、安全边界、证据锚点、生成协议和评测 case 结构化。
8. **缺口补读轮**：读取 `coverage_gaps.md`，优先补读 priority=1 的视频。采用则写入 `evidence_index.md`，不采用则在 raw notes 中说明噪声、重复或证据弱。
9. **固定评测轮**：完成 `evaluation_suite.md` 和 `evaluation_suite.json`，用 6 个 case 检查最终 skill 是否能稳定完成选题、脚本、改写、批评、边界处理和证据解释。
10. **反向识别轮**：完成 `reverse_identification.md` 和 `reverse_identification.json`，证明生成稿中的 creator-specific markers 能回溯到 `persona_model.json` 和视频 ID，同时标出 generic AI markers。
11. **成品重写轮**：先写 raw research notes，再重写 skill 文件，然后填写 `reviewer_findings.md` 和 `refinement_audit.md`。模板里的复选框必须改为已完成状态，结论必须明确是否建议 `ready_for_use=true`。

### 4. 产出 raw research notes

至少写入 5 份研究笔记：

```text
research/raw/01_topic_and_timeline.md
research/raw/02_structure_and_judgment.md
research/raw/03_expression_and_boundary.md
research/raw/04_contradictions_and_evolution.md
research/raw/05_short_form_patterns.md
```

每份必须包含：

- 覆盖范围
- 来源元数据
- 关键发现
- 重复模式
- 矛盾与变化
- 推断
- 缺口

笔记必须区分“证据”和“推断”。不得把完整转写稿粘进去。

### 5. 重写 Creator Skill

重写以下文件，而不是只在初稿末尾追加几段：

```text
skill/SKILL.md
skill/references/persona.md
skill/references/topic_model.md
skill/references/script_style.md
skill/references/research_summary.md
skill/references/evidence_index.md
skill/references/persona_model.schema.json
skill/references/persona_model.json
skill/references/meta.json
```

最低内容要求：

- `persona.md`：表达 DNA、选题模型、脚本模板、判断启发式、反模式、Agent 使用协议。
- `topic_model.md`：至少 5 个有证据的选题模型，每个模型要有适用场景、证据锚点和失败模式。
- `script_style.md`：至少 4 个脚本模板，区分实验、教程、现场、产业解释等类型。
- `evidence_index.md`：至少 15 个证据锚点，优先覆盖高互动、长转写、典型结构和边界样本。
- `research_summary.md`：明确样本范围、核心发现、证据缺口和是否可进入 Skill 构建。
- `persona_model.json`：至少 5 个 topic model、4 个 script template、6 条 judgment heuristic、6 条 expression DNA、5 条 anti-pattern、4 条 safety boundary、15 个 evidence anchor，并包含 `generation_protocol` 和至少 6 个 `evaluation_cases`。每个 topic model 至少 2 个 evidence ID。
- `usage_probe.md`：必须有真实输入、输出、批评、使用的 persona_model 字段和证据说明，结论写明“是否通过反向生成测试：是/否”。
- `evaluation_suite.md/json`：必须完成 6 个固定 case，每个 case 引用 persona_model 字段和证据视频或安全规则，结论写明“是否通过评测集：是/否”，JSON scorecard 的 `passed=true`。
- `reverse_identification.md/json`：必须识别 creator-specific markers 和 generic AI markers，并回溯到 persona_model 字段与视频 ID，结论写明“是否通过反向识别测试：是/否”，JSON scorecard 的 `passed=true`。
- `reviewer_findings.md`：必须列出 reviewer 发现和修复状态，结论写明是否建议进入 `ready_for_use=true`。

### 6. 质量检查

修改后运行：

```powershell
python scripts/creator_pipeline.py quality-check `
  --run-dir .\runs\<project-name>\<run-id> `
  --json
```

`passed=true` 只表示安全底线和产物结构通过。

`ready_for_use=true` 才表示宿主 agent 已完成足够深度的研究、证据索引和 skill 重写。

## 不合格信号

- `persona.md` 只有泛泛标签，没有可执行规则。
- `topic_model.md` 只有 3-5 个常识分类，没有证据锚点。
- `script_style.md` 只写“问题 -> 过程 -> 结论”，没有分类型模板。
- `evidence_index.md` 低于 15 条，或只覆盖标题不覆盖结构观察。
- 没有 `research/raw/*.md`，或 raw note 不区分证据与推断。
- 没有 `research/host_refinement/corpus_index.json` 或 `transcript_signal_matrix.md`。
- 没有 `transcript_signals.json`，或没有使用逐条信号修正最终模型。
- 没有 `short_form_coverage.md`，或短视频样本完全未进入证据缺口说明。
- 没有 `timeline_shift.md`，或把近期热点直接写成永久人格。
- 没有 `asr_entity_review.md`，或科技专名未标注复核风险。
- `evidence_coverage.md` 评分过低，尤其是高互动、长转写、边界样本没有覆盖。
- `usage_probe.md` 仍是模板，或没有真实反向生成测试。
- `evaluation_suite.md` 仍是模板，或没有完成 6 个固定 case。
- `reverse_identification.md` 仍是模板，或无法证明生成稿来自该创作者的稳定模式。
- `evaluation_suite.json` 或 `reverse_identification.json` 仍是 `draft_template`，或 scorecard 没有通过。
- `persona.md`、`topic_model.md` 或 `script_style.md` 大量出现“引发共鸣”“层层递进”“通俗易懂”等泛化 AI 话术。
- `reviewer_findings.md` 仍是模板，或没有处理 high / medium 问题。
- `persona_model.json` 仍是模板，缺少证据 ID、生成协议或评测 case，或 `persona_model_diagnostics.json` 里 `ready=false`。
- `research/reviews/refinement_audit.md` 仍是空模板，或没有明确建议 `ready_for_use=true`。
- 文件里出现大量 `????` 或 `�`，说明编码损坏，必须修复后再检查。
- 直接复制长段转写稿进 skill。

## 宿主 Agent 输出顺序

1. 先生成或更新 `research/raw/*.md`。
2. 再重写 `skill/references/*.md`。
3. 最后重写 `skill/SKILL.md`。
4. 填写 `usage_probe.md`、`evaluation_suite.md/json`、`reverse_identification.md/json`、`reviewer_findings.md` 和 `refinement_audit.md`。
5. 跑质量检查。
6. 向用户报告：触达文件、证据数量、模型数量、覆盖评分、反向生成测试结果、质量检查结果和仍然存在的证据缺口。
