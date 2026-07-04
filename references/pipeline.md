# 创作者 Skill 构建流水线

## 产品方向

先验证固定的 skill 构建链路，再考虑 Web 平台。MVP 的核心价值不是做一个“大而全后台”，而是从公开或授权的创作者内容中生成一个有证据支撑、可复用的 Creator Skill。

第一版链路：

```text
抖音创作者主页
  -> TikHub 拉取近期公开作品
  -> 下载视频
  -> ffmpeg 抽取音频
  -> 阿里云 Qwen-ASR 转写
  -> 确定性 transcript summary
  -> 确定性 Creator Skill 初稿
  -> prepare_host_refinement.py 生成宿主研究包
  -> 宿主 agent 读取 corpus index / signal matrix / transcript signals / evidence coverage
  -> 宿主 agent 写 research/raw 笔记并重写 Creator Skill
  -> 宿主 agent 填写 persona_model.json 和生成协议
  -> 宿主 agent 完成 usage probe、evaluation suite、reverse identification、reviewer findings 和 refinement audit
  -> 严格质量检查
```

## 步骤契约

### 1. 解析创作者链接

输入：

```json
{
  "source_url": "https://v.douyin.com/xxx/",
  "project_name": "creator-slug"
}
```

输出：

```json
{
  "platform": "douyin",
  "source_url": "https://v.douyin.com/xxx/",
  "project_slug": "creator-slug"
}
```

### 2. 拉取 TikHub 元数据

使用配置好的 TikHub endpoint 和 token 请求数据，同时保存原始响应和归一化后的元数据。

归一化视频条目：

```json
{
  "platform": "douyin",
  "platform_video_id": "string",
  "title": "string",
  "published_at": "string",
  "duration": 0,
  "stats": {
    "like": 0,
    "favorite": 0,
    "share": 0,
    "comment": 0
  },
  "download_url": "string",
  "source_url": "string",
  "raw": {}
}
```

### 3. 选择近期样本

按 `published_at` 倒序排列，选择 `sample_count` 条。实际作品不足时，记录实际选中的数量。

除了 `metadata/selected.json`，还必须写入：

- `metadata/selected.compact.json`：去掉供应商原始 `raw` 字段，只保留研究常用字段，供宿主 agent 优先读取。
- `metadata/creator_profile.json`：从作品元数据中尽力提取昵称、handle、author_id、sec_uid；字段提取不到时留空。

`selected.json` 继续保留完整 `raw` 字段，用于溯源和调试。选择策略必须显式记录为 `selection_strategy: published_at_desc`。

### 4. 下载视频

要求：

- 下载到 `media/videos/`。
- 先写入 `*.part`，成功后再重命名。
- 已存在完整文件时跳过。
- 在日志中记录每条视频状态。

### 5. 抽取音频

使用 `ffmpeg` 输出到 `media/audio/`。默认格式可配置，当前推荐 `mp3`，便于控制 ASR 请求体大小。

### 6. 阿里云 ASR

使用配置好的阿里云 ASR adapter。保存：

- 原始 JSON：`transcripts/raw_json/`
- 纯文本转写：`transcripts/*.txt`
- 可用时保存字幕文件

`qwen3-asr-flash` 同步接口对单段音频有限制，因此 runner 默认按 `ASR_SEGMENT_SECONDS` 切片后逐段转写，再合并成完整文本。

### 7. 归一化转写稿

有字幕文本时复用 `scripts/research/srt_to_transcript.py`。ASR JSON 则转换成带时间戳的文本，再做清理。

### 8. 确定性摘要与初稿

runner 会确定性写入 `research/merged/summary.md`，保证流程可恢复、可测试。真正的风格研究由当前加载此 skill 的 Codex 或 Claude Code 完成，不需要额外配置研究用 LLM API。

摘要中必须提醒：ASR 可能误识别专名、人名、品牌名和英文模型名；最终写入 skill 前要用元数据或源材料校对关键名词。

确定性摘要只作为索引，不替代宿主 agent 研究。

### 9. 宿主 Agent 精修

流水线完成后先运行：

