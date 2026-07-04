# 配置说明

所有供应商凭证、endpoint、模型名、token budget 和并发参数都必须可配置。不要把真实密钥写进代码或文档示例。

## 环境变量

TikHub：

```text
TIKHUB_API_KEY=
TIKHUB_API_BASE=
TIKHUB_CREATOR_VIDEOS_ENDPOINT=
TIKHUB_AUTH_HEADER=Authorization
TIKHUB_AUTH_SCHEME=Bearer
TIKHUB_METADATA_FETCH_LIMIT=100
TIKHUB_SOURCE_URL_PARAM=url
TIKHUB_AUTO_RESOLVE_DOUYIN_URL=true
TIKHUB_LIMIT_PARAM=limit
TIKHUB_EXTRA_QUERY=
TIKHUB_ITEMS_PATH=
TIKHUB_VIDEO_ID_PATH=
TIKHUB_VIDEO_TITLE_PATH=
TIKHUB_VIDEO_PUBLISHED_AT_PATH=
TIKHUB_VIDEO_DOWNLOAD_URL_PATH=
TIKHUB_VIDEO_SOURCE_URL_PATH=
```

TikHub 抖音 App V3 主页作品接口推荐配置：

```text
TIKHUB_API_BASE=https://api.tikhub.io
TIKHUB_CREATOR_VIDEOS_ENDPOINT=/api/v1/douyin/app/v3/fetch_user_post_videos
TIKHUB_SOURCE_URL_PARAM=sec_user_id
TIKHUB_LIMIT_PARAM=count
TIKHUB_EXTRA_QUERY=max_cursor=0&sort_type=0
```

当 `TIKHUB_SOURCE_URL_PARAM=sec_user_id` 且输入是 `v.douyin.com` 短链或抖音主页链接时，`TIKHUB_AUTO_RESOLVE_DOUYIN_URL=true` 会先跟随跳转并提取 `sec_uid/sec_user_id`，再请求 TikHub。

阿里云 ASR：

```text
ALI_ASR_PROVIDER=openai-compatible
ALI_ASR_API_KEY=
DASHSCOPE_API_KEY=
ALI_ASR_APP_KEY=
ALI_ASR_ENDPOINT=
DASHSCOPE_BASE_HTTP_API_URL=
ALI_ASR_MODEL=qwen3-asr-flash
ALI_ASR_LANGUAGE=zh-CN
ALI_ASR_AUDIO_FORMAT=mp3
ALI_ASR_RESPONSE_FORMAT=json
ALI_ASR_MIME_TYPE=audio/mpeg
ALI_ASR_COMPATIBLE_API=chat-completions
ALI_ASR_ENABLE_ITN=false
ALI_ASR_TIMEOUT_SECONDS=180
ALI_ASR_CONCURRENCY=4
ALI_ASR_POLL_SECONDS=5
ALI_ASR_WAIT_MODE=wait
ALI_ASR_AUDIO_URL_TEMPLATE=
AUDIO_PUBLIC_URL_BASE=
ASR_SAMPLE_RATE=16000
ASR_MP3_BITRATE=64k
ASR_SEGMENT_SECONDS=120
ALI_OSS_ENDPOINT=
ALI_OSS_BUCKET=
ALI_OSS_ACCESS_KEY_ID=
ALI_OSS_ACCESS_KEY_SECRET=
ALI_OSS_PREFIX=creator-agent-studio/audio
ALI_OSS_SIGNED_URL_EXPIRES=3600
```

`ALI_ASR_PROVIDER=openai-compatible` 时，运行器会调用：

```text
<ALI_ASR_ENDPOINT>/chat/completions
```

这适用于 Qwen-ASR 兼容模式。adapter 会把 `input_audio` 作为 Base64 Data URL 发送。为了避免同步 ASR 单段限制，默认抽取 MP3，并通过 `ASR_SEGMENT_SECONDS=120` 自动切片。

`ALI_ASR_PROVIDER=aliyun` 时，DashScope 录音文件识别需要一个可访问的音频 URL。音频 URL 获取顺序：

1. `ALI_ASR_AUDIO_URL_TEMPLATE`
2. `AUDIO_PUBLIC_URL_BASE`
3. 使用 `ALI_OSS_*` 上传到 OSS 并生成签名 URL

不要把本地文件路径直接传给录音文件识别 adapter。

Agent 研究参数：

```text
MAX_INPUT_TOKENS=120000
MAX_OUTPUT_TOKENS=8000
```

不要配置单独的研究用大模型 API。加载此 skill 的 Codex 或 Claude Code 会读取转写稿和初版 skill，并用宿主模型完成研究、归纳和优化。

运行参数：

```text
RUN_ROOT=runs
DOWNLOAD_CONCURRENCY=6
DOWNLOAD_RETRY=3
HTTP_TIMEOUT_SECONDS=60
FFMPEG_BIN=ffmpeg
FFPROBE_BIN=ffprobe
AUTO_RESUME=true
```

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

写入 `config.snapshot.json` 时，以下关键词对应的值必须脱敏：

```text
KEY
TOKEN
SECRET
PASSWORD
AUTH
ACCESS
```

脱敏示例：

```text
sk-1...abcd
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
  --env .env
```

运行确定性流水线：

```powershell
python scripts/run_creator_skill_build.py `
  --source-url "https://v.douyin.com/xxx/" `
  --project-name "创作者名称" `
  --sample-count 50 `
  --env .env
```

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
