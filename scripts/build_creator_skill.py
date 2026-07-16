#!/usr/bin/env python3
"""Bootstrap a Thousand Faces Style Skill run.

This script intentionally keeps provider calls behind configuration. It prepares
the run layout, validates required knobs, writes redacted config, and records the
fixed pipeline plan so TikHub and Aliyun ASR adapters can be added without
changing downstream research or skill-generation modules.
"""

from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import redaction
import provenance
import research_taxonomy
import run_diagnostics
import settings
from input_validation import (
    InputValidationError,
    metadata_fetch_limit_argument,
    normalize_project_slug,
    project_name_argument,
    sample_count_argument,
    validate_run_inputs,
)
from io_utils import atomic_write_json as write_json


CONFIG_KEYS = settings.CONFIG_KEYS
DEFAULTS = dict(settings.DEFAULT_ENV)

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

RUN_ID_CREATE_ATTEMPTS = 10


def add_taxonomy_arguments(parser: argparse.ArgumentParser) -> None:
    """Expose one consistent taxonomy contract on every run-creation CLI."""

    parser.add_argument(
        "--taxonomy-preset",
        default=research_taxonomy.DEFAULT_TAXONOMY_PRESET,
        help=(
            "Versioned research taxonomy preset; available: "
            + ", ".join(research_taxonomy.available_taxonomy_presets())
        ),
    )
    parser.add_argument(
        "--taxonomy-version",
        help="Require an exact preset version; omitted uses the current registered version",
    )


load_env_file = settings.load_env_file


def slugify(value: str) -> str:
    return normalize_project_slug(value) or "creator"


def now_id() -> str:
    now = datetime.now(timezone.utc)
    timestamp = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z"
    return f"{timestamp}-{uuid.uuid4().hex}"


def collect_config() -> dict[str, str]:
    return settings.load_settings(environment=os.environ).as_env()


def is_secret_key(key: str) -> bool:
    return redaction.is_secret_key(key)


def redact_value(value: str) -> str:
    return redaction.redact_secret(value)


def redact_config(config: dict[str, str]) -> dict[str, str]:
    return redaction.redact_config(config)


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


def missing_required(config: settings.Settings | dict[str, str]) -> list[str]:
    values = config.as_env() if isinstance(config, settings.Settings) else config
    required = [
        "TIKHUB_API_KEY",
        "TIKHUB_API_BASE",
        "TIKHUB_CREATOR_VIDEOS_ENDPOINT",
        "ALI_ASR_MODEL",
    ]
    missing = [key for key in required if not values.get(key)]
    if not (values.get("DASHSCOPE_API_KEY") or values.get("ALI_ASR_API_KEY")):
        missing.append("DASHSCOPE_API_KEY or ALI_ASR_API_KEY")
    asr_provider = values.get("ALI_ASR_PROVIDER", settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]).lower()
    if asr_provider in {"openai-compatible", "compatible", "qwen-compatible"} and not (
        values.get("ALI_ASR_ENDPOINT") or values.get("DASHSCOPE_BASE_HTTP_API_URL")
    ):
        missing.append("ALI_ASR_ENDPOINT or DASHSCOPE_BASE_HTTP_API_URL")
    return missing


