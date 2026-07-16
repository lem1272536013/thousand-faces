# 配置说明

所有供应商凭证、endpoint、模型名和并发参数都必须可配置。不要把真实密钥写进代码或文档示例。

运行配置统一由 `scripts/settings.py` 加载并类型化。优先级固定为：代码默认值 < `--env` 指定的
`.env` 文件 < 当前进程环境变量 < 显式 CLI override。布尔值只接受
`true/false`、`yes/no`、`on/off` 或 `1/0`；整数、浮点数和枚举在任何 run 目录创建前完成范围校验。
`ALI_ASR_PROVIDER` 允许 `openai-compatible`、`compatible`、`qwen-compatible`、`aliyun`，默认
provider/model 统一为 `openai-compatible` / `qwen3-asr-flash`；若显式选择 `aliyun` 且未配置
`ALI_ASR_MODEL`，模型默认值会由同一 Settings 规则派生为 `fun-asr`。HTTP endpoint 必须是无 userinfo、
无 fragment 的绝对 HTTP(S) URL；TikHub endpoint 必须是无 query、fragment 或 `..` 的相对路径。

每个新 run 的 `config.snapshot.json` 使用 `settings_schema_version=2`，保存规范化后的非敏感类型值；
secret 字段直接省略，非 secret 字段中误嵌的 token、签名参数和本机私有路径也会清理。旧 run 的平铺字符串
快照仍可用于质量诊断和阶段阈值读取。运行所需的原始 secret 只保留在进程环境中，不进入普通 Settings
序列化、`repr` 或 run 快照。

v2 删除了从未接入运行消费者的 `ALI_ASR_APP_KEY`、`AUTO_RESUME`、`MAX_INPUT_TOKENS` 和
`MAX_OUTPUT_TOKENS`。显式 `.env`、mapping 或 CLI override 若仍传入这些字段会在运行前给出迁移说明；
ASR 凭证改用 `ALI_ASR_API_KEY`/`DASHSCOPE_API_KEY`，恢复操作改用 `scripts/resume_creator_run.py`，
宿主模型的上下文与输出预算由宿主自身控制。

## 环境变量

<!-- BEGIN GENERATED SETTINGS REFERENCE -->
### 自动生成配置目录

以下内容由 `scripts/settings.py` 生成；请勿手工修改本区块。generic 默认值用于
`references/config.example.env`，根 `.env.example` 仅应用下列已命名 preset。

#### TikHub App V3 recommended preset

| 字段 | generic 默认 | App V3 推荐值 |
|---|---|---|
| `TIKHUB_API_BASE` | `—` | `https://api.tikhub.io` |
| `TIKHUB_CREATOR_VIDEOS_ENDPOINT` | `—` | `/api/v1/douyin/app/v3/fetch_user_post_videos` |
| `TIKHUB_SOURCE_URL_PARAM` | `url` | `sec_user_id` |
| `TIKHUB_LIMIT_PARAM` | `limit` | `count` |
| `TIKHUB_EXTRA_QUERY` | `—` | `max_cursor=0&sort_type=0` |

#### Settings 字段表

