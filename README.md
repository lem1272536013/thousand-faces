<p align="center">
  <img src="docs/assets/readme/qianrenqianmian-promo-20x9.png" alt="千人千面 - Thousand Faces" width="100%" />
</p>

<h1 align="center">千人千面 / Thousand Faces</h1>

<p align="center">
  <strong>把创作者的公开表达风格，沉淀成可以被理解、复用、审查和进化的 Creator Skill。</strong>
  <br />
  <sub>Clone a creator's public style into an evidence-based, reusable AI Skill.</sub>
</p>

<p align="center">
  开源的创作者风格研究流水线 · 公开内容 · 风格克隆 · 证据化 Skill
</p>

<p align="center">
  <img alt="Thousand Faces" src="https://img.shields.io/badge/Thousand%20Faces-Style%20Skill-111111?style=for-the-badge" />
  <img alt="Style Clone" src="https://img.shields.io/badge/Style-Clone-666666?style=for-the-badge" />
  <img alt="Evidence Based" src="https://img.shields.io/badge/Evidence-Based-999999?style=for-the-badge" />
  <img alt="Human First" src="https://img.shields.io/badge/Human-First-f5f5f5?style=for-the-badge&labelColor=111111&color=f5f5f5" />
  <a href="https://github.com/lem1272536013/thousand-faces/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/lem1272536013/thousand-faces/actions/workflows/ci.yml/badge.svg" /></a>
</p>

<br />

<table align="center">
  <tr>
    <td align="center" width="33%">
      <sub>BUFFON</sub>
      <br />
      <strong>Le style est l'homme même.</strong>
      <br />
      <sup>风格即其人。</sup>
    </td>
    <td align="center" width="33%">
      <sub>MARSHALL McLUHAN</sub>
      <br />
      <strong>The medium is the message.</strong>
      <br />
      <sup>媒介本身，就是信息。</sup>
    </td>
    <td align="center" width="33%">
      <sub>LUDWIG WITTGENSTEIN</sub>
      <br />
      <strong>The limits of my language mean the limits of my world.</strong>
      <br />
      <sup>语言的边界，就是世界的边界。</sup>
    </td>
  </tr>
</table>

<br />

<p align="center">
  <strong>千人千面不是在制造替身。</strong>
  <br />
  它是在把风格从内容流里打捞出来，把方法交还给创作者，把表达变成一种可以长期生长的资产。
</p>

<p align="center">
  <a href="#项目描述">项目描述</a> ·
  <a href="#产品宣言">产品宣言</a> ·
  <a href="#为什么它重要">为什么重要</a> ·
  <a href="#从内容到-skill">工作流</a> ·
  <a href="#边界">边界</a> ·
  <a href="#给开发者的最短依赖">开发者入口</a>
</p>

<br />

<table>
  <tr>
    <td align="center" width="25%">
      <sub>POSITIONING</sub>
      <br />
      <strong>创作者风格资产化</strong>
    </td>
    <td align="center" width="25%">
      <sub>INPUT</sub>
      <br />
      <strong>公开或授权内容</strong>
    </td>
    <td align="center" width="25%">
      <sub>OUTPUT</sub>
      <br />
      <strong>Creator Skill</strong>
    </td>
    <td align="center" width="25%">
      <sub>STANCE</sub>
      <br />
      <strong>Human-first AI</strong>
    </td>
  </tr>
</table>

## 项目描述

千人千面（Thousand Faces）是一个开源的创作者风格研究与 Creator Skill 生成项目。

它从公开或授权的创作者内容出发，通过作品采集、音视频处理、ASR 转写、风格研究、证据索引和质量审查，理解一个人长期稳定的表达方式：他如何选题，如何开头，如何推进观点，如何处理情绪，如何建立信任，如何形成自己的内容判断。然后，它把这些模糊却珍贵的东西整理成一个可被 Agent 调用、复盘和持续进化的风格能力包。

它不是为了复制谁本人。

它是为了让一个人的公开表达风格和创作方法被看见、被保存、被复用。

## 产品宣言

这个时代不缺内容。

缺的是能被继承的方法，能被解释的风格，能经得起复盘的判断。

我们每天都在生产新的文本、新的视频、新的观点，但太多真正重要的东西会被流量冲走：一个创作者如何建立信任，如何拿捏分寸，如何把复杂问题讲得有温度，如何在相似的热点里说出属于自己的判断。

