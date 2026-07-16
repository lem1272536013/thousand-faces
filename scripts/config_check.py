#!/usr/bin/env python3
"""Check local dependencies and live-run configuration."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import build_creator_skill
import provider_adapters
import settings


def check_package(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_config(args: argparse.Namespace) -> dict:
    active_settings = settings.load_settings(
        Path(args.env).expanduser() if args.env else None,
        install=True,
    )
    config = active_settings.as_env()
    missing = build_creator_skill.missing_required(config)
    validation_errors: list[str] = []

    ffmpeg_bin = config.get("FFMPEG_BIN", "ffmpeg")
    has_ffmpeg = shutil.which(ffmpeg_bin) is not None
    has_dashscope = check_package("dashscope")
    has_oss2 = check_package("oss2")
    has_requests = check_package("requests")
    has_oss_config = provider_adapters.oss_configured()
    has_audio_url = bool(config.get("AUDIO_PUBLIC_URL_BASE") or config.get("ALI_ASR_AUDIO_URL_TEMPLATE") or has_oss_config)
    has_tikhub = bool(config.get("TIKHUB_API_KEY") and config.get("TIKHUB_API_BASE") and config.get("TIKHUB_CREATOR_VIDEOS_ENDPOINT"))
    has_asr = bool((config.get("DASHSCOPE_API_KEY") or config.get("ALI_ASR_API_KEY")) and config.get("ALI_ASR_MODEL"))
    asr_provider = config.get("ALI_ASR_PROVIDER", settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]).lower()
    compatible_asr = asr_provider in {"openai-compatible", "compatible", "qwen-compatible"}
    has_compatible_asr = compatible_asr and has_requests and has_asr and bool(config.get("ALI_ASR_ENDPOINT") or config.get("DASHSCOPE_BASE_HTTP_API_URL"))

    checks = {
        "ffmpeg_available": has_ffmpeg,
        "dashscope_installed": has_dashscope,
        "oss2_installed": has_oss2,
        "requests_installed": has_requests,
        "oss_configured": has_oss_config,
        "tikhub_configured": has_tikhub,
        "aliyun_asr_configured": has_asr,
        "compatible_asr_configured": has_compatible_asr,
        "audio_public_url_configured": has_audio_url,
    }
    live_required = {
        "fetch": checks["tikhub_configured"],
        "download": checks["tikhub_configured"],
        "extract_audio": checks["ffmpeg_available"],
        "aliyun_asr": (
            checks["compatible_asr_configured"]
            if compatible_asr
            else checks["dashscope_installed"]
            and checks["aliyun_asr_configured"]
            and checks["audio_public_url_configured"]
            and (checks["oss2_installed"] or bool(config.get("AUDIO_PUBLIC_URL_BASE") or config.get("ALI_ASR_AUDIO_URL_TEMPLATE")))
        ),
        "agent_research": True,
    }
    report = {
        "passed": all(live_required.values()) and not missing and not validation_errors,
        "checks": checks,
        "live_required": live_required,
        "missing_required_config": missing,
        "config_validation_errors": validation_errors,
        "redacted_config": active_settings.diagnostic_dict() if args.include_config else {},
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Thousand Faces Style Skill live-run readiness")
    parser.add_argument("--env", help="Path to .env file")
    parser.add_argument("--include-config", action="store_true", help="Include redacted config snapshot")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when live-run readiness fails")
    args = parser.parse_args()

    try:
        report = check_config(args)
    except settings.SettingsError as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