| 字段 | 分组 | 类型 | generic 默认 | 范围/选项 | secret | 层级 | 状态 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `TIKHUB_API_KEY` | `tikhub` | `string` | — | — | yes | standard | active | TikHub API credential. |
| `TIKHUB_API_BASE` | `tikhub` | `string` | — | — | no | standard | active | TikHub absolute HTTP API base URL. |
| `TIKHUB_CREATOR_VIDEOS_ENDPOINT` | `tikhub` | `string` | — | — | no | standard | active | TikHub creator-video relative endpoint path. |
| `TIKHUB_AUTH_HEADER` | `tikhub` | `string` | `Authorization` | — | no | advanced | active | TikHub authentication header name. |
| `TIKHUB_AUTH_SCHEME` | `tikhub` | `string` | `Bearer` | — | no | advanced | active | TikHub authentication scheme. |
| `TIKHUB_METADATA_FETCH_LIMIT` | `tikhub` | `integer` | `100` | `1..5000` | no | standard | active | Maximum metadata items requested. |
| `TIKHUB_SOURCE_URL_PARAM` | `tikhub` | `string` | `url` | — | no | standard | active | TikHub source URL query parameter. |
| `TIKHUB_AUTO_RESOLVE_DOUYIN_URL` | `tikhub` | `boolean` | `true` | — | no | standard | active | Resolve Douyin share URLs before TikHub calls. |
| `TIKHUB_LIMIT_PARAM` | `tikhub` | `string` | `limit` | — | no | standard | active | TikHub item-limit query parameter. |
| `TIKHUB_EXTRA_QUERY` | `tikhub` | `string` | — | — | no | advanced | active | Additional TikHub query string. |
| `TIKHUB_ITEMS_PATH` | `tikhub` | `string` | — | — | no | advanced | active | Optional dotted TikHub item-list path. |
| `TIKHUB_VIDEO_ID_PATH` | `tikhub` | `string` | — | — | no | advanced | active | Optional dotted TikHub video ID path. |
| `TIKHUB_VIDEO_TITLE_PATH` | `tikhub` | `string` | — | — | no | advanced | active | Optional dotted TikHub title path. |
| `TIKHUB_VIDEO_PUBLISHED_AT_PATH` | `tikhub` | `string` | — | — | no | advanced | active | Optional dotted TikHub publish-time path. |
| `TIKHUB_VIDEO_DOWNLOAD_URL_PATH` | `tikhub` | `string` | — | — | no | advanced | active | Optional dotted TikHub download URL path. |
| `TIKHUB_VIDEO_SOURCE_URL_PATH` | `tikhub` | `string` | — | — | no | advanced | active | Optional dotted TikHub source URL path. |
| `TIKHUB_CURSOR_PARAM` | `tikhub` | `string` | `max_cursor` | — | no | standard | active | TikHub pagination cursor field and query parameter. |
| `TIKHUB_ENABLE_PAGINATION` | `tikhub` | `boolean` | `true` | — | no | standard | active | Enable bounded TikHub cursor pagination. |
| `TIKHUB_MAX_PAGES` | `tikhub` | `integer` | `20` | `1..1000` | no | standard | active | Maximum TikHub pages per metadata request. |
| `ALI_ASR_PROVIDER` | `asr` | `enum` | `openai-compatible` | `openai-compatible`, `compatible`, `qwen-compatible`, `aliyun` | no | standard | active | ASR provider adapter selection. |
| `ALI_ASR_API_KEY` | `asr` | `string` | — | — | yes | standard | active | ASR provider credential. |
| `ALI_ASR_ENDPOINT` | `asr` | `string` | — | — | no | standard | active | OpenAI-compatible ASR absolute endpoint. |
| `ALI_ASR_MODEL` | `asr` | `string` | `qwen3-asr-flash` | — | no | standard | active | ASR model identifier. |
| `ALI_ASR_LANGUAGE` | `asr` | `string` | `zh-CN` | — | no | standard | active | ASR language hint. |
| `ALI_ASR_AUDIO_FORMAT` | `asr` | `string` | `mp3` | — | no | advanced | active | Extracted audio container suffix. |
| `ALI_ASR_RESPONSE_FORMAT` | `asr` | `string` | `json` | — | no | advanced | active | Compatible ASR response format. |
| `ALI_ASR_MIME_TYPE` | `asr` | `string` | `audio/mpeg` | — | no | advanced | active | Compatible ASR audio MIME type. |
| `ALI_ASR_COMPATIBLE_API` | `asr` | `enum` | `chat-completions` | `chat-completions`, `audio-transcriptions` | no | advanced | active | Compatible ASR request style. |
| `ALI_ASR_ENABLE_ITN` | `asr` | `boolean` | `false` | — | no | advanced | active | Enable inverse text normalization when supported. |
| `ALI_ASR_TIMEOUT_SECONDS` | `asr` | `integer` | `180` | `1..3600` | no | advanced | active | ASR request timeout in seconds. |
| `ALI_ASR_CONCURRENCY` | `asr` | `integer` | `4` | `1..16` | no | standard | active | Maximum concurrent ASR video tasks. |
| `ALI_ASR_MAX_BASE64_AUDIO_BYTES` | `asr` | `integer` | `8388608` | `1..33554432` | no | advanced | active | Maximum raw compatible-chat audio bytes per request. |
| `ALI_ASR_RETRY` | `asr` | `integer` | `3` | `1..20` | no | advanced | deprecated; use PROVIDER_RETRY_MAX_ATTEMPTS | Legacy ASR retry attempts. |
| `ALI_ASR_POLL_SECONDS` | `asr` | `float` | `5` | `0.1..3600` | no | advanced | active | DashScope polling interval in seconds. |
| `ALI_ASR_POLL_DEADLINE_SECONDS` | `asr` | `float` | `900` | `1..86400` | no | advanced | active | DashScope polling deadline in seconds. |
| `ALI_ASR_WAIT_MODE` | `asr` | `enum` | `wait` | `wait`, `poll` | no | advanced | active | Legacy bounded DashScope waiting mode. |
| `ALI_ASR_AUDIO_URL_TEMPLATE` | `asr` | `string` | — | — | no | advanced | active | Absolute public audio URL template for file-url ASR. |
| `AUDIO_PUBLIC_URL_BASE` | `asr` | `string` | — | — | no | advanced | active | Absolute public audio base URL. |
| `ASR_SAMPLE_RATE` | `asr` | `integer` | `16000` | `8000..384000` | no | advanced | active | Audio sample rate in hertz. |
| `ASR_MP3_BITRATE` | `asr` | `string` | `64k` | — | no | advanced | active | FFmpeg MP3 audio bitrate. |
| `ASR_SEGMENT_SECONDS` | `asr` | `integer` | `120` | `1..3600` | no | advanced | active | Maximum ASR segment duration in seconds. |
| `ALI_OSS_ENDPOINT` | `oss` | `string` | — | — | no | advanced | active | Aliyun OSS endpoint. |
| `ALI_OSS_BUCKET` | `oss` | `string` | — | — | no | advanced | active | Aliyun OSS bucket name. |
| `ALI_OSS_ACCESS_KEY_ID` | `oss` | `string` | — | — | yes | advanced | active | Aliyun OSS access-key identifier. |
| `ALI_OSS_ACCESS_KEY_SECRET` | `oss` | `string` | — | — | yes | advanced | active | Aliyun OSS access-key secret. |
| `ALI_OSS_PREFIX` | `oss` | `string` | `creator-agent-studio/audio` | — | no | advanced | active | Managed OSS object prefix. |
| `ALI_OSS_SIGNED_URL_EXPIRES` | `oss` | `integer` | `3600` | `60..3600` | no | advanced | active | OSS signed URL lifetime in seconds. |
| `ALI_OSS_LIFECYCLE_POLICY` | `oss` | `enum` | `delete_after_asr` | `delete_after_asr`, `retain` | no | advanced | active | Temporary OSS audio lifecycle mode. |
| `ALI_OSS_FAILURE_RETENTION_SECONDS` | `oss` | `integer` | `86400` | `60..2592000` | no | advanced | active | Failed ASR OSS retention window in seconds. |
| `DASHSCOPE_API_KEY` | `asr` | `string` | — | — | yes | standard | active | DashScope API credential. |
| `DASHSCOPE_BASE_HTTP_API_URL` | `asr` | `string` | — | — | no | standard | active | DashScope-compatible absolute HTTP API base URL. |
| `RUN_ROOT` | `runtime` | `string` | `runs` | — | no | standard | active | Default root directory for new runs. |
| `DOWNLOAD_CONCURRENCY` | `runtime` | `integer` | `6` | `1..32` | no | standard | active | Maximum concurrent video downloads. |
| `DOWNLOAD_RETRY` | `runtime` | `integer` | `3` | `1..20` | no | standard | active | Video download retry attempts. |
| `MAX_VIDEO_BYTES` | `runtime` | `integer` | `536870912` | `1..53687091200` | no | standard | active | Maximum bytes per downloaded video. |
| `DOWNLOAD_HEADER_TIMEOUT_SECONDS` | `runtime` | `integer` | `30` | `1..3600` | no | advanced | active | Download response-header timeout. |
| `DOWNLOAD_DEADLINE_SECONDS` | `runtime` | `integer` | `300` | `1..3600` | no | advanced | active | Total video download deadline. |
| `MEDIA_PROBE_TIMEOUT_SECONDS` | `runtime` | `integer` | `30` | `1..3600` | no | advanced | active | ffprobe media-validation timeout. |
| `HTTP_TIMEOUT_SECONDS` | `runtime` | `integer` | `60` | `1..3600` | no | advanced | active | Default provider request timeout. |
| `PROVIDER_RETRY_MAX_ATTEMPTS` | `recovery` | `integer` | `3` | `1..20` | no | advanced | active | Unified provider maximum attempts. |
| `PROVIDER_RETRY_BASE_SECONDS` | `recovery` | `float` | `1` | `0..3600` | no | advanced | active | Unified provider base backoff. |
| `PROVIDER_RETRY_MAX_SECONDS` | `recovery` | `float` | `10` | `0..3600` | no | advanced | active | Unified provider maximum backoff. |
| `PROVIDER_RETRY_JITTER_RATIO` | `recovery` | `float` | `0.2` | `0..1` | no | advanced | active | Unified provider retry jitter ratio. |
| `PROVIDER_REQUEST_DEADLINE_SECONDS` | `recovery` | `float` | `300` | `0.1..3600` | no | advanced | active | Unified logical request deadline. |
| `FFMPEG_BIN` | `runtime` | `string` | `ffmpeg` | — | no | advanced | active | FFmpeg executable name or path. |
| `FFMPEG_CONCURRENCY` | `runtime` | `integer` | `2` | `1..8` | no | standard | active | Maximum concurrent FFmpeg processes. |
| `FFPROBE_BIN` | `runtime` | `string` | `ffprobe` | — | no | advanced | active | ffprobe executable name or path. |
| `DRAFT_MIN_STAGE_COUNT` | `quality` | `integer` | `2` | `1..1000` | no | advanced | active | Minimum draft stage count. |
| `DRAFT_MIN_STAGE_RATIO` | `quality` | `float` | `0.8` | `0.01..1` | no | advanced | active | Minimum draft stage ratio. |
| `READY_MIN_STAGE_COUNT` | `quality` | `integer` | `5` | `1..1000` | no | advanced | active | Minimum ready stage count. |
| `READY_MIN_STAGE_RATIO` | `quality` | `float` | `0.95` | `0.01..1` | no | advanced | active | Minimum ready stage ratio. |
<!-- END GENERATED SETTINGS REFERENCE -->