千人千面要做的，是把这些隐性的能力从作品里提取出来。

不是把人变成模型，而是让人的方法不再消失。

不是让 Agent 替谁发声，而是让 Agent 学会尊重一个人的表达结构。

不是追求廉价的“像”，而是追求有证据、有边界、有灵魂的个性化协作。

## 为什么它重要

每个成熟创作者身上，都有一套看不见的系统。

观众看到的是一条条视频、一次次表达、一个个爆款。但真正决定内容质量的，往往不是某一句金句，而是背后的判断力：

- 什么话题值得讲。
- 什么开头能让人留下来。
- 什么节奏能让观点更有力量。
- 什么案例能让抽象概念落地。
- 什么边界不能越过。
- 什么语气才像“这个人”。

这些能力以前通常只能留在创作者脑子里，或者散落在团队经验、口头复盘和零碎文档里。时间一长，风格会丢，方法会散，团队新人只能靠感觉模仿。

千人千面想做的事很简单，也很有野心：

让创作者的表达能力变成一种长期资产。

## 它真正生成的不是文案

千人千面生成的不是一篇仿写稿，也不是一个“像某某一样说话”的提示词。

它生成的是 Creator Skill。

一个好的 Creator Skill 应该像一份创作者的表达说明书：

- 它知道这个创作者通常关注什么问题。
- 它知道这个创作者如何判断选题价值。
- 它知道这个创作者如何组织一条内容。
- 它知道这个创作者的语气、节奏、结构和禁区。
- 它知道哪些结论有证据，哪些只是推测。
- 它知道自己不能冒充本人。

这让 Agent 不再只是“临时写一篇”，而是拥有可持续调用的风格上下文。

## 不只是 Prompt

<table>
  <tr>
    <th align="left">普通仿写 / Prompt</th>
    <th align="left">千人千面</th>
  </tr>
  <tr>
    <td>追求表层相似：语气词、口头禅、高频词。</td>
    <td>追求结构理解：选题、论证、节奏、边界和判断力。</td>
  </tr>
  <tr>
    <td>一次性生成，用完即散。</td>
    <td>沉淀为 Creator Skill，可以反复调用、审查和迭代。</td>
  </tr>
  <tr>
    <td>容易滑向“像某个人说话”。</td>
    <td>明确声明辅助创作，不冒充本人，不伪造身份。</td>
  </tr>
  <tr>
    <td>依赖感觉和风格标签。</td>
    <td>保留证据索引，让判断有来处，让修改有依据。</td>
  </tr>
</table>

## 适合谁

### 创作者

如果你已经积累了一批公开作品，千人千面可以帮你把自己的表达方法整理出来。

不是把你变成模板，而是把你已经形成的能力变得更清楚：你擅长什么，你反复使用什么结构，你为什么能打动观众，你的内容边界在哪里。

### 内容团队

如果你在做账号矩阵、达人孵化、MCN 内容管理或品牌内容团队，千人千面可以把经验从“靠老人带新人”变成“有结构可复用”。

新人不必只靠猜测去模仿风格，团队也不必每次都从零解释选题逻辑和脚本节奏。

### Agent 使用者

如果你希望 Agent 帮你选题、改稿、写口播脚本、点评内容，千人千面可以给 Agent 一份更稳定的风格底座。

它让 Agent 不只是回答问题，而是带着一个创作者的内容系统去协作。

## 这个项目相信什么

<table>
  <tr>
    <td width="33%" valign="top">
      <sub>01 / 正名</sub>
      <br />
      <strong>名不正，则言不顺。</strong>
      <br /><br />
      个性化的第一步不是模仿，而是把“这个 Skill 到底是什么”说清楚。它是研究助手，不是身份替身；是创作基础设施，不是人格复制器。
    </td>
    <td width="33%" valign="top">
      <sub>02 / 形式</sub>
      <br />
      <strong>Form ever follows function.</strong>
      <br /><br />
      一个 Creator Skill 的形态，应该从它要承担的工作长出来：选题、结构、语气、边界、证据，而不是从几个漂亮标签拼出来。
    </td>
    <td width="33%" valign="top">
      <sub>03 / 留白</sub>
      <br />
      <strong>不是所有东西都该被生成。</strong>
      <br /><br />
      好的个性化系统，必须知道哪里应该表达，哪里应该克制，哪里应该拒绝。边界不是限制创造力，边界是长期信任的形状。
    </td>
  </tr>