```powershell
python scripts/prepare_host_refinement.py `
  --run-dir .\runs\<project-name>\<run-id>
```

生成：

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
research/reviews/persona_model_diagnostics.json
research/reviews/refinement_audit.md
skill/references/persona_model.schema.json
skill/references/persona_model.json
```

宿主 agent 必须读取该 brief、corpus index、signal matrix、transcript signals、evidence coverage、`metadata/selected.compact.json`、`research/merged/summary.md`、当前 `skill/` 初稿，并按需读取具体 `transcripts/<video_id>.txt`。

宿主 agent 必须写入：

```text
research/raw/01_topic_and_timeline.md
research/raw/02_structure_and_judgment.md
research/raw/03_expression_and_boundary.md
research/raw/04_contradictions_and_evolution.md
research/raw/05_short_form_patterns.md
```

研究重点：

- 选题系统
- 选题判断模型
- 开头 hook 模式
- 脚本结构
- 表达 DNA
- 价值判断模型
- 反复出现的案例和证据索引
- 安全边界
- 证据缺口和推断标注

### 10. 构建 Creator Skill

生成：

```text
SKILL.md
references/persona.md
references/topic_model.md
references/script_style.md
references/research_summary.md
references/evidence_index.md
references/meta.json
```

初稿可以由脚本生成，但最终必须由宿主 agent 基于 raw research notes 和 brief 重写。不要只在确定性初稿末尾追加几段。

重写后必须填写 `skill/references/persona_model.json`、`research/reviews/usage_probe.md`、`research/reviews/evaluation_suite.md`、`research/reviews/reverse_identification.md`、`research/reviews/reviewer_findings.md` 和 `research/reviews/refinement_audit.md`。空模板不能进入 `ready_for_use=true`。

### 11. 质量检查

复用已有质量检查能力，并追加 Creator Skill 专项检查：

- 是否有免责声明
- 是否没有长篇转写稿倾倒
- 是否存在证据索引
- 是否存在安全边界
- 是否说明了内容生成模式
- 是否存在 host refinement 包、逐条 ASR signals、证据覆盖评分、覆盖缺口推荐、persona model 和已填写的 usage/evaluation/reverse-identification/reviewer/audit
- 是否有足够 raw research notes
- 是否有足够选题模型、脚本模板和证据锚点
- 是否存在乱码

## 断点续跑策略

每个高成本步骤执行前，先检查目标产物是否已经存在：

- 已下载视频
- 已抽取音频
- ASR 原始 JSON
- 转写文本
- 研究摘要
- 生成的 skill 文件

除非用户明确要求重建，否则跳过已经成功的产物。

## 脚本地图

- `scripts/build_creator_skill.py`：创建运行目录，写入 `input.json`、脱敏 `config.snapshot.json` 和 `workflow.plan.json`。
- `scripts/provider_adapters.py`：调用 TikHub 与阿里云 ASR，封装 endpoint、鉴权和响应结构差异。
- `scripts/creator_pipeline.py`：归一化元数据、选择样本、下载视频、抽音频、ASR JSON 转文本、生成摘要、构建 Creator Skill 初稿、质量检查、写运行摘要。
- `scripts/run_creator_skill_build.py`：端到端编排上述步骤。
- `scripts/prepare_host_refinement.py`：从运行目录生成宿主 agent 精修 brief、corpus index、signal matrix、逐条 transcript signals、证据覆盖评分和 review 模板，帮助读取大样本而不把完整转写塞进上下文。
- `scripts/config_check.py`：检查供应商配置、token budget、Python 包、`ffmpeg` 和 `ffprobe` 是否可用。

## 本地与分阶段运行

TikHub 已经调用过或要用保存的响应测试时，使用 `--raw-metadata`。

ASR 已经完成，或暂时没有供应商凭证时，使用 `--transcripts-dir`。

调试阶段可使用 `--skip-download`、`--skip-audio` 或 `--skip-asr`。只要已有转写稿，仍然可以生成 draft skill。

一次运行完成后，宿主 agent 应检查：