def create_run(
    args: argparse.Namespace,
    config: settings.Settings | dict[str, str],
) -> Path:
    active_settings = config if isinstance(config, settings.Settings) else settings.Settings.from_mapping(config)
    config_values = active_settings.as_env()
    validated = validate_run_inputs(
        args.project_name,
        args.sample_count,
        args.metadata_fetch_limit,
        config_values,
    )
    try:
        taxonomy = research_taxonomy.get_taxonomy_preset(
            getattr(args, "taxonomy_preset", None),
            getattr(args, "taxonomy_version", None),
        )
    except research_taxonomy.TaxonomyPresetError as error:
        raise InputValidationError(str(error)) from error
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        governance = provenance.build_run_record(
            args,
            source_platform="douyin",
            source_collected_at=created_at,
        )
    except provenance.ProvenanceError as error:
        raise InputValidationError(str(error)) from error
    run_root = Path(args.run_root or config_values["RUN_ROOT"]).expanduser()
    project_run_root = run_root / validated.project_slug
    project_run_root.mkdir(parents=True, exist_ok=True)
    run_dir: Path | None = None
    for _ in range(RUN_ID_CREATE_ATTEMPTS):
        candidate = project_run_root / now_id()
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        run_dir = candidate
        break
    if run_dir is None:
        raise RuntimeError(
            f"unable to create a unique run directory after {RUN_ID_CREATE_ATTEMPTS} attempts under {project_run_root}"
        )
    ensure_run_layout(run_dir)

    input_payload = {
        "run_format": run_diagnostics.RUN_FORMAT_NAME,
        "schema_version": run_diagnostics.RUN_FORMAT_SCHEMA_VERSION,
        "platform": "douyin",
        "project_name": validated.project_name,
        "sample_count": validated.sample_count,
        "metadata_fetch_limit": validated.metadata_fetch_limit,
        "created_at": created_at,
        "execution_mode": (
            "offline_transcripts"
            if getattr(args, "transcripts_dir", None)
            else "online_media"
        ),
        "taxonomy_preset": taxonomy.name,
        "taxonomy_version": taxonomy.version,
        **provenance.input_fields(governance),
    }
    plan_payload = {
        "schema_version": 1,
        "workflow_id": "creator_skill_build_v1_skill_first",
        "status": "planned",
        "final_status": "pending",
        "created_at": created_at,
        "updated_at": created_at,
        "steps": [{"step_id": step, "status": "pending"} for step in PIPELINE_STEPS],
    }

    write_json(run_dir / "input.json", input_payload)
    provenance.write_run_manifest(run_dir, governance)
    write_json(run_dir / "config.snapshot.json", active_settings.snapshot())
    write_json(run_dir / "workflow.plan.json", plan_payload)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a Thousand Faces Style Skill run")
    parser.add_argument("--source-url", required=True, help="Douyin creator profile URL")
    parser.add_argument("--project-name", required=True, type=project_name_argument, help="Project or creator slug")
    parser.add_argument("--sample-count", type=sample_count_argument, default=50, help="Number of recent videos (1-1000)")
    parser.add_argument(
        "--metadata-fetch-limit",
        type=metadata_fetch_limit_argument,
        help="TikHub metadata fetch limit (1-5000)",
    )
    parser.add_argument("--run-root", help="Override run root")
    parser.add_argument("--env", help="Path to .env file")
    add_taxonomy_arguments(parser)
    parser.add_argument(
        "--rights-basis",
        choices=provenance.RIGHTS_BASES,
        default="unspecified",
        help="Auditable source-rights basis; unspecified is draft-only",
    )
    parser.add_argument(
        "--authorization-reference-id",
        help="Reference ID only; never place contract or identity-document content here",
    )
    parser.add_argument(
        "--authorization-note-path",
        help="Safe relative local note path; the referenced file is never copied into the run",
    )
    parser.add_argument(
        "--retention-policy",
        choices=provenance.RETENTION_POLICIES,
        default="retain_media",
    )
    parser.add_argument(
        "--takedown-contact",
        default=provenance.TAKEDOWN_CONTACT_NOT_PROVIDED,
        help="Single-line opt-out/takedown contact or internal route",
    )
    parser.add_argument(
        "--strict-config",
        action="store_true",
        help="Fail if provider and model configuration is incomplete",
    )
    args = parser.parse_args()

    try:
        active_settings = settings.load_settings(
            Path(args.env).expanduser() if args.env else None,
            overrides={"RUN_ROOT": args.run_root},
            install=True,
        )
    except settings.SettingsError as exc:
        parser.error(str(exc))
    config = active_settings.as_env()
    missing = missing_required(config)
    if args.strict_config and missing:
        raise SystemExit("missing required config: " + ", ".join(missing))

    try:
        run_dir = create_run(args, active_settings)
    except InputValidationError as exc:
        parser.error(str(exc))
    print(run_dir)
    if missing:
        print("warning: missing config for full execution: " + ", ".join(missing))
    print("prepared workflow.plan.json; provider adapters are configured separately")


if __name__ == "__main__":
    main()