</table>

### 风格不是皮肤，是结构

真正的风格不只是口头禅、语气词和几个高频词。

风格是一个人如何观察世界、如何选择问题、如何安排论证、如何表达立场、如何控制分寸。

所以千人千面关注的不只是“说得像”，而是“想得像、组织得像、判断得像”，并且始终保留证据和边界。

### 个性化不是贴标签

一个人不应该被压缩成几个粗糙标签。

千人千面希望生成的是细腻的、多层次的风格画像：既包含主题偏好，也包含结构习惯；既包含表达 DNA，也包含内容禁区；既能辅助创作，也能提醒风险。

### 辅助创作不是身份冒充

Creator Skill 是风格研究助手，不是创作者本人。

它可以帮助整理选题、生成草稿、优化结构、提供风格点评，但不应该声称代表创作者本人发言，也不应该用于伪造授权、背书、私密观点或身份关系。

千人千面要做的是放大方法，不是伪造身份。

## 从内容到 Skill

千人千面围绕一条完整的创作者风格资产化链路展开：

<table>
  <tr>
    <td align="center"><sub>01</sub><br /><strong>创作者主页</strong></td>
    <td align="center"><sub>02</sub><br /><strong>公开作品采集</strong></td>
    <td align="center"><sub>03</sub><br /><strong>视频与音频处理</strong></td>
    <td align="center"><sub>04</sub><br /><strong>内容转写</strong></td>
  </tr>
  <tr>
    <td align="center"><sub>05</sub><br /><strong>风格研究</strong></td>
    <td align="center"><sub>06</sub><br /><strong>证据索引</strong></td>
    <td align="center"><sub>07</sub><br /><strong>Creator Skill</strong></td>
    <td align="center"><sub>08</sub><br /><strong>Agent 协作</strong></td>
  </tr>
</table>

这条链路的意义不在于“自动化抓取”，而在于把内容背后的创作能力一步步萃取出来。

最终产物不是一堆素材，而是一套可被继续审查、修改和进化的创作者能力模型。

## Creator Skill 能做什么

先说清楚两个概念。

**Creator Skill** 是最终产物。它不是一篇提示词，也不是一份单次生成的文案，而是一组可以被 Agent 加载和反复调用的风格能力文件：通常包含 `SKILL.md`、创作者画像、选题模型、脚本结构、表达 DNA、证据索引、安全边界和结构化 `persona_model.json`。它的作用是让 Agent 在选题、写稿、改写和风格点评时，拥有一套稳定的创作者风格上下文。

**千人千面** (**Thousand Faces**) 是生成 Creator Skill 的项目和流水线。它负责从公开或授权内容出发，完成作品采集、音视频处理、ASR 转写、风格研究、证据整理、质量检查和宿主 Agent 精修，最后输出一个可用的 Creator Skill。换句话说，千人千面 是“工厂”和方法论，Creator Skill 是每次为某个创作者生成出来的“风格能力包”。

一个经过整理的 Creator Skill 可以帮助完成：

- 选题建议：判断什么话题适合这个创作者。
- 脚本结构：给出更接近其表达方式的内容骨架。
- 口播草稿：生成可继续人工修改的初稿。
- 内容改写：让已有文本更贴近目标风格。
- 风格点评：指出哪里不像、哪里过度、哪里越界。
- 团队交接：把隐性的创作经验沉淀成文档化资产。

它最适合成为创作流程里的第二大脑，而不是替代创作者本人。

## 边界

千人千面默认站在创作者和内容团队这一边。

它应该帮助人更好地理解自己的表达，而不是让别人偷走一个人的身份。

因此，生成的 Creator Skill 应始终遵守：