上表和 `references/settings.schema.json` 是字段、默认值、范围、secret、层级及生命周期状态的权威参考。
根 `.env.example` 使用表中声明的 TikHub App V3 preset；`references/config.example.env` 保持 generic
默认。除该命名 preset 外，两份模板的字段和值不允许出现其他差异。

当 `TIKHUB_SOURCE_URL_PARAM=sec_user_id` 且输入是 `v.douyin.com` 短链或抖音主页链接时，`TIKHUB_AUTO_RESOLVE_DOUYIN_URL=true` 会先跟随跳转并提取 `sec_uid/sec_user_id`，再请求 TikHub。
分页使用响应中的 `TIKHUB_CURSOR_PARAM` 继续请求；达到样本 limit、供应商声明无更多数据、游标重复或
`TIKHUB_MAX_PAGES` 时立即停止。关闭 `TIKHUB_ENABLE_PAGINATION` 时只请求一页。

所有网络入口统一经过 SSRF 策略：

- 只接受 HTTP/HTTPS，拒绝 URL userinfo（`user:password@host`）。
- 创作者来源 URL 仅允许 `douyin.com`、`iesdouyin.com` 及其真实子域；类似
  `douyin.com.attacker.example` 的后缀混淆不会通过。
- TikHub 返回的媒体 URL 和 ASR 结果 URL 可使用任意公网域名，但 DNS 的全部 A/AAAA 结果都必须是
  全局可路由地址；任一结果属于 loopback、RFC1918、link-local、保留地址或云元数据地址即拒绝。
