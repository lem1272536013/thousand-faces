---
name: thousand-faces-style-skill
description: "千人千面 / Thousand Faces：开源的创作者风格研究与 Creator Skill 生成项目。从抖音创作者主页克隆公开表达风格并生成可复用 Creator Skill，适用于中文开发者运行或维护固定流程：TikHub 拉取抖音公开作品，下载视频，ffmpeg 抽音频，阿里云 Qwen-ASR 转写，当前 Codex/Claude Code 读取转写稿并完善创作者风格 Skill。不需要额外配置研究用大模型 API，只需要配置数据抓取和 ASR 凭证。"
---

# 千人千面 / Thousand Faces

## 用途

使用这个 skill，把一个抖音创作者主页转成可复用的 Creator Skill。它克隆的是公开表达风格，不是创作者本人；它不是“真人冒充系统”，而是一个基于公开或授权内容的风格研究与内容辅助工具。

面向默认使用者：中文开发者。说明、命令示例、产物解释优先使用中文；保留脚本名、环境变量名、接口字段名等技术标识的英文原文。

## 必读材料

- 运行或修改流程前，先读 `references/pipeline.md`。
- 配置 TikHub 或阿里云 ASR 前，先读 `references/configuration.md`。
- 完整生成 Creator Skill 时，必须读 `references/host_refinement.md`。
- 精修人格画像时，按需读 `references/prompts/celebrity/research.md`、`persona_analyzer.md`、`persona_builder.md` 和 `merger.md`。

## 主流程

1. 解析抖音创作者主页或分享短链，创建本次运行目录。
2. 通过 TikHub 拉取近期公开作品元数据。
3. 按 `published_at` 倒序选择最近的 N 条作品，同时写入精简元数据和创作者档案。
4. 下载视频，支持 `.part` 临时文件和断点跳过。
5. 使用 `ffmpeg` 抽取音频。
6. 使用阿里云 Qwen-ASR 转写音频。
7. 归一化转写文本。
8. 生成确定性的 transcript summary 和 Creator Skill 初稿。
9. 运行 `scripts/prepare_host_refinement.py` 生成 host refinement 包、逐条 ASR 信号、证据覆盖评分、短视频覆盖、时间线阶段变化、ASR 专名复核、persona model schema/template 和 review 模板。
10. 当前 Codex/Claude Code 读取 brief、转写稿索引、逐条信号、覆盖评分、元数据和初稿，写入 `research/raw/*.md`，再重写 Creator Skill。
11. 当前 Codex/Claude Code 填写结构化 `persona_model.json`，完成反向生成测试、固定评测集、反向识别测试、二次审稿和 refinement audit。
12. 运行质量检查并写入运行摘要。

## 核心模块

确定性流水线由下面几类脚本组成。修改时优先保持输入输出契约稳定，不要轻易改变运行目录结构和质量检查口径。

研究辅助模块：

- `scripts/research/srt_to_transcript.py`：将 SRT/VTT 字幕清洗为可研究的 transcript 文本。
- `scripts/research/merge_research.py`：汇总 `research/raw/` 里的研究笔记，生成结构化摘要。
- `scripts/research/quality_check.py`：提供轻量级研究与 Skill 文本质量检查能力。

主编排模块：

- `scripts/provider_adapters.py`：封装 TikHub、阿里 ASR、OpenAI-compatible ASR 和 OSS 上传。
- `scripts/creator_pipeline.py`：处理元数据归一化、样本选择、下载、抽音频、转写归一化、摘要、初稿和质量检查。
- `scripts/run_creator_skill_build.py`：端到端运行入口。
- `scripts/prepare_host_refinement.py`：生成宿主 Agent 精修包、证据覆盖、逐条信号和评测模板。
- `scripts/config_check.py`：检查真实运行所需配置、依赖和外部命令。
- `scripts/self_test.py`：离线回归测试，验证主流程和精修包生成。