- 只基于公开内容或已授权材料。
- 每个 run 都明确记录 `rights_basis`：`unspecified`、`public_research`、`creator_authorized` 或 `team_owned`；未声明时只允许 draft，不得进入成品或商业交付。
- 授权场景只在 run 中保存安全引用 ID 或相对说明路径，不复制合同、身份证明和签字页等私密材料。
- 最终 Skill 保留来源平台、采集时间、权利依据、退出/下架联系和使用边界，且与运行清单一致。
- 本地媒体、转写和最终 Skill 按 `retain_media`、`transcripts_only` 或 `final_skill_only` 策略管理；实际删除前必须先 dry-run 查看清单。
- 下载、ffmpeg 和 ASR 分别受独立并发上限约束；compatible-chat 的音频分片在 Base64 前执行文件上限和总在途内存预算检查。
- 不声称“我是该创作者”。
- 不代表创作者本人发布声明。
- 不伪造授权、合作、背书或商业关系。
- 不推断隐私、私密观点或未公开经历。
- 不用于声音克隆、形象克隆、数字人冒充。
- 不把大段原始转写稿塞进 Skill。

有边界，才有长期价值。

## 当前形态

这个仓库当前提供的是一个 Skill-first 的 Thousand Faces。

<table>
  <tr>
    <td width="50%" valign="top">
      <sub>PRODUCT SURFACE</sub>
      <br />
      <strong>一个可运行的 Skill 构建器</strong>
      <br /><br />
      面向创作者主页、公开作品、转写文本和风格研究，输出可被宿主 Agent 调用的 Creator Skill。
    </td>
    <td width="50%" valign="top">
      <sub>DESIGN CENTER</sub>
      <br />
      <strong>稳定产物，而不是一次性生成</strong>
      <br /><br />
      保留中间材料、证据索引、质量检查和安全边界，让每一次生成都可以复盘、校正、迭代。
    </td>
  </tr>
</table>

核心目录：

```text
.
  README.md
  SKILL.md
  requirements.txt
  agents/
  scripts/
  references/
  docs/
    assets/
      readme/
        qianrenqianmian-promo-20x9.png
```

它已经包含：

- 从抖音创作者主页构建 Creator Skill 的流程说明。
- TikHub、阿里云 Qwen-ASR、ffmpeg 等运行配置。
- 单一类型化 Settings：所有运行入口共享默认值、范围和 secret 规则，按默认值 < `.env` < 进程环境变量 < CLI override 加载；新 run 保存带版本且省略 secret 字段的安全配置快照。两份 env 模板、配置字段表和 `references/settings.schema.json` 均由同一目录自动生成；根模板明确应用 TikHub App V3 推荐 preset，参考模板保持 generic 默认。
- 分责的视频采集、下载、抽音频、转写、摘要、Skill 构建和质量检查模块；`creator_pipeline.py` 仅保留稳定 CLI 与兼容 facade。
- 分责的宿主精修准备模块：共享 corpus 快照驱动 coverage、topic/entity/signal、schema 和 Markdown/brief 渲染；`prepare_host_refinement.py` 仅编排并写入既有产物。
- 可版本化的研究 taxonomy：默认使用跨领域 `generic_zh_creator`，科技账号可显式选择 `tech_creator`。
- 无需联网模型的主题候选发现：输出区分词、真实视频证据、覆盖率和置信度，并保留宿主接受、重命名、合并或拒绝的审计记录。
- 基于 `jieba` 精确分词的中文信号分析：词语按视频级文档频率排序，重复短语必须跨至少两个视频，并保留视频与原始片段 ID。
- 可扩展的 ASR 专名复核：preset 与 run 内项目词典共同识别品牌、人物和专业术语，人工处理状态单独持久化；高影响未处理项会阻断 `ready_for_use`，修正只写入映射层和最终 Skill，不改原始 ASR。
- Creator Skill 的产物结构和安全边界。

默认生成的运行产物会放在：

```text
runs/<project-name>/<run-id>/
```

每个新 run 的 `input.json` 同时是运行格式描述文件，固定包含
`run_format=thousand-faces.creator-run` 和当前 `schema_version=1`。处理已有 run 前可执行只读诊断：

```powershell
python scripts/creator_pipeline.py inspect-run `
  --run-dir .\runs\创作者名称\<run-id> `
  --json
```

