#!/usr/bin/env python3
"""Resume expensive post-download steps for an existing Creator Skill run."""

from __future__ import annotations

import argparse
from pathlib import Path

import creator_pipeline
import logging_utils
import path_policy
import redaction
import run_diagnostics
import run_creator_skill_build
import settings
from input_validation import project_name_argument
from pipeline_models import PipelineResult, StepResult, write_pipeline_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume ASR, summary, skill build, and quality check for an existing run")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--project-name", required=True, type=project_name_argument)
    parser.add_argument("--env")
    parser.add_argument("--strict-asr", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    env_path = Path(args.env).expanduser() if args.env else None
    try:
        settings.load_settings(env_path, install=True)
    except settings.SettingsError as exc:
        parser.error(str(exc))
    try:
        run_diagnostics.require_current_run(run_dir)
    except run_diagnostics.RunFormatError as error:
        parser.error(str(error))

    event_logger = logging_utils.StructuredRunLogger(
        run_dir,
        known_secrets=redaction.configured_secrets(),
    )
    event_logger.pipeline_started(resumed=True, message="resuming existing run")
    step_results: list[StepResult] = []
    current_step = ""
    current_timer: logging_utils.StepTimer | None = None
    quality_passed: bool | None = None
    quality_report: dict | None = None

    def start_step(step_id: str, note: str = "") -> None:
        nonlocal current_step, current_timer
        current_step = step_id
        current_timer = event_logger.step_started(step_id, message=note)
        creator_pipeline.update_workflow_state(run_dir, step_id, "running", note)

    def finish_step(result: StepResult, note: str = "") -> None:
        nonlocal current_step, current_timer
        if current_step != result.step_id or current_timer is None:
            raise RuntimeError(
                f"step result mismatch: expected {current_step or '<none>'}, got {result.step_id}"
            )
        workflow_note = note or "; ".join(result.issues[:3])
        creator_pipeline.update_workflow_state(
            run_dir,
            current_step,
            result.status,
            workflow_note,
        )
        result = event_logger.step_finished(
            current_timer,
            result,
            message=workflow_note,
        )
        step_results.append(result)
        current_step = ""
        current_timer = None

    def record(result: StepResult, note: str = "") -> None:
        if not current_step:
            start_step(result.step_id, note)
        finish_step(result, note)

    try:
        record(StepResult.succeeded("download_videos"), "videos are available")
        record(StepResult.succeeded("extract_audio_with_ffmpeg"), "audio files are available")

        start_step("transcribe_with_aliyun_asr")
        record(run_creator_skill_build.transcribe_audio_files_step(run_dir, env_path, args.strict_asr))

        start_step("normalize_transcripts")
        transcript_paths = path_policy.artifact_files(run_dir / "transcripts", ".txt")
        if transcript_paths:
            record(
                StepResult.succeeded("normalize_transcripts", input_count=len(transcript_paths)),
                "transcript text files are available",
            )
        else:
            record(StepResult.failed("normalize_transcripts", issues=("no transcript text files found",)))

        start_step("research_creator_style")
        record(
            creator_pipeline.summarize_transcripts_step(
                run_dir / "transcripts",
                run_dir / "research" / "merged",
                overwrite=True,
            ),
            "deterministic transcript summary written",
        )

        start_step("build_creator_skill")
        record(creator_pipeline.build_creator_skill_step(run_dir, args.project_name, overwrite=True))

        start_step("quality_check")
        quality_result, quality_report = creator_pipeline.creator_quality_check_step(run_dir)
        quality_passed = bool(quality_report.get("passed"))
        record(quality_result, "quality gate executed")
    except BaseException as exc:
        descriptor = logging_utils.classify_exception(
            exc,
            known_secrets=redaction.configured_secrets(),
        )
        if current_step:
            failed_result = StepResult.failed(
                current_step,
                issues=(descriptor.message,),
                error_codes=(descriptor.error_code,),
            )
            finish_step(failed_result)
        pipeline_result = PipelineResult.from_steps(
            str(run_dir),
            step_results,
            quality_passed=quality_passed,
            error={
                "type": type(exc).__name__,
                "error_code": descriptor.error_code,
                "detail_code": descriptor.detail_code,
                "message": descriptor.message,
                "recoverable": str(descriptor.recoverable).lower(),
                "recovery_hint": descriptor.recovery_hint,
            },
        )
        write_pipeline_result(run_dir / "logs" / "pipeline_result.json", pipeline_result)
        event_logger.pipeline_finished(pipeline_result)
        creator_pipeline.write_run_summary(
            run_dir,
            quality_report,
            pipeline_result,
        )
        raise SystemExit(f"{descriptor.error_code}: {descriptor.message}") from None

    pipeline_result = PipelineResult.from_steps(
        str(run_dir),
        step_results,
        quality_passed=quality_passed,
    )
    write_pipeline_result(run_dir / "logs" / "pipeline_result.json", pipeline_result)
    event_logger.pipeline_finished(pipeline_result)
    creator_pipeline.write_run_summary(
        run_dir,
        quality_report,
        pipeline_result,
    )
    print(
        f"DONE passed={quality_passed} ready_for_use={quality_report.get('ready_for_use')} "
        f"commercial_delivery_ready={quality_report.get('commercial_delivery_ready')}"
    )
    return pipeline_result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