- TikHub、ASR、DashScope 和 OSS endpoint 属于受信配置，因此不使用业务域名 allowlist；但仍要求
  HTTP/HTTPS、公网 DNS 且禁止嵌入凭证。
- 无凭证的下载/短链/结果请求可以跟随重定向，但每一跳都会重新执行完整校验；携带 provider
  凭证的请求禁止重定向，避免 Authorization 被重放到新主机。
- 内置 urllib 链路连接到本次校验得到的固定 IP，HTTPS 仍使用原始 hostname 做 SNI 和证书校验，
  避免校验后再次解析形成 DNS rebinding 窗口；这些链路不继承系统 HTTP(S) 代理。
- 网络策略错误只显示 scheme、host 和非默认端口，不显示 URL 路径、查询字符串或 userinfo。

本策略会拒绝指向本机开发服务或企业私网的自定义 provider endpoint。需要本地 mock 时应在单元测试中
注入假 DNS/请求实现，不要为了测试关闭生产策略。

`ALI_ASR_PROVIDER=openai-compatible` 时，运行器会调用：

```text
<ALI_ASR_ENDPOINT>/chat/completions
```

这适用于 Qwen-ASR 兼容模式。adapter 会把 `input_audio` 作为 Base64 Data URL 发送。为了避免同步 ASR 单段限制，默认抽取 MP3，并通过 `ASR_SEGMENT_SECONDS=120` 自动切片。每个分片在读入和 Base64 编码前受 `ALI_ASR_MAX_BASE64_AUDIO_BYTES` 限制，默认 8 MiB、最大 32 MiB；compatible-chat 的 `ALI_ASR_CONCURRENCY × 分片上限` 不得超过 128 MiB 原始在途预算。超限时在编码前失败，并提示降低 `ASR_SEGMENT_SECONDS`。file-url/DashScope 路径不使用 Base64，不受组合预算影响。