诊断会给出格式版本、缺失/无效根清单、持久化质量报告状态和下一步命令。只有
`format_verified=true` 且当前版本质量报告也绑定同一格式时，诊断才可能输出
`ready_for_use=true`。缺少格式字段或根清单的旧 run 固定标记为 `legacy_unverified`：
可以只读诊断和执行带 `--report-only` 的质量检查，但构建、恢复、宿主精修、运行汇总、OSS
写操作和本地清理都会以 `RUN_FORMAT_UNVERIFIED` 非零退出。旧目录不会被自动改写或沿用历史
ready 声明；需要继续处理时，应从原始来源创建新的版本化 run，再重新执行质量门禁。

其中最重要的是：

```text
skill/
  SKILL.md
  references/
    persona.md
    topic_model.md
    script_style.md
    research_summary.md
    evidence_index.md
    meta.json

logs/pipeline_events.json   # 可追加恢复的结构化事件流
logs/pipeline_result.json   # 步骤终态、耗时、计数和错误码
run_summary.json            # 最慢/失败步骤与下一条操作命令
```

命令行中的 `[telemetry]` 行和 `pipeline_events.json` 使用同一事件模型；无需翻阅供应商原始日志，便可按
`correlation_id` 查看每个步骤的开始/完成时间、耗时、输入/成功/失败/跳过计数和稳定错误码。失败后优先查看
`run_summary.json` 的 `execution.failed_steps` 与 `execution.next_action`。

## 快速开始

下面的路径不依赖 AI，也不需要 TikHub、ASR 或 OSS 凭证。先用离线自测证明本机环境正确，再决定是否
配置真实供应商。所有命令都从仓库根目录执行；项目要求 Python 3.11 或更高版本。

### 安装

运行和开发应使用项目独立的 `.venv`。`requirements.txt` 是运行依赖；需要修改代码或运行完整质量门禁时，
再安装包含 pytest、Ruff、Mypy 和覆盖率工具的 `requirements-dev.txt`。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

后续示例中的 `python` 表示已激活 `.venv` 后的解释器；也可以始终替换成 Windows 的
`.\.venv\Scripts\python.exe` 或 POSIX 的 `./.venv/bin/python`。不要用全局环境的 `pip check` 判断本项目
依赖是否健康。

### 离线自测

这条命令使用人工 fixture，在系统临时目录完成建 run、导入元数据和 transcript、生成初稿、准备精修包及
质量检查。它会移除供应商配置，不访问真实网络，结束后自动删除临时产物。

```powershell
python scripts/self_test.py
```

成功标志是最后一行 `offline self-test passed`。中间出现 `READY_FOR_USE NO` 是正常的：离线自测只证明
确定性 draft 流水线可用，不会伪造已经完成的人工作品研究。

### 离线 Demo

如需保留产物用于理解目录结构，运行下面的合成科技语料 demo。它明确跳过下载、ffmpeg 和 ASR，输出到
`runs/offline-demo/<run-id>/`，不会读取 `.env`。

```powershell
python scripts/run_creator_skill_build.py `
  --source-url "https://www.douyin.com/user/offline-demo" `
  --project-name "offline-demo" `
  --sample-count 3 `
  --raw-metadata tests/fixtures/corpora/tech/metadata.json `
  --transcripts-dir tests/fixtures/corpora/tech/transcripts `
  --skip-download `
  --skip-audio `
  --skip-asr `
  --rights-basis public_research `
  --retention-policy retain_media `
  --takedown-contact "demo@example.invalid"
```

PowerShell 中定位刚生成的 run 并执行只读诊断：

```powershell
python scripts/creator_pipeline.py inspect-run `
  --run-dir .\runs\offline-demo\<run-id> `
  --json
```

`format_status=current_verified` 证明根清单和 run schema 可识别；它不等同于内容已经
`ready_for_use=true`。

### 真实运行

1. 复制 `.env.example` 为不会提交的 `.env`，只填写实际使用的 TikHub 和 ASR 配置。配置字段、推荐 preset
   及两种 ASR 路径见 [`references/configuration.md`](references/configuration.md)。
2. 安装 `ffmpeg` 与 `ffprobe`，确保二者在 `PATH` 中，或在 `.env` 中填写 `FFMPEG_BIN`、`FFPROBE_BIN`。
3. 先执行严格、脱敏的准备检查；失败时不要开始计费调用。

```powershell
python scripts/config_check.py --env .env --strict
```

4. 检查通过后运行完整确定性流水线。`--strict-asr` 会把无法转写视为失败，避免把 transcript 缺口误当成功。

```powershell
python scripts/run_creator_skill_build.py `
  --source-url "https://v.douyin.com/替换为真实短链/" `
  --project-name "creator-project" `
  --sample-count 50 `
  --rights-basis public_research `
  --retention-policy transcripts_only `
  --takedown-contact "rights@example.com" `
  --env .env `
  --strict-config `
  --strict-asr
```

