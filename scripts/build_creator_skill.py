#!/usr/bin/env python3
"""Bootstrap a Thousand Faces Style Skill run.

This script intentionally keeps provider calls behind configuration. It prepares
the run layout, validates required knobs, writes redacted config, and records the
fixed pipeline plan so TikHub and Aliyun ASR adapters can be added without
changing downstream research or skill-generation modules.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


SECRET_KEY_FRAGMENTS = (
    "API_KEY",
    "APP_KEY",
    "SECRET",
    "PASSWORD",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
)

CONFIG_KEYS = (
    "TIKHUB_API_KEY",
    "TIKHUB_API_BASE",
    "TIKHUB_CREATOR_VIDEOS_ENDPOINT",
    "TIKHUB_AUTH_HEADER",
    "TIKHUB_AUTH_SCHEME",
    "TIKHUB_METADATA_FETCH_LIMIT",
    "TIKHUB_SOURCE_URL_PARAM",
    "TIKHUB_AUTO_RESOLVE_DOUYIN_URL",
    "TIKHUB_LIMIT_PARAM",
    "TIKHUB_EXTRA_QUERY",
    "TIKHUB_ITEMS_PATH",
    "TIKHUB_VIDEO_ID_PATH",
    "TIKHUB_VIDEO_TITLE_PATH",
    "TIKHUB_VIDEO_PUBLISHED_AT_PATH",
    "TIKHUB_VIDEO_DOWNLOAD_URL_PATH",
    "TIKHUB_VIDEO_SOURCE_URL_PATH",
    "ALI_ASR_PROVIDER",
    "ALI_ASR_API_KEY",
    "ALI_ASR_APP_KEY",
    "ALI_ASR_ENDPOINT",
    "ALI_ASR_MODEL",
    "ALI_ASR_LANGUAGE",
    "ALI_ASR_AUDIO_FORMAT",
    "ALI_ASR_RESPONSE_FORMAT",
    "ALI_ASR_MIME_TYPE",
    "ALI_ASR_COMPATIBLE_API",
    "ALI_ASR_ENABLE_ITN",
    "ALI_ASR_TIMEOUT_SECONDS",
    "ALI_ASR_CONCURRENCY",
    "ALI_ASR_POLL_SECONDS",
    "ALI_ASR_WAIT_MODE",
    "ALI_ASR_AUDIO_URL_TEMPLATE",
    "AUDIO_PUBLIC_URL_BASE",
    "ASR_SAMPLE_RATE",
    "ASR_MP3_BITRATE",
    "ASR_SEGMENT_SECONDS",
    "ALI_OSS_ENDPOINT",
    "ALI_OSS_BUCKET",
    "ALI_OSS_ACCESS_KEY_ID",
    "ALI_OSS_ACCESS_KEY_SECRET",
    "ALI_OSS_PREFIX",
    "ALI_OSS_SIGNED_URL_EXPIRES",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_HTTP_API_URL",
    "MAX_INPUT_TOKENS",
    "MAX_OUTPUT_TOKENS",
    "RUN_ROOT",
    "DOWNLOAD_CONCURRENCY",
    "DOWNLOAD_RETRY",
    "HTTP_TIMEOUT_SECONDS",
    "FFMPEG_BIN",
    "FFPROBE_BIN",
    "AUTO_RESUME",
)

DEFAULTS = {
    "TIKHUB_AUTH_HEADER": "Authorization",
    "TIKHUB_AUTH_SCHEME": "Bearer",
    "TIKHUB_METADATA_FETCH_LIMIT": "100",
    "TIKHUB_SOURCE_URL_PARAM": "url",
    "TIKHUB_AUTO_RESOLVE_DOUYIN_URL": "true",
    "TIKHUB_LIMIT_PARAM": "limit",
    "ALI_ASR_PROVIDER": "openai-compatible",
    "ALI_ASR_MODEL": "qwen3-asr-flash",
    "ALI_ASR_LANGUAGE": "zh-CN",
    "ALI_ASR_AUDIO_FORMAT": "mp3",
    "ALI_ASR_RESPONSE_FORMAT": "json",
    "ALI_ASR_MIME_TYPE": "audio/mpeg",
    "ALI_ASR_COMPATIBLE_API": "chat-completions",
    "ALI_ASR_ENABLE_ITN": "false",
    "ALI_ASR_TIMEOUT_SECONDS": "180",
    "ALI_ASR_CONCURRENCY": "4",
    "ALI_ASR_POLL_SECONDS": "5",
    "ALI_ASR_WAIT_MODE": "wait",
    "ALI_OSS_PREFIX": "creator-agent-studio/audio",
    "ALI_OSS_SIGNED_URL_EXPIRES": "3600",
    "MAX_INPUT_TOKENS": "120000",
    "MAX_OUTPUT_TOKENS": "8000",
    "RUN_ROOT": "runs",
    "DOWNLOAD_CONCURRENCY": "6",
    "DOWNLOAD_RETRY": "3",
    "HTTP_TIMEOUT_SECONDS": "60",
    "FFMPEG_BIN": "ffmpeg",
    "FFPROBE_BIN": "ffprobe",
    "AUTO_RESUME": "true",
    "ASR_MP3_BITRATE": "64k",
    "ASR_SEGMENT_SECONDS": "120",
}

PIPELINE_STEPS = [
    "parse_creator_url",
    "fetch_creator_videos_with_tikhub",
    "select_recent_samples",
    "download_videos",
    "extract_audio_with_ffmpeg",
    "transcribe_with_aliyun_asr",
    "normalize_transcripts",
    "research_creator_style",
    "build_creator_skill",
    "quality_check",
]


def load_env_file(path: Path | None) -> None:
    if not path:
        return
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value.strip())
    normalized = re.sub(r"-+", "-", normalized).strip("-_").lower()
    return normalized or "creator"


def now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def collect_config() -> dict[str, str]:
    config = dict(DEFAULTS)
    for key in CONFIG_KEYS:
        value = os.environ.get(key)
        if value is not None:
            config[key] = value
    return config


def is_secret_key(key: str) -> bool:
    upper = key.upper()
    return (
        any(fragment in upper for fragment in SECRET_KEY_FRAGMENTS)
        or upper == "TOKEN"
        or upper.endswith("_TOKEN")
    )


def redact_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def redact_config(config: dict[str, str]) -> dict[str, str]:
    return {
        key: redact_value(value) if is_secret_key(key) else value
        for key, value in sorted(config.items())
    }


def ensure_run_layout(run_dir: Path) -> None:
    dirs = [
        "metadata",
        "media/videos",
        "media/audio",
        "transcripts/raw_json",
        "research/raw",
        "research/merged",
        "research/reviews",
        "skill/references",
        "logs",
    ]
    for relative in dirs:
        (run_dir / relative).mkdir(parents=True, exist_ok=True)


def missing_required(config: dict[str, str]) -> list[str]:
    required = [
        "TIKHUB_API_KEY",
        "TIKHUB_API_BASE",
        "TIKHUB_CREATOR_VIDEOS_ENDPOINT",
        "ALI_ASR_MODEL",
    ]
    missing = [key for key in required if not config.get(key)]
    if not (config.get("DASHSCOPE_API_KEY") or config.get("ALI_ASR_API_KEY")):
        missing.append("DASHSCOPE_API_KEY or ALI_ASR_API_KEY")
    asr_provider = config.get("ALI_ASR_PROVIDER", "aliyun").lower()
    if asr_provider in {"openai-compatible", "compatible", "qwen-compatible"} and not (
        config.get("ALI_ASR_ENDPOINT") or config.get("DASHSCOPE_BASE_HTTP_API_URL")
    ):
        missing.append("ALI_ASR_ENDPOINT or DASHSCOPE_BASE_HTTP_API_URL")
    return missing


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_run(args: argparse.Namespace, config: dict[str, str]) -> Path:
    project_slug = slugify(args.project_name or "creator")
    run_root = Path(args.run_root or config["RUN_ROOT"]).expanduser()
    run_dir = run_root / project_slug / now_id()
    ensure_run_layout(run_dir)

    input_payload = {
        "platform": "douyin",
        "source_url": args.source_url,
        "project_name": args.project_name,
        "sample_count": args.sample_count,
        "metadata_fetch_limit": args.metadata_fetch_limit or int(config["TIKHUB_METADATA_FETCH_LIMIT"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    plan_payload = {
        "workflow_id": "creator_skill_build_v1_skill_first",
        "status": "planned",
        "steps": [{"step_id": step, "status": "pending"} for step in PIPELINE_STEPS],
    }

    write_json(run_dir / "input.json", input_payload)
    write_json(run_dir / "config.snapshot.json", redact_config(config))
    write_json(run_dir / "workflow.plan.json", plan_payload)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a Thousand Faces Style Skill run")
    parser.add_argument("--source-url", required=True, help="Douyin creator profile URL")
    parser.add_argument("--project-name", required=True, help="Project or creator slug")
    parser.add_argument("--sample-count", type=int, default=50, help="Number of recent videos")
    parser.add_argument("--metadata-fetch-limit", type=int, help="TikHub metadata fetch limit")
    parser.add_argument("--run-root", help="Override run root")
    parser.add_argument("--env", help="Path to .env file")
    parser.add_argument(
        "--strict-config",
        action="store_true",
        help="Fail if provider and model configuration is incomplete",
    )
    args = parser.parse_args()

    load_env_file(Path(args.env).expanduser() if args.env else None)
    config = collect_config()
    missing = missing_required(config)
    if args.strict_config and missing:
        raise SystemExit("missing required config: " + ", ".join(missing))

    run_dir = create_run(args, config)
    print(run_dir)
    if missing:
        print("warning: missing config for full execution: " + ", ".join(missing))
    print("prepared workflow.plan.json; provider adapters are configured separately")


if __name__ == "__main__":
    main()