TikHub、兼容 ASR、DashScope 查询和 OSS 请求共用 `PROVIDER_RETRY_*` 策略：最多尝试指定次数，
按指数退避并加入 jitter；HTTP 429 优先遵守 `Retry-After`，500/502/503/504 与连接、读取超时可重试，
认证或参数类 4xx 默认立即失败。`PROVIDER_REQUEST_DEADLINE_SECONDS` 是一次逻辑请求（包含退避等待）的总时限，
不是每次尝试的独立时限。旧的 `ALI_ASR_RETRY` 仅作为未设置统一次数参数时的兼容后备；视频下载仍使用
`DOWNLOAD_RETRY` 及其专用下载 deadline。

DashScope 异步任务由本地受控轮询统一等待；`ALI_ASR_POLL_DEADLINE_SECONDS` 是任务轮询总时限。
`ALI_ASR_WAIT_MODE=wait` 为兼容旧配置保留，但同样执行有界本地轮询。任务返回 `FAILED`、`CANCELED`
或未知状态时立即失败，不会继续无限等待。

`ALI_ASR_PROVIDER=aliyun` 时，DashScope 录音文件识别默认使用 `fun-asr`，并需要一个可访问的音频 URL。
如果显式设置了 `ALI_ASR_MODEL`，则始终以显式值为准。音频 URL 获取顺序：

1. `ALI_ASR_AUDIO_URL_TEMPLATE`
2. `AUDIO_PUBLIC_URL_BASE`
3. 使用 `ALI_OSS_*` 上传到 OSS 并生成签名 URL

不要把本地文件路径直接传给录音文件识别 adapter。

### OSS 临时音频生命周期

OSS 桥接只用于 `ALI_ASR_PROVIDER=aliyun` 的临时音频。对象键固定为：

```text
<prefix>/<project>/<run>/<video>/<chunk>/<source_sha256>.<ext>
```

project、run、video、chunk 和源文件 SHA-256 共同隔离对象；同名音频在不同 run 中不会互相覆盖。
签名 URL 只保存在进程内并直接传给 ASR，不写入 `logs/asr_status.json`、artifact manifest 或
`logs/oss_lifecycle.json`。生命周期清单只记录 bucket、受管 object key、源哈希、ASR 结果和清理状态。

| 策略/结果 | 行为 | 清单状态 |
|---|---|---|
| `delete_after_asr` + ASR 成功 | 转写稿和 manifest 成功落盘后立即删除 OSS 对象 | `deleted`；删除失败为 `cleanup_failed` |
| `delete_after_asr` + ASR 失败 | 保留 `ALI_OSS_FAILURE_RETENTION_SECONDS`，便于短期诊断 | `pending_expiry`，记录 `retain_until` |
| `retain` | 无论 ASR 成败都不自动删除 | `retained`，原因 `explicit_retain` |

默认策略是 `delete_after_asr`，失败保留 86400 秒（1 天）。`pending_expiry` 表示对象尚未删除；必须由
定时任务或运维人员在到期后执行清理：

```powershell
python scripts/provider_adapters.py --env .env oss-cleanup --run-dir <run目录>
```