不要把原 Whisper 转写路径作为主路径。本项目以阿里云 Qwen-ASR 为默认转写方案，Whisper 只适合作为后续可选 fallback。

## 配置规则

- 不要在代码中硬编码真实密钥、token、模型名、endpoint URL 或 token budget。
- 从 `.env`、环境变量或显式 CLI 参数读取运行配置。
- 每次运行都写入脱敏后的 `config.snapshot.json`。
- 日志和摘要中只保留密钥的短前缀和短后缀。
- TikHub 与阿里云 ASR 的配置必须彼此独立、可替换。
- 不要求用户配置单独的研究大模型 API；风格研究由加载此 skill 的宿主 agent 模型完成。

## 安全边界

生成的 Creator Skill 必须：

- 声明输出是基于公开或授权材料的 AI 风格辅助，不代表创作者本人。
- 不声称“我是该创作者”、不代表该创作者发言。
- 不把完整转写稿塞进生成的 skill。
- 证据以改写、摘要和短片段为主，避免长篇引用。
- 拒绝身份冒充、虚假背书、声音克隆、形象克隆、私密信息推断等请求。

## 产物结构

每次成功运行应生成：

```text
runs/<project-name>/<run-id>/
  input.json
  config.snapshot.json
  metadata/raw.json
  metadata/normalized.json
  metadata/selected.json
  metadata/selected.compact.json
  metadata/creator_profile.json
  media/videos/
  media/audio/
  transcripts/
  research/raw/
  research/host_refinement/brief.md
  research/host_refinement/corpus_index.json
  research/host_refinement/transcript_signal_matrix.md
  research/host_refinement/transcript_signals.json
  research/host_refinement/transcript_signals.md
  research/merged/
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
  skill/SKILL.md
  skill/references/persona.md
  skill/references/topic_model.md
  skill/references/script_style.md
  skill/references/research_summary.md
  skill/references/evidence_index.md
  skill/references/persona_model.schema.json
  skill/references/persona_model.json
  skill/references/meta.json
  logs/
```

## 实现要点

- 下载、归一化、目录布局、配置检查和质量检查优先用确定性脚本完成。
- `selected.json` 保留供应商原始 `raw` 字段用于追溯；人工研究和宿主 agent 优先读取 `selected.compact.json`，避免被 TikHub 噪音淹没。
- `metadata/creator_profile.json` 保存从作品元数据中推断出的昵称、handle、author_id 和 sec_uid；如果供应商字段不足，允许为空但文件仍应存在。
- 样本选择策略固定为 `published_at_desc`。如果用户说“前 N 条”，默认解释为最近 N 条，并在元数据中显式记录。
- 数据采集、ASR 准备、转写归一化、摘要和初稿生成都应可重复运行。
- 风格研究、判断归纳和最终 Creator Skill 文案修订交给当前宿主 agent 完成；宿主 agent 不应把确定性初稿当成成品。
- 完整产物必须包含 `research/host_refinement/brief.md`、`corpus_index.json`、`transcript_signal_matrix.md`、`transcript_signals.json`、证据覆盖评分、覆盖缺口推荐、短视频覆盖、时间线阶段变化、ASR 专名复核、至少 5 份 `research/raw/*.md` 研究笔记、结构化 `persona_model.json`、诊断文件，以及已填写的 `usage_probe.md`、`evaluation_suite.md/json`、`reverse_identification.md/json`、`reviewer_findings.md` 和 `refinement_audit.md`。
- `ready_for_use=true` 前，宿主 agent 必须明确使用全量语料索引、信号矩阵、逐条 ASR 信号、证据覆盖评分和 `persona_model.json`，并在 `skill/references/*.md` 中体现选题模型、脚本模板、判断启发式、证据锚点和边界。
- 保留中间产物，失败后可以从下载、抽音频、ASR 或转写稿继续。
- 供应商 API 形态不确定时，只改 adapter 或配置映射，不要改下游产物结构。
- `ALI_ASR_PROVIDER=openai-compatible` 时，使用配置的 Qwen-ASR 兼容模式。`qwen3-asr-flash` 走 `/chat/completions` + `input_audio`。
- 录音文件识别模式需要可访问音频 URL，可通过 `ALI_ASR_AUDIO_URL_TEMPLATE`、`AUDIO_PUBLIC_URL_BASE` 或 `ALI_OSS_*` 上传获得。