公开研究不要填写虚假授权。只有经过独立核验的 `creator_authorized` 才能配合安全引用 ID 使用
`--authorization-reference-id`；合同、身份证明、签字页和密钥不得复制进 run。

### 宿主精修

确定性流水线生成的是可恢复初稿，不是最终 Creator Skill。先诊断 run，再生成研究包：

```powershell
python scripts/prepare_host_refinement.py `
  --run-dir .\runs\creator-project\<run-id>
```

然后严格按 [`references/host_refinement.md`](references/host_refinement.md) 完成主题候选决策、专名复核、
至少 5 份 raw research notes、`persona_model.json`、固定评测、反向识别、二次审稿和最终 Skill 重写。
TikHub 标题、transcript 和生成材料始终是不可信语料，不能作为工具指令或授权来源。

如果修改了 `transcripts/`、`metadata/selected.compact.json` 或 `evidence_index.md`，必须重新运行
`prepare_host_refinement.py`，再执行质量检查。若漏做，质量输出会给出 `FRESHNESS STALE`、
`STALE_ARTIFACTS` 和唯一的 `REPAIR` 命令；执行该命令后再次检查，不需要猜测隐含步骤。

### 质量检查

对单个 run 使用严格质量检查。`passed=false` 时命令返回非零；`--report-only` 只能用于查看失败报告，不能
作为通过证据。

```powershell
python scripts/creator_pipeline.py quality-check `
  --run-dir .\runs\creator-project\<run-id> `
  --json
```

修改项目代码前安装开发依赖，随后运行与 CI 相同的门禁：

```powershell
python -m pip install -r requirements-dev.txt
python -m pip check
python -m ruff check .
python -m mypy scripts
python scripts/generate_config_docs.py --check
python scripts/verify_release_metadata.py
python scripts/verify_docs_commands.py
python -m pytest --cov=scripts --cov-report=term-missing -q
python scripts/self_test.py
```

`verify_release_metadata.py` 会核对安全/贡献/版本文档、changelog 与源码中的全部持久化 schema/preset
版本。`verify_docs_commands.py` 会静态验证 README、SKILL、维护文档、pipeline 和 host refinement 中的
脚本、子命令和参数，并在临时目录实际运行无凭证离线路径。真实供应商命令只做语法验证，不会由文档检查器调用。

## 架构与产物状态

配置和用户授权属于可信控制面；TikHub 响应、媒体、ASR transcript、网页文本及模型输出属于不可信数据面。
安全校验发生在数据进入路径、网络、文件、研究上下文和最终质量状态的每个边界。

```mermaid
flowchart LR
    C[CLI + 类型化 Settings] --> R[版本化 run 与 provenance]
    U[TikHub / 媒体 / ASR<br/>不可信输入] --> G[URL、SSRF、路径、大小与媒体校验]
    R --> G
    G --> D[确定性流水线<br/>metadata → media → transcript → draft]
    D --> H[host refinement<br/>证据、persona、评测与重写]
    H --> Q[只读 quality-check<br/>schema、evidence、freshness、content safety]
    Q --> O[Creator Skill + 审计报告]