清理器只删除当前 `ALI_OSS_PREFIX` 下、当前 bucket 与清单一致且已经到期的对象。删除失败会以脱敏后的
`OSS_CLEANUP_FAILED` 写入生命周期清单，并传播为 ASR workflow issue；不会回显凭证或签名参数。
`cleanup_failed` 保持可重试，后续再次运行 `oss-cleanup` 会重试删除，成功后记录
`cleanup_retry_succeeded`，但保留历史 issue 作为审计证据。
建议按失败保留窗口定期扫描仍活跃的 run。若组织从不使用 `retain`，还可在同一 prefix 上配置 OSS
服务端生命周期规则作为兜底；若需要显式长期保留，应使用独立 bucket/prefix，避免兜底规则误删。

临时音频包含完整语音内容，保留时间越长，隐私暴露面和存储/请求成本越高。`retain` 仅用于有明确
授权、保留期限和删除责任人的场景。OSS 凭证应只授予该 bucket/prefix 的上传、读取签名和删除权限，
不要使用跨 bucket 管理权限。

不要配置单独的研究用大模型 API 或假定本项目能限制宿主模型 token budget。加载此 skill 的宿主
agent 会读取转写稿和初版 skill，并由宿主自身的上下文/预算策略完成研究、归纳和优化。

### 研究 taxonomy（CLI）

研究关键词不是环境密钥，也不从 `.env` 选择。两个创建 run 的入口都接受：

```text
--taxonomy-preset generic_zh_creator|tech_creator
--taxonomy-version 1.0.0
```

- 默认 `generic_zh_creator`，只包含教程、案例、观点、风险边界等跨领域结构信号。
- `tech_creator` 保留科技创作者的 AI/Agent、工具、实验、硬件、现场、教育、安全和专名词典，必须显式选择。
- `--taxonomy-version` 可省略；创建时会解析当前注册版本，并把名称和精确版本共同写入 `input.json`。
- 未知 preset、请求版本不匹配，或 run 中只记录名称/版本之一时会在生成研究产物前失败。旧 run 若两个字段都没有，按 generic 兼容。
- 不根据标题或转写中偶然出现的 AI、品牌词自动切换 taxonomy。

每次执行 `prepare_host_refinement.py` 都会保留或创建 run 内的
`research/entity_dictionary.json`。它是项目级专名扩展，不是环境配置；可加入非科技品牌、人物、机构、
地点、产品和专业术语。修改后重新执行 prepare，旧 ASR 专名报告会被 freshness 判为 stale。示例：

```json
{
  "schema_version": 1,
  "entities": [
    {
      "canonical_term": "Nike",
      "aliases": ["耐克", "耐克 Nike"],
      "category": "brand",
      "impact": "high",
      "note": "项目中的高影响品牌"
    },
    {
      "canonical_term": "心房颤动",
      "aliases": ["房颤"],
      "category": "professional_term",
      "impact": "high",
      "note": "医学术语"
    }
  ]
}
```

`canonical_term`、别名和中英文混写会按 NFKC、大小写折叠及空格/点/横线/斜线等分隔符归一化；
不同实体不得占用同一归一化别名。`impact` 只能是 `high`、`medium` 或 `low`，`category` 使用
lower_snake_case。安全上限为 1 MiB、1000 个实体、每实体 50 个别名；该词典不得放入密码、凭证或个人隐私材料。

主题与短语发现无需新增环境配置或在线模型。`scripts/text_analysis.py` 固定使用运行依赖
`jieba==0.42.1` 的精确模式和随包 HMM 未登录词识别；该模型随依赖本地提供，不在运行时下载。
产物显式输出 tokenizer 名称/版本/模式、stopword 版本和 `minimum_video_appearances=2`，对应值也进入
artifact manifest。`pypinyin` 没有参与任何分析，已从运行依赖移除。

主题候选按视频级文档频率和共现生成；单视频候选保持 low 且整体为 `unclassified`，没有区分信号时
输出空候选和 `insufficient`。词语排名优先使用不同视频数，再参考标题 DF 和总频次；重复短语只在至少
两个不同视频出现时输出，同一视频内多次重复只增加 `total_frequency`，不能满足跨样本门槛。所有词语和
短语证据保留真实 `representative_video_ids` 与稳定 `source_fragment_ids`，不回退到领域词典编造分类。

