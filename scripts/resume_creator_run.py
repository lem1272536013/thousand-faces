#!/usr/bin/env python3
"""Resume expensive post-download steps for an existing Creator Skill run."""

from __future__ import annotations

import argparse
from pathlib import Path

import build_creator_skill
import creator_pipeline
import run_creator_skill_build


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume ASR, summary, skill build, and quality check for an existing run")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--env")
    parser.add_argument("--strict-asr", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    env_path = Path(args.env).expanduser() if args.env else None
    build_creator_skill.load_env_file(env_path)

    creator_pipeline.update_workflow_state(run_dir, "download_videos", "completed", "videos are available")
    creator_pipeline.update_workflow_state(run_dir, "extract_audio_with_ffmpeg", "completed", "audio files are available")

    creator_pipeline.update_workflow_state(run_dir, "transcribe_with_aliyun_asr", "running")
    run_creator_skill_build.transcribe_audio_files(run_dir, env_path, args.strict_asr)
    creator_pipeline.update_workflow_state(run_dir, "transcribe_with_aliyun_asr", "completed")

    creator_pipeline.update_workflow_state(run_dir, "normalize_transcripts", "running")
    if list((run_dir / "transcripts").glob("*.txt")):
        creator_pipeline.update_workflow_state(
            run_dir,
            "normalize_transcripts",
            "completed",
            "transcript text files are available",
        )
    else:
        creator_pipeline.update_workflow_state(run_dir, "normalize_transcripts", "skipped", "no transcript text files found")

    creator_pipeline.update_workflow_state(run_dir, "research_creator_style", "running")
    creator_pipeline.summarize_transcripts(run_dir / "transcripts", run_dir / "research" / "merged", overwrite=True)
    creator_pipeline.update_workflow_state(run_dir, "research_creator_style", "completed", "deterministic transcript summary written")

    creator_pipeline.update_workflow_state(run_dir, "build_creator_skill", "running")
    creator_pipeline.build_creator_skill(run_dir, args.project_name, overwrite=True)
    creator_pipeline.update_workflow_state(run_dir, "build_creator_skill", "completed")

    creator_pipeline.update_workflow_state(run_dir, "quality_check", "running")
    quality_report = creator_pipeline.creator_quality_check(run_dir)
    creator_pipeline.write_run_summary(run_dir, quality_report)
    creator_pipeline.update_workflow_state(
        run_dir,
        "quality_check",
        "completed" if quality_report.get("passed") else "failed",
        "quality gate executed",
    )
    print(f"DONE passed={quality_report.get('passed')} ready_for_use={quality_report.get('ready_for_use')}")


if __name__ == "__main__":
    main()