## 常用命令

只创建运行目录，不调用外部服务：

```powershell
python scripts/build_creator_skill.py `
  --source-url "https://v.douyin.com/xxx/" `
  --project-name "创作者名称" `
  --sample-count 50 `
  --env .env
```

运行完整确定性流水线：

```powershell
python scripts/run_creator_skill_build.py `
  --source-url "https://v.douyin.com/xxx/" `
  --project-name "创作者名称" `
  --sample-count 50 `
  --env .env
```

流水线完成后，在当前 Codex/Claude Code 会话中继续读取生成的 `transcripts/`、`research/merged/summary.md` 和 `skill/` 文件，使用内置模型完善 Creator Skill。不要再向用户索要额外研究模型配置。

宿主 agent 精修前先生成研究包：

```powershell
python scripts/prepare_host_refinement.py `
  --run-dir .\runs\创作者名称\<run-id>
```

然后按 `references/host_refinement.md` 执行：写入 raw research notes，重写 `skill/SKILL.md` 和 `skill/references/*.md`，填写 `persona_model.json`、usage probe、evaluation suite、reverse identification、reviewer findings 和 refinement audit，最后重新质量检查。

运行器会自动写入 `logs/creator_quality_report.json` 和 `run_summary.json`。

质量报告有两层含义：

- `passed`：确定性流水线产物齐全，安全底线、证据索引和转写稿隔离检查通过。
- `ready_for_use`：宿主 agent 已完成深加工，包含足够 raw research、逐条 ASR 信号、证据覆盖评分、结构化 persona model、反向生成测试、二次审稿、persona、选题模型、脚本模板和证据条目，可作为成品使用。

如果 `passed=true` 但 `ready_for_use=false`，说明流水线成功，但宿主 agent 仍需读取转写稿和研究摘要继续完善 skill。人工修改生成 skill 后，可用以下命令重新检查：

`ready_for_use=true` 必须表示宿主 agent 已完成深加工，而不只是确定性初稿达到最低字数。检查重点包括：

- 至少 5 份 raw research note。
- host refinement 包完整，含 brief、corpus index、signal matrix、逐条 transcript signals。
- evidence coverage 评分达标，覆盖高互动、长转写、短转写、主题簇和边界样本。
- coverage gaps 已生成，宿主 agent 已补读或解释高优先级缺口视频。
- short form、timeline shift、ASR entity review 三类专项审查文件存在。
- persona model 结构完整，诊断通过，且证据 ID 能回溯到 evidence index。
- usage probe、evaluation suite、reverse identification、reviewer findings、refinement audit 已填写，并明确建议 ready。
- evaluation suite 和 reverse identification 的 Markdown 与 JSON 都已填写，并明确通过。
- 反模板化检测通过，没有大量“引发共鸣”“层层递进”“通俗易懂”等泛化 AI 话术。
- persona 有可执行的表达 DNA、判断启发式和安全边界。
- topic model 至少包含多个带证据锚点和失败模式的模型。
- script style 至少包含多个分类型模板。
- evidence index 覆盖足够多的视频锚点。
- 没有乱码、长篇转写倾倒或身份冒充风险。

```powershell
python scripts/creator_pipeline.py quality-check `
  --run-dir .\runs\创作者名称\<run-id>
```

修改脚本后运行离线回归：

```powershell
python scripts/self_test.py
```

真实运行前做脱敏配置检查：

```powershell
python scripts/config_check.py --env .env --include-config
```