阶段覆盖率门禁同时使用绝对数量和比例：每个必需阶段的实际要求为
`min(selected, max(min_count, ceil(selected * min_ratio)))`。默认 draft 要求至少
2 条且达到 80%，ready 要求至少 5 条且达到 95%；小样本会被 selected 上限收敛为全量覆盖。
`READY_*` 不得低于对应的 `DRAFT_*`。使用 `--transcripts-dir` 时，运行模式会显式记录为
`offline_transcripts`，downloaded/audio 不参与门禁，但 selected/transcribed 仍必须达标。

视频下载默认限制为单文件 512 MiB、响应头等待 30 秒、包含全部重试与退避的总下载 deadline
300 秒，ffprobe 最长运行 30 秒。`DOWNLOAD_DEADLINE_SECONDS` 不得小于
`DOWNLOAD_HEADER_TIMEOUT_SECONDS`。下载只接受完整 HTTP 200，以及 `video/*`、`application/mp4`、
`application/octet-stream` 或 `binary/octet-stream`；有 `Content-Length` 时必须为正数、不得超限且
必须与实际字节数一致，无长度头时仍按流式累计字节强制截断。任何失败都会删除 `.part`。

响应通过头部检查后仍不会直接成为缓存：`scripts/media_validation.py` 先拒绝明显 HTML/XML/JSON，
再用受协议、探测预算和超时限制的 ffprobe 验证正时长视频流、编码及尺寸。只有验证成功的文件才会
原子发布并写入包含 SHA-256、大小、格式、时长、音视频流数量、编码和分辨率的 artifact manifest。
同一批次的相同 video ID/URL 只下载一次；同 ID 不同 URL 会在网络请求前以
`DOWNLOAD_ID_CONFLICT` 失败，避免并发覆盖。

三个媒体阶段使用独立线程池：下载默认 6/最大 32，ffmpeg 默认 2/最大 8，ASR 默认 4/最大 16。`FFMPEG_CONCURRENCY` 应根据 CPU 核数、磁盘带宽和音频格式保守调整；三个值互不借用额度，某阶段调大不会隐式改变另一阶段。

平台视频 ID 与本地文件 ID 是两个字段：`platform_video_id` 原样用于证据回溯，`artifact_id` 是受限的
小写 ASCII 文件标识。映射写入 `metadata/video_id_map.json` 和
`metadata/selected.video_id_map.json`。包含路径分隔符、`..`、绝对/设备路径、Windows 保留名、控制字符、
尾随点或空格的平台 ID 会直接失败；归一化碰撞使用稳定哈希后缀隔离。下载、音频、ASR、转写、阶段覆盖和
宿主研究均只用 `artifact_id` 访问本地文件，并用 `resolve_within` 验证解析后路径仍在声明根目录内。
外部导入的旧转写稿可按合法平台 ID 命名，但导入时必须通过 selected 映射改名；无法验证的旧文件名不会
在下游被隐式接受。

环境变量的逐字段数值边界由上方自动生成表维护；越界、非法布尔或非整数会在创建 run 目录前返回非零。
CLI 自身另有两个边界：

| CLI 参数 | 允许范围 |
|---|---:|
| `--sample-count` | 1–1000 |
| `--metadata-fetch-limit` | 1–5000 |

Settings 还会校验跨字段关系：下载总 deadline 不得小于响应头 timeout，统一最大退避不得小于基础退避，
ready 阶段的数量和比例不得低于 draft，compatible-chat 的 ASR 并发数乘以单片原始音频上限不得超过
128 MiB。`ALI_ASR_RETRY` 已标记为 deprecated，仅在统一重试次数未显式配置时兼容回填；
新配置应使用 `PROVIDER_RETRY_MAX_ATTEMPTS`。

`--project-name` 不能为空；规范化后的 slug 最长 80 个字符。运行目录 ID 使用
UTC 毫秒时间戳加随机后缀，并以不可覆盖方式创建。

Python 依赖：

```powershell
pip install -r requirements.txt
```

外部命令：

```text
ffmpeg
ffprobe
```

## 脱敏规则

写入 `config.snapshot.json` 和普通 Settings 序列化时，secret 字段直接省略。只有显式执行
`config_check.py --include-config` 的诊断输出会保留 secret 字段名；已配置值固定显示 `<redacted>`，
未配置值保持空字符串，两者都不保留原值长度、前缀或后缀。Settings 的显式 secret 元数据覆盖以下类别：