- `research/host_refinement/brief.md`
- `research/host_refinement/corpus_index.json`
- `research/host_refinement/transcript_signal_matrix.md`
- `research/host_refinement/transcript_signals.json`
- `research/reviews/evidence_coverage.md`
- `transcripts/*.txt`
- `research/merged/summary.md`
- `skill/SKILL.md`
- `skill/references/*.md`

然后直接使用内置推理模型优化生成的 Creator Skill。

## 阿里云 ASR 路径

支持两种 ASR 路径：

1. `ALI_ASR_PROVIDER=openai-compatible`：使用 Qwen-ASR 兼容模式，例如 `qwen3-asr-flash` 的 `/chat/completions` + `input_audio`。
2. `ALI_ASR_PROVIDER=aliyun`：使用 DashScope 录音文件识别，需要公网可访问的音频 URL。

录音文件识别模式下，`ffmpeg` 抽出本地音频后，需要通过以下方式之一得到音频 URL：

- `AUDIO_PUBLIC_URL_BASE`：音频文件托管在固定公网路径下。
- `ALI_ASR_AUDIO_URL_TEMPLATE`：用 filename/stem/path 格式化每个音频 URL。
- `ALI_OSS_*`：上传到 OSS 并传入签名 URL。

如果都没有配置，runner 会记录 ASR skipped，除非启用 `--strict-asr`。

音频 URL 优先级：template、public base URL、OSS 上传。

## 质量门槛

每次完成运行都会写入：

- `logs/creator_quality_report.json`
- `run_summary.json`

质量报告检查：

- 必需 skill 文件存在
- 有免责声明
- 有安全边界
- 有证据索引
- 生成 skill 没有明显转写稿倾倒
- 有转写稿
- 有配置快照
- 有已选元数据
- 有精简已选元数据
- 有创作者档案
- 有研究摘要

质量报告分两层：

- `passed`：流程产物完整且安全底线通过。
- `ready_for_use`：宿主 agent 已完成深加工，host refinement 包、逐条 ASR signals、证据覆盖评分、覆盖缺口推荐、persona model、usage probe、evaluation suite、reverse identification、reviewer findings、refinement audit、persona、topic model、script style、evidence index 和 raw research notes 达到最低内容密度。

`passed=true` 且 `ready_for_use=false` 是允许状态，表示确定性流水线已完成，但 Creator Skill 仍是初稿，需要宿主 agent 深加工。

`ready_for_use=true` 的含义更严格：

- 至少 5 份 `research/raw/*.md` 研究笔记。
- `research/host_refinement/brief.md`、`corpus_index.json`、`transcript_signal_matrix.md` 和 `transcript_signals.json` 存在且覆盖全量样本。
- `research/reviews/evidence_coverage.md` 存在，证据覆盖高互动、长转写、短转写、主题簇和边界样本。
- `research/reviews/coverage_gaps.md` 存在，宿主 agent 已补读或解释高优先级缺口视频。
- `skill/references/persona_model.json` 结构完整，包含生成协议和评测 case，`research/reviews/persona_model_diagnostics.json` 显示 `ready=true`。
- `research/reviews/usage_probe.md` 已完成反向生成测试，并明确通过。
- `research/reviews/evaluation_suite.md/json` 已完成固定评测集，并明确通过。
- `research/reviews/reverse_identification.md/json` 已完成反向识别测试，并明确通过。
- `research/reviews/reviewer_findings.md` 已完成二次审稿，并明确建议进入 `ready_for_use=true`。
- `research/reviews/refinement_audit.md` 已填写，并明确建议 `ready_for_use=true`。
- `persona.md` 有足够密度，并包含表达 DNA、反模式、安全边界和 Agent 使用协议。
- `topic_model.md` 至少有多个带证据和失败模式的选题模型。
- `script_style.md` 至少有多个分类型脚本模板。
- `evidence_index.md` 有足够视频锚点。
- 文件中没有明显乱码。
- 文件中没有大量泛化 AI 模板话术。

手动质量检查：

```powershell
python scripts/creator_pipeline.py quality-check `
  --run-dir .\runs\创作者名称\<run-id>
```

离线回归：

```powershell
python scripts/self_test.py
```

真实运行准备检查：

```powershell
python scripts/config_check.py --env .env --include-config
```