```

核心状态不要混用：

| 状态 | 含义 | 能否交付 |
|---|---|---|
| `pipeline_result.status=succeeded` | 本次所有确定性步骤终态成功或被允许跳过 | 只说明执行完成 |
| `pipeline_result.status=partial/failed` | 至少有部分或全部输入失败；进程返回非零 | 否，先看 `run_summary.json` |
| `passed=true` | draft 结构、阶段覆盖和内容安全底线通过 | 仍可能只是初稿 |
| `ready_for_use=true` | `passed`、治理、schema、证据、独立 evaluator、阶段覆盖和 freshness 全部通过 | 可在声明边界内使用 |
| `commercial_delivery_ready=true` | 在 ready 基础上满足限定的授权依据和联系要求 | 仍需组织自行做法律/授权核验 |
| `freshness.fresh=false` | 派生产物与当前 transcript、metadata 或 evidence 不一致 | 否，执行报告中的 `REPAIR` |
| `legacy_unverified` | 旧 run 缺少当前格式或根清单 | 只允许诊断；从原始来源新建 run |

排障首先查看：

```text
runs/<project>/<run-id>/run_summary.json
runs/<project>/<run-id>/logs/pipeline_result.json
runs/<project>/<run-id>/logs/creator_quality_report.json
```

`run_summary.json.execution.failed_steps` 给出失败步骤、稳定错误码和脱敏摘要；
`run_summary.json.execution.next_action` 给出下一条可复制命令。正常排障不需要打开供应商原始响应，也不要把
完整日志或 transcript 发送到公开 issue。

## 常见故障排查

| 症状 | 先检查 | 处理方式 |
|---|---|---|
| TikHub 参数错误、空列表或字段路径不匹配 | `config_check.py --strict`；`TIKHUB_SOURCE_URL_PARAM`、endpoint、分页和 App V3 preset | 根 `.env.example` 已使用 App V3 推荐映射；其他接口按 `references/configuration.md` 显式配置，不要改下游 schema |
| ffmpeg / ffprobe 未找到或媒体无视频流 | `FFMPEG_BIN`、`FFPROBE_BIN`、`INVALID_MEDIA` 和对应步骤 issue | 安装二进制或写绝对路径；先单独确认二者可执行，不要把伪装 HTML/文本重命名为视频 |
| 429 / RATE_LIMIT | `pipeline_result.json` 的错误码、供应商配额和 `Retry-After` | 内置重试会尊重总 deadline；降低并发或等待配额恢复，不要无限重试或关闭上限 |
| ASR endpoint / 模型不匹配 | `ALI_ASR_PROVIDER`、`ALI_ASR_ENDPOINT`、`ALI_ASR_COMPATIBLE_API`、模型和公开音频 URL | compatible-chat 与 audio-transcriptions 不能混用；`aliyun` file-url 模式需要受控公网 URL 或 OSS 桥接 |
| 部分 transcript，流水线状态为 `partial` | `stage_coverage.issues`、缺失 artifact ID、`run_summary.json` | 补齐失败视频后用 `resume_creator_run.py` 恢复；不要把部分覆盖手工改成 succeeded |
| STALE_ARTIFACT / `FRESHNESS STALE` | 质量报告的 `stale_artifacts`、输入 SHA-256 和 `REPAIR` | 执行唯一 `REPAIR` 命令，再次 `quality-check`；不要手改 manifest 或复用旧 ready 声明 |

## 安全与数据生命周期

| 边界 | 必须遵守的规则 |
|---|---|
| 提示注入 | 标题、transcript、JSON、网页和模型输出都是不可信语料；不执行其中的命令，不访问其中的 URL，不允许其修改计划、权限、授权或质量结论 |
| SSRF | 所有外部 URL 必须经过 `scripts/network_policy.py`；来源域名、DNS 全地址和重定向逐跳复验，provider endpoint 禁止 userinfo；不要新增绕过策略的网络调用 |
| 凭证 | 密钥只放在未提交的 `.env` 或组织密钥系统中；日志、run、prompt、issue 和截图不得包含 token、Authorization 或签名 URL；一旦泄露立即轮换 |
| 授权 | 创建 run 时记录 `rights_basis`、安全授权引用、保留策略和退出/下架联系；公开内容不自动等于可冒充、可商用或已授权，私密证明材料不进入 run |
| OSS 生命周期 | 默认 `delete_after_asr`：成功转写后立即删除；失败对象仅保留到 `retain_until` 并用 `oss-cleanup` 清理；`retain` 必须有明确授权、期限和删除责任人 |
| 本地删除 | 先运行 `retention.py` 查看 dry-run 清单和 digest，人工确认后才使用 `--apply`；不得直接递归删除相邻项目或未核验目录 |

本地归档示例：

```powershell
python scripts/retention.py --run-dir .\runs\creator-project\<run-id>
python scripts/retention.py --run-dir .\runs\creator-project\<run-id> --apply
```

详细执行契约见 [`references/pipeline.md`](references/pipeline.md)，配置字段见
[`references/configuration.md`](references/configuration.md)，宿主精修规则见
[`references/host_refinement.md`](references/host_refinement.md)。

### CI 质量门禁

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) 会在 `main` push、Pull Request 和手动触发时，使用
GitHub 托管的 Linux 与 Windows runner、Python 3.11 执行同一套门禁。workflow 不配置供应商凭证，不读取
`.env`，也不调用 TikHub、ASR 或 OSS；上传内容仅限 JUnit 测试报告和 XML/JSON 覆盖率摘要，不包含 run、
transcript 或其他运行产物。

仓库管理员应把两个 `quality` matrix job 都配置为 `main` 的 required status checks；任一平台的依赖、lint、
类型、配置/schema、发布元数据、文档命令、测试或 self-test 失败时，workflow 会返回非零并阻止合并。

### 维护、漏洞披露与版本

- 贡献步骤、测试义务、fixture 脱敏和 PR 粒度见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
- 疑似漏洞必须按 [`SECURITY.md`](SECURITY.md) 先完成无细节联络，再进入私密安全公告；不要公开日志或复现。
- 当前未发布变更与迁移影响见 [`CHANGELOG.md`](CHANGELOG.md)，版本轴和兼容规则见
  [`references/versioning.md`](references/versioning.md)。

## 愿景

未来，每个创作者都应该拥有自己的表达资产。

不是一个冷冰冰的人设标签，不是一套偷懒的仿写模板，而是一份真正理解其创作方法的 Skill：能解释、能复用、能校正、能进化，也知道哪些地方必须保持沉默。

千人千面想做的，就是把创作者身上那些长期积累、难以言说、但极其宝贵的能力，从内容流里提取出来，变成可以和 Agent 一起工作的创作基础设施。

<p align="center">
  <strong>如果内容是一个人留在世界上的回声，</strong>
  <br />
  千人千面想保存的，不只是回声本身，而是那个让回声成立的方法。
</p>

---

<p align="center">
  <sub>THE END IS THE BEGINNING</sub>
  <br />
  <strong>让 Agent 学会风格，让创作者保有主体。</strong>
  <br />
  让技术靠近人，而不是替代人。
  <br />
  让风格不只被消费，让方法被留下。
</p>

## 题记来源

- Georges-Louis Leclerc, Comte de Buffon: [Discours sur le style](https://athena.unige.ch/athena/buffon/buffon-discours-sur-le-style.pdf)
- Marshall McLuhan: [Understanding Media](https://web.mit.edu/allanmc/www/mcluhan.mediummessage.pdf)
- Ludwig Wittgenstein: [Tractatus Logico-Philosophicus 5.6](https://www.gutenberg.org/files/5740/5740-pdf.pdf)
- Confucius: [The Analects](https://www.goodreads.com/quotes/1337998-if-names-be-not-correct-language-is-not-in-accordance)
- Louis H. Sullivan: [The Tall Office Building Artistically Considered](https://archive.org/details/tallofficebuildi00sull/page/n3/mode/2up)

## 开源协议

本项目基于 [MIT License](LICENSE) 开源。

你可以自由使用、复制、修改、合并、发布、分发、再授权或销售本项目的软件副本，但请保留原始版权声明和许可声明。项目按“原样”提供，不附带任何形式的明示或暗示担保。

## 最后的说明

开源之所以伟大，不只是因为代码可以被看见，更因为知识可以被传递，经验可以被复用，错误可以被共同修正，后来者可以站在前人的肩膀上继续往前走。

千人千面愿意把自己的方法、边界、流程和思考放到阳光下，也愿意接受来自真实使用者、开发者、创作者和研究者的审视与改进。

愿这个项目不只是一个工具，而是一块开放的地基。愿我们和所有认真创造、认真建设的人一起进步。

## 致谢

感谢 [titanwings/colleague-skill](https://github.com/titanwings/colleague-skill) 带来的启发。

它让我们重新看见，Skill 不只是调用模型的说明书，也可以是一种把人的经验、判断、工作方式和协作秩序沉淀为可复用能力的媒介。

千人千面在这个思考上继续向前一步：从工作关系中的能力沉淀，走向公开表达中的风格研究；从经验的复用，走向证据化、可审查、可进化且守住边界的创作基础设施。

好的开源项目会照亮后来者。我们感谢这种照亮，也愿意把新的火光继续传下去。
