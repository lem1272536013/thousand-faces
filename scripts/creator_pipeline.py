#!/usr/bin/env python3
"""CLI routing and compatibility facade for the creator pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess as subprocess
import sys
import time as time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

import artifacts as artifacts
import content_safety as content_safety
import creator_media
import creator_quality
import entity_review as entity_review
import evidence_model as evidence_model
import logging_utils
import media_validation as media_validation
import network_policy as network_policy
import path_policy as path_policy
import provenance as provenance
import quality_engine as quality_engine
import redaction
import run_diagnostics
import schema_validation as schema_validation
import settings
import text_analysis as text_analysis
from asr_parsers import ASRParseError as ASRParseError
from creator_media import (
    DownloadValidationError as DownloadValidationError,
    asr_json_to_transcript as asr_json_to_transcript,
    audio_artifact_spec as audio_artifact_spec,
    download_artifact_spec as download_artifact_spec,
    download_one as download_one,
    download_response_metadata as download_response_metadata,
    download_videos_step as download_videos_step,
    extract_audio_step as extract_audio_step,
    extract_terms as extract_terms,
    ffmpeg_version as ffmpeg_version,
    stream_download_response as stream_download_response,
    summarize_transcripts as summarize_transcripts,
    summarize_transcripts_step as summarize_transcripts_step,
    validate_download_response as validate_download_response,
)
from creator_metadata import (
    candidate_author_dicts as candidate_author_dicts,
    collect_candidate_lists as collect_candidate_lists,
    compact_metadata_item as compact_metadata_item,
    extract_creator_profile as extract_creator_profile,
    extract_url as extract_url,
    find_first_key as find_first_key,
    first_value as first_value,
    get_path as get_path,
    infer_video_items as infer_video_items,
    is_bad_profile_value as is_bad_profile_value,
    normalize_metadata as normalize_metadata,
    normalize_timestamp as normalize_timestamp,
    read_json as read_json,
    safe_filename as safe_filename,
    select_samples as select_samples,
)
from creator_quality import (
    compute_persona_model_stats as compute_persona_model_stats,
    creator_content_readiness as creator_content_readiness,
    creator_quality_check_step as creator_quality_check_step,
    extract_video_ids_from_value as extract_video_ids_from_value,
    generic_template_stats as generic_template_stats,
    has_mojibake as has_mojibake,
    host_refinement_stats as host_refinement_stats,
    markdown_heading_count as markdown_heading_count,
    markdown_nonempty_bullets as markdown_nonempty_bullets,
    markdown_table_rows as markdown_table_rows,
    nonempty_items as nonempty_items,
    persona_model_stats as persona_model_stats,
    raw_research_note_stats as raw_research_note_stats,
)
from input_validation import sample_count_argument
from io_utils import atomic_write_json as write_json
from pipeline_models import PipelineResult, StepResult as StepResult
from skill_builder import (
    build_creator_skill as build_creator_skill,
    build_creator_skill_step as build_creator_skill_step,
)
from stage_coverage import evaluate_stage_coverage as evaluate_stage_coverage


WORKFLOW_SCHEMA_VERSION = 1
WORKFLOW_RECOVERY_ERROR = Path("logs") / "workflow_recovery_error.json"


class WorkflowStateError(RuntimeError):
    """Raised when workflow state cannot be read or durably updated."""


def raise_workflow_state_error(
    run_dir: Path,
    workflow_path: Path,
    step_id: str,
    status: str,
    message: str,
    error: BaseException,
) -> NoReturn:
    """Persist a bounded recovery diagnostic, report it, and stop the caller."""

    occurred_at = datetime.now(timezone.utc).isoformat()
    workflow_display = redaction.safe_relative_path(workflow_path, run_dir)
    safe_error = redaction.scrub_text(error, limit=500)
    diagnostic = f"{message}: {workflow_display} ({type(error).__name__}: {safe_error})"
    print(f"[workflow] ERROR {diagnostic}", file=sys.stderr)
    recovery_path = run_dir / WORKFLOW_RECOVERY_ERROR
    try:
        write_json(
            recovery_path,
            {
                "schema_version": WORKFLOW_SCHEMA_VERSION,
                "occurred_at": occurred_at,
                "workflow_path": workflow_display,
                "operation": {"step_id": step_id, "status": status},
                "error": {"type": type(error).__name__, "message": safe_error},
            },
        )
    except OSError as recovery_error:
        print(
            "[workflow] ERROR could not persist recovery diagnostic: "
            f"{redaction.safe_relative_path(recovery_path, run_dir)} "
            f"({type(recovery_error).__name__}: {redaction.scrub_text(recovery_error, limit=500)})",
            file=sys.stderr,
        )
    raise WorkflowStateError(diagnostic) from None


def update_workflow_state(run_dir: Path, step_id: str, status: str, note: str = "") -> None:
    """Atomically update a versioned workflow state or fail with a recovery diagnostic."""

    workflow_path = run_dir / "workflow.plan.json"
    if not workflow_path.exists():
        raise_workflow_state_error(
            run_dir,
            workflow_path,
            step_id,
            status,
            "workflow state file does not exist",
            FileNotFoundError("workflow state file does not exist"),
        )

    try:
        workflow = read_json(workflow_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as read_error:
        raise_workflow_state_error(
            run_dir,
            workflow_path,
            step_id,
            status,
            "cannot read workflow state",
            read_error,
        )

    if not isinstance(workflow, dict):
        raise_workflow_state_error(
            run_dir,
            workflow_path,
            step_id,
            status,
            "cannot validate workflow state",
            TypeError("workflow state must be a JSON object"),
        )
    steps = workflow.get("steps")
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        raise_workflow_state_error(
            run_dir,
            workflow_path,
            step_id,
            status,
            "cannot validate workflow state",
            TypeError("workflow steps must be a JSON array of objects"),
        )

    for existing_step in steps:
        existing_note = existing_step.get("note")
        if isinstance(existing_note, str):
            existing_step["note"] = redaction.scrub_text(existing_note, limit=2000)
    safe_note = redaction.scrub_text(note, limit=2000) if note else ""

    normalized_status = "succeeded" if status == "completed" else status
    allowed_statuses = {"pending", "running", "succeeded", "partial", "failed", "skipped"}
    if normalized_status not in allowed_statuses:
        raise_workflow_state_error(
            run_dir,
            workflow_path,
            step_id,
            status,
            "cannot validate workflow step status",
            ValueError(f"unsupported workflow step status: {status}"),
        )

    now = datetime.now(timezone.utc).isoformat()
    workflow.setdefault("schema_version", WORKFLOW_SCHEMA_VERSION)
    workflow.setdefault("created_at", now)
    workflow["updated_at"] = now

    found = False
    for step in steps:
        if step.get("step_id") != step_id:
            continue
        found = True
        step["status"] = normalized_status
        step["updated_at"] = now
        if normalized_status == "running":
            step.setdefault("started_at", now)
        if normalized_status in {"succeeded", "partial", "skipped", "failed"}:
            step["completed_at"] = now
        if safe_note:
            step["note"] = safe_note
        break

    if not found:
        steps.append(
            {
                "step_id": step_id,
                "status": normalized_status,
                "updated_at": now,
                "note": safe_note,
            }
        )

    if any(step.get("status") == "failed" for step in steps):
        workflow["status"] = "failed"
        workflow["final_status"] = "failed"
    elif any(step.get("status") == "partial" for step in steps):
        workflow["status"] = "partial"
        workflow["final_status"] = "partial"
    elif steps and all(step.get("status") in {"succeeded", "completed", "skipped"} for step in steps):
        workflow["status"] = "completed"
        workflow["final_status"] = "succeeded"
    else:
        workflow["status"] = "running"
        workflow["final_status"] = "pending"

    try:
        write_json(workflow_path, workflow)
    except OSError as error:
        raise_workflow_state_error(
            run_dir,
            workflow_path,
            step_id,
            status,
            "cannot persist workflow state",
            error,
        )


def download_videos(selected_path: Path, output_dir: Path, logs_dir: Path) -> Path:
    """Compatibility wrapper preserving the replaceable ``download_one`` seam."""

    return creator_media.download_videos(
        selected_path,
        output_dir,
        logs_dir,
        download_fn=download_one,
    )


def extract_audio(video_dir: Path, audio_dir: Path) -> Path:
    """Compatibility wrapper preserving the replaceable FFmpeg version seam."""

    return creator_media.extract_audio(
        video_dir,
        audio_dir,
        ffmpeg_version_fn=ffmpeg_version,
    )


def creator_quality_check(run_dir: Path) -> dict[str, Any]:
    """Compatibility wrapper preserving facade-level quality test seams."""

    return creator_quality.creator_quality_check(
        run_dir,
        content_readiness_fn=creator_content_readiness,
        stage_coverage_fn=evaluate_stage_coverage,
    )


def write_run_summary(
    run_dir: Path,
    quality_report: dict[str, Any] | None = None,
    pipeline_result: PipelineResult | None = None,
) -> Path:
    def count_glob(relative: str, pattern: str) -> int:
        root = run_dir / relative
        return len(list(root.glob(pattern))) if root.exists() else 0

    summary = {
        "run_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "raw_metadata": (run_dir / "metadata" / "raw.json").exists(),
            "selected_metadata": (run_dir / "metadata" / "selected.json").exists(),
            "selected_compact_metadata": (
                run_dir / "metadata" / "selected.compact.json"
            ).exists(),
            "creator_profile": (run_dir / "metadata" / "creator_profile.json").exists(),
            "videos": count_glob("media/videos", "*.mp4"),
            "audio": count_glob("media/audio", "*.*"),
            "transcripts": count_glob("transcripts", "*.txt"),
            "asr_raw_json": count_glob("transcripts/raw_json", "*.json"),
            "research_summary": (run_dir / "research" / "merged" / "summary.md").exists(),
            "skill": (run_dir / "skill" / "SKILL.md").exists(),
        },
        "quality": quality_report or {},
        "stage_coverage": (quality_report or {}).get("stage_coverage", {}),
        "execution": logging_utils.build_execution_summary(
            run_dir,
            pipeline_result=pipeline_result,
            quality_report=quality_report,
        ),
    }
    output_path = run_dir / "run_summary.json"
    write_json(output_path, summary)
    return output_path


def command_normalize_metadata(args: argparse.Namespace) -> None:
    normalize_metadata(Path(args.input), Path(args.output))


def command_select_samples(args: argparse.Namespace) -> None:
    select_samples(Path(args.input), Path(args.output), args.sample_count)


def command_download_videos(args: argparse.Namespace) -> None:
    download_videos(Path(args.input), Path(args.output_dir), Path(args.logs_dir))


def command_extract_audio(args: argparse.Namespace) -> None:
    extract_audio(Path(args.video_dir), Path(args.audio_dir))


def command_asr_json_to_transcript(args: argparse.Namespace) -> None:
    asr_json_to_transcript(Path(args.input), Path(args.output))


def command_summarize_transcripts(args: argparse.Namespace) -> None:
    summarize_transcripts(Path(args.transcripts_dir), Path(args.output_dir))


def command_build_skill(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    run_diagnostics.require_current_run(run_dir)
    build_creator_skill(run_dir, args.project_name)


def command_quality_check(args: argparse.Namespace) -> int:
    report = creator_quality_check(Path(args.run_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for name, passed in report["checks"].items():
            print(f"{'PASS' if passed else 'FAIL'}  {name}")
        for name, passed in report.get("content_readiness", {}).get("checks", {}).items():
            print(f"{'PASS' if passed else 'WARN'}  readiness.{name}")
        for name, passed in report.get("governance", {}).get("checks", {}).items():
            print(f"{'PASS' if passed else 'WARN'}  governance.{name}")

        integrity = report.get("evidence_integrity", {})
        print(f"EVIDENCE_INTEGRITY {'VALID' if integrity.get('valid') else 'INVALID'}")
        integrity_counts = integrity.get("counts") or {}
        print(
            "REFERENCE_ERRORS "
            f"orphan={integrity_counts.get('orphan_references', 0)} "
            f"missing={integrity_counts.get('missing_references', 0)} "
            f"duplicate={integrity_counts.get('duplicate_references', 0)} "
            f"type_mismatch={integrity_counts.get('type_mismatches', 0)}"
        )
        evaluator = report.get("evaluator_verdict") or {}
        print(f"EVALUATOR {'PASS' if evaluator.get('passed') else 'FAIL'}")
        for name, check_value in (report.get("blocking_checks") or {}).items():
            check = check_value if isinstance(check_value, dict) else {}
            evidence = json.dumps(
                check.get("evidence") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            print(
                f"BLOCKING {'PASS' if check.get('passed') else 'FAIL'} "
                f"{name} evidence={evidence}"
            )
        for name, check_value in (report.get("advisory_checks") or {}).items():
            check = check_value if isinstance(check_value, dict) else {}
            evidence = json.dumps(
                check.get("evidence") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            print(
                f"ADVISORY {'PASS' if check.get('passed') else 'WARN'} "
                f"{name} evidence={evidence}"
            )

        safety = report.get("content_safety") or {}
        overlap = safety.get("copyright_overlap") or {}
        print(
            f"COPYRIGHT_OVERLAP {'PASS' if overlap.get('passed') else 'FAIL'} "
            f"longest={overlap.get('longest_overlap_chars', 0)} "
            f"ratio={overlap.get('overall_copied_ratio', 0.0)}"
        )
        overlap_failed_files = overlap.get("failed_files") or []
        if overlap_failed_files:
            print("COPYRIGHT_FAILED_FILES " + " ".join(overlap_failed_files))
        encoding = safety.get("encoding") or {}
        print(f"ENCODING {'PASS' if encoding.get('passed') else 'FAIL'}")
        encoding_failed_files = encoding.get("failed_files") or []
        if encoding_failed_files:
            print("ENCODING_FAILED_FILES " + " ".join(encoding_failed_files))
        freshness = report.get("freshness", {})
        print(f"FRESHNESS {'FRESH' if freshness.get('fresh') else 'STALE'}")
        if not freshness.get("fresh"):
            print("STALE_ARTIFACTS " + " ".join(freshness.get("stale_artifacts") or []))
            print(f"REPAIR {freshness.get('repair_command')}")
        print(f"READY_FOR_USE {'YES' if report.get('ready_for_use') else 'NO'}")
        print(
            "COMMERCIAL_DELIVERY_READY "
            f"{'YES' if report.get('commercial_delivery_ready') else 'NO'}"
        )
        print(f"OVERALL {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] or args.report_only else 1


def command_run_summary(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    run_diagnostics.require_current_run(run_dir)
    report_path = run_dir / "logs" / "creator_quality_report.json"
    report = read_json(report_path) if report_path.exists() else None
    print(write_run_summary(run_dir, report))


def command_inspect_run(args: argparse.Namespace) -> int:
    report = run_diagnostics.inspect_run(Path(args.run_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        missing = ",".join(report["missing_manifests"]) or "none"
        invalid = ",".join(report["invalid_manifests"]) or "none"
        action = report["recommended_action"]
        print(f"RUN_FORMAT {report['format_name'] or 'unknown'}")
        print(f"FORMAT_VERSION {report['format_version'] or 'unknown'}")
        print(f"FORMAT_STATUS {report['format_status']}")
        print(f"FORMAT_VERIFIED {'YES' if report['format_verified'] else 'NO'}")
        print(f"READY_FOR_USE {'YES' if report['ready_for_use'] else 'NO'}")
        print(f"MISSING_MANIFESTS {missing}")
        print(f"INVALID_MANIFESTS {invalid}")
        print(f"NEXT_ACTION {action['code']} {action['command']}")
    return 0 if report["format_verified"] else 1


def build_parser() -> argparse.ArgumentParser:
    """Build the public parser so compatibility tests can exercise it without I/O."""

    parser = argparse.ArgumentParser(description="Creator Skill deterministic pipeline utilities")
    parser.add_argument("--env", help="Path to .env file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize-metadata")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--output", required=True)
    normalize.set_defaults(func=command_normalize_metadata)

    select = subparsers.add_parser("select-samples")
    select.add_argument("--input", required=True)
    select.add_argument("--output", required=True)
    select.add_argument("--sample-count", type=sample_count_argument, required=True)
    select.set_defaults(func=command_select_samples)

    download = subparsers.add_parser("download-videos")
    download.add_argument("--input", required=True)
    download.add_argument("--output-dir", required=True)
    download.add_argument("--logs-dir", required=True)
    download.set_defaults(func=command_download_videos)

    audio = subparsers.add_parser("extract-audio")
    audio.add_argument("--video-dir", required=True)
    audio.add_argument("--audio-dir", required=True)
    audio.set_defaults(func=command_extract_audio)

    transcript = subparsers.add_parser("asr-json-to-transcript")
    transcript.add_argument("--input", required=True)
    transcript.add_argument("--output", required=True)
    transcript.set_defaults(func=command_asr_json_to_transcript)

    summary = subparsers.add_parser("summarize-transcripts")
    summary.add_argument("--transcripts-dir", required=True)
    summary.add_argument("--output-dir", required=True)
    summary.set_defaults(func=command_summarize_transcripts)

    skill = subparsers.add_parser("build-skill")
    skill.add_argument("--run-dir", required=True)
    skill.add_argument("--project-name", required=True)
    skill.set_defaults(func=command_build_skill)

    quality = subparsers.add_parser("quality-check")
    quality.add_argument("--run-dir", required=True)
    quality.add_argument("--json", action="store_true")
    quality.add_argument(
        "--report-only",
        action="store_true",
        help="Print a failing quality report but return exit code 0",
    )
    quality.set_defaults(func=command_quality_check)

    run_summary = subparsers.add_parser("run-summary")
    run_summary.add_argument("--run-dir", required=True)
    run_summary.set_defaults(func=command_run_summary)

    inspect_run = subparsers.add_parser(
        "inspect-run",
        help="Read-only diagnosis of run format, manifests, and persisted readiness",
    )
    inspect_run.add_argument("--run-dir", required=True)
    inspect_run.add_argument("--json", action="store_true")
    inspect_run.set_defaults(func=command_inspect_run)
    return parser


def main() -> int:
    parser = build_parser()

    args = parser.parse_args()
    if args.command != "inspect-run":
        try:
            settings.load_settings(
                Path(args.env).expanduser() if args.env else None,
                install=True,
            )
        except settings.SettingsError as error:
            parser.error(str(error))
    try:
        result = args.func(args)
    except run_diagnostics.RunFormatError as error:
        parser.error(str(error))
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1) from None