```text
API_KEY / APP_KEY / PRIVATE_KEY / ACCESS_KEY
TOKEN
SECRET
PASSWORD
AUTHORIZATION / CREDENTIAL / SIGNATURE
COOKIE / SESSION
```

非 secret 配置中的 URL 同样删除 userinfo、fragment，以及 token、key、signature、credential、auth、sig、policy 等敏感 query 参数；普通 query 参数可以保留。错误、workflow note 和状态日志统一通过 scrubber 清理 Authorization/Bearer、已配置 secret、签名 URL 和本机绝对路径。

结构化运行日志不需要额外后端或配置。主运行与恢复运行会在 run 内原子写入
`logs/pipeline_events.json`，并把同一事件模型渲染为控制台 `[telemetry]` 行。事件只记录步骤标识、状态、
起止时间、毫秒耗时、四类计数、稳定错误码和最多 500 字符的脱敏摘要；不会持久化请求体、响应体、
签名 URL 或转写正文。`run_summary.json.execution.next_action.command` 是失败或待精修状态下的最短后续命令。

脱敏示例：

```text
<redacted>
```

## Adapter 规则

如果供应商 endpoint 或响应结构变化，优先修改 adapter 配置或 adapter 脚本。不要因为供应商变化而改研究提示、skill 模板或下游产物目录。

## 常用命令

只准备运行目录：

```powershell
python scripts/build_creator_skill.py `
  --source-url "https://v.douyin.com/xxx/" `
  --project-name "创作者名称" `
  --sample-count 50 `
  --rights-basis creator_authorized `
  --authorization-reference-id "AUTH-2026-001" `
  --authorization-note-path "governance/authorization-note.md" `
  --retention-policy transcripts_only `
  --takedown-contact "rights@example.com" `
  --env .env
```

运行确定性流水线：

```powershell
python scripts/run_creator_skill_build.py `
  --source-url "https://v.douyin.com/xxx/" `
  --project-name "创作者名称" `
  --sample-count 50 `
  --rights-basis public_research `
  --retention-policy final_skill_only `
  --takedown-contact "rights@example.com" `
  --env .env
```

`--rights-basis` 可选 `unspecified`、`public_research`、`creator_authorized`、`team_owned`；省略时明确记录为
`unspecified`，只允许 draft。`--authorization-note-path` 必须是当前工作目录下已存在的安全相对文件，run
只记录路径而不读取或复制文件内容。不要把合同、身份证明或签字内容放进 CLI、run 或日志。
`--retention-policy` 可选 `retain_media`、`transcripts_only`、`final_skill_only`。

本地保留清单默认 dry-run：

```powershell
python scripts/retention.py --run-dir .\runs\创作者名称\<run-id>
```

人工确认 `delete_paths` 后再显式执行：

```powershell
python scripts/retention.py `
  --run-dir .\runs\创作者名称\<run-id> `
  --apply
```

命令只接受 run 创建时记录的策略，清理结果写入 `logs/retention.json`。应用前会重建 inventory 并对整份计划做 run 内预检；每次真实 `unlink` 前还会重新检查父目录与符号链接/联接点。竞态或删除失败会停止不安全的后续操作，并在回执中记录 `partial`。不要直接用递归删除替代该流程。

修改 transcript、selected metadata、evidence 或 persona 后重新检查质量：

```powershell
python scripts/creator_pipeline.py quality-check `
  --run-dir .\runs\创作者名称\<run-id>
```

命令会实时重算当前覆盖并验证派生产物 manifest。若输出 `FRESHNESS STALE`，按随后打印的 `REPAIR`
命令重建，再执行一次 quality-check；不要手工编辑 manifest，也不要把 `passed=true` 当成 freshness 已通过。

检查真实运行准备情况：

```powershell
python scripts/config_check.py `
  --env .env `
  --include-config
```

供应商凭证未准备好时，可以使用已有元数据或转写稿：

```powershell
python scripts/run_creator_skill_build.py `
  --source-url "https://v.douyin.com/xxx/" `
  --project-name "创作者名称" `
  --raw-metadata .\raw.json `
  --transcripts-dir .\transcripts `
  --skip-download `
  --skip-audio `
  --skip-asr
```
