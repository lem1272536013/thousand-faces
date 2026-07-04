#!/usr/bin/env python3
"""Run the Thousand Faces Style Skill pipeline end to end where config permits."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import build_creator_skill
import creator_pipeline
import provider_adapters


def copy_existing_transcripts(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("*.txt")):
        shutil.copy2(path, target / path.name)


def audio_public_url(audio_path: Path) -> tuple[str, str]:
    template = os.environ.get("ALI_ASR_AUDIO_URL_TEMPLATE", "")
    if template:
        return template.format(filename=audio_path.name, stem=audio_path.stem, path=audio_path.as_posix()), "template"
    base = os.environ.get("AUDIO_PUBLIC_URL_BASE", "").rstrip("/")
    if base:
        return f"{base}/{audio_path.name}", "base_url"
    if provider_adapters.oss_configured():
        return provider_adapters.upload_file_to_oss(audio_path), "oss_signed_url"
    return "", ""


def media_duration_seconds(path: Path) -> float:
    ffprobe = os.environ.get("FFPROBE_BIN", "ffprobe")
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def split_audio_for_asr(audio_path: Path, chunks_dir: Path) -> list[Path]:
    segment_seconds = int(os.environ.get("ASR_SEGMENT_SECONDS", "120"))
    if segment_seconds <= 0:
        return [audio_path]
    duration = media_duration_seconds(audio_path)
    if not duration or duration <= segment_seconds:
        return [audio_path]

    chunks_dir.mkdir(parents=True, exist_ok=True)
    suffix = audio_path.suffix.lstrip(".") or os.environ.get("ALI_ASR_AUDIO_FORMAT", "mp3")
    pattern = chunks_dir / f"{audio_path.stem}.chunk-%03d.{suffix}"
    existing = sorted(chunks_dir.glob(f"{audio_path.stem}.chunk-*.{suffix}"))
    if existing:
        return existing

    ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(audio_path),
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-reset_timestamps",
        "1",
        "-vn",
        "-ac",
        "1",
        "-ar",
        os.environ.get("ASR_SAMPLE_RATE", "16000"),
    ]
    if suffix in {"mp3", "mpeg"}:
        cmd.extend(["-codec:a", "libmp3lame", "-b:a", os.environ.get("ASR_MP3_BITRATE", "64k")])
    cmd.append(str(pattern))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"failed to split audio for ASR: {proc.stderr[-2000:]}")
    chunks = sorted(chunks_dir.glob(f"{audio_path.stem}.chunk-*.{suffix}"))
    return chunks or [audio_path]


def transcribe_compatible_audio_path(audio_path: Path, raw_dir: Path, transcript_path: Path) -> dict:
    chunks = split_audio_for_asr(audio_path, raw_dir / "chunks")
    chunk_transcripts = []
    chunk_json_paths = []
    for index, chunk_path in enumerate(chunks, start=1):
        result_json = raw_dir / f"{audio_path.stem}.chunk-{index:03d}.result.json" if len(chunks) > 1 else raw_dir / f"{audio_path.stem}.result.json"
        chunk_txt = raw_dir / f"{audio_path.stem}.chunk-{index:03d}.txt" if len(chunks) > 1 else transcript_path
        if not (result_json.exists() and result_json.stat().st_size > 0):
            provider_adapters.transcribe_compatible_audio_file(
                SimpleNamespace(input=str(chunk_path), output=str(result_json))
            )
        creator_pipeline.asr_json_to_transcript(result_json, chunk_txt)
        chunk_json_paths.append(str(result_json))
        if chunk_txt.exists():
            chunk_transcripts.append(chunk_txt.read_text(encoding="utf-8").strip())

    if len(chunks) > 1:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("\n\n".join(text for text in chunk_transcripts if text).strip() + "\n", encoding="utf-8")

    return {
        "audio": str(audio_path),
        "status": "transcribed",
        "transcript": str(transcript_path),
        "chunks": len(chunks),
        "raw_json": chunk_json_paths,
        "asr_provider": os.environ.get("ALI_ASR_PROVIDER", "openai-compatible").lower(),
    }


def transcribe_one_audio(audio_path: Path, raw_dir: Path, transcript_dir: Path, strict_asr: bool) -> dict:
    transcript_path = transcript_dir / f"{audio_path.stem}.txt"
    if transcript_path.exists() and transcript_path.stat().st_size > 0:
        return {"audio": str(audio_path), "status": "skipped", "transcript": str(transcript_path)}

    asr_provider = os.environ.get("ALI_ASR_PROVIDER", "aliyun").lower()
    task_json = raw_dir / f"{audio_path.stem}.task.json"
    result_json = raw_dir / f"{audio_path.stem}.result.json"

    if asr_provider in {"openai-compatible", "compatible", "qwen-compatible"}:
        return transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)

    url, url_source = audio_public_url(audio_path)
    if not url:
        message = "missing AUDIO_PUBLIC_URL_BASE, ALI_ASR_AUDIO_URL_TEMPLATE, or OSS config"
        if strict_asr:
            raise SystemExit(message)
        return {"audio": str(audio_path), "status": "skipped", "reason": message}

    provider_adapters.transcribe_aliyun_file_url(
        SimpleNamespace(
            file_url=url,
            output=str(task_json),
            result_json=str(result_json),
            timeout=int(os.environ.get("HTTP_TIMEOUT_SECONDS", "60")),
        )
    )
    source_json = result_json if result_json.exists() else task_json
    creator_pipeline.asr_json_to_transcript(source_json, transcript_path)
    return {
        "audio": str(audio_path),
        "status": "transcribed",
        "transcript": str(transcript_path),
        "audio_url_source": url_source,
    }


def transcribe_audio_files(run_dir: Path, env_path: Path | None, strict_asr: bool) -> list[dict]:
    audio_dir = run_dir / "media" / "audio"
    raw_dir = run_dir / "transcripts" / "raw_json"
    transcript_dir = run_dir / "transcripts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    audio_paths = [path for path in sorted(audio_dir.iterdir() if audio_dir.exists() else []) if path.is_file()]
    concurrency = max(1, int(os.environ.get("ALI_ASR_CONCURRENCY", "4")))
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(audio_paths)))) as executor:
        futures = {
            executor.submit(transcribe_one_audio, audio_path, raw_dir, transcript_dir, strict_asr): audio_path
            for audio_path in audio_paths
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results = sorted(results, key=lambda row: row.get("audio", ""))
    creator_pipeline.write_json(run_dir / "logs" / "asr_status.json", {"count": len(results), "results": results})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Thousand Faces Style Skill end-to-end")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--sample-count", type=int, default=50)
    parser.add_argument("--metadata-fetch-limit", type=int)
    parser.add_argument("--run-root")
    parser.add_argument("--env")
    parser.add_argument("--raw-metadata", help="Use existing TikHub raw metadata JSON")
    parser.add_argument("--transcripts-dir", help="Use existing transcript .txt files and skip provider ASR")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-audio", action="store_true")
    parser.add_argument("--skip-asr", action="store_true")
    parser.add_argument("--skip-llm-research", action="store_true", help="Deprecated; research is performed by the host agent after transcripts are prepared.")
    parser.add_argument("--strict-config", action="store_true")
    parser.add_argument("--strict-asr", action="store_true")
    args = parser.parse_args()

    env_path = Path(args.env).expanduser() if args.env else None
    build_creator_skill.load_env_file(env_path)
    config = build_creator_skill.collect_config()
    missing = build_creator_skill.missing_required(config)
    if args.strict_config and missing:
        raise SystemExit("missing required config: " + ", ".join(missing))

    run_dir = build_creator_skill.create_run(args, config)
    print(f"[run] created {run_dir}")

    current_step = ""

    def start_step(step_id: str, note: str = "") -> None:
        nonlocal current_step
        current_step = step_id
        creator_pipeline.update_workflow_state(run_dir, step_id, "running", note)

    def finish_step(status: str = "completed", note: str = "") -> None:
        if current_step:
            creator_pipeline.update_workflow_state(run_dir, current_step, status, note)

    raw_metadata = run_dir / "metadata" / "raw.json"
    normalized_metadata = run_dir / "metadata" / "normalized.json"
    selected_metadata = run_dir / "metadata" / "selected.json"
    selected_compact_metadata = run_dir / "metadata" / "selected.compact.json"
    creator_profile = run_dir / "metadata" / "creator_profile.json"

    start_step("parse_creator_url")
    finish_step("completed", "run directory created")

    try:
        if args.raw_metadata:
            start_step("fetch_creator_videos_with_tikhub", "using existing raw metadata")
            shutil.copy2(Path(args.raw_metadata).expanduser(), raw_metadata)
            print(f"[metadata] copied {raw_metadata}")
            finish_step("completed", "copied raw metadata")
        elif not args.skip_fetch:
            start_step("fetch_creator_videos_with_tikhub")
            provider_adapters.fetch_tikhub_creator_videos(
                SimpleNamespace(
                    source_url=args.source_url,
                    limit=args.metadata_fetch_limit or int(config["TIKHUB_METADATA_FETCH_LIMIT"]),
                    output=str(raw_metadata),
                    timeout=int(config["HTTP_TIMEOUT_SECONDS"]),
                )
            )
            print(f"[metadata] fetched {raw_metadata}")
            finish_step("completed", "fetched raw metadata")
        else:
            start_step("fetch_creator_videos_with_tikhub")
            finish_step("skipped", "--skip-fetch was set")

        start_step("select_recent_samples")
        if raw_metadata.exists():
            creator_pipeline.normalize_metadata(raw_metadata, normalized_metadata)
            creator_pipeline.select_samples(normalized_metadata, selected_metadata, args.sample_count)
            print(f"[metadata] selected {selected_metadata}")
            if selected_compact_metadata.exists():
                print(f"[metadata] compact {selected_compact_metadata}")
            if creator_profile.exists():
                print(f"[metadata] creator profile {creator_profile}")
            finish_step("completed", "normalized and selected samples")
        else:
            finish_step("skipped", "raw metadata was not available")

        start_step("download_videos")
        if selected_metadata.exists() and not args.skip_download:
            creator_pipeline.download_videos(selected_metadata, run_dir / "media" / "videos", run_dir / "logs")
            print("[download] done")
            finish_step("completed")
        else:
            finish_step("skipped", "--skip-download was set or selected metadata was missing")

        start_step("extract_audio_with_ffmpeg")
        if not args.skip_audio:
            creator_pipeline.extract_audio(run_dir / "media" / "videos", run_dir / "media" / "audio")
            print("[audio] done")
            finish_step("completed")
        else:
            finish_step("skipped", "--skip-audio was set")

        start_step("transcribe_with_aliyun_asr")
        if args.transcripts_dir:
            copy_existing_transcripts(Path(args.transcripts_dir).expanduser(), run_dir / "transcripts")
            print("[transcripts] copied existing transcripts")
            finish_step("completed", "copied existing transcripts")
        elif not args.skip_asr:
            transcribe_audio_files(run_dir, env_path, args.strict_asr)
            print("[asr] done")
            finish_step("completed")
        else:
            finish_step("skipped", "--skip-asr was set")

        start_step("normalize_transcripts")
        if list((run_dir / "transcripts").glob("*.txt")):
            finish_step("completed", "transcript text files are available")
        else:
            finish_step("skipped", "no transcript text files found")

        start_step("research_creator_style")
        creator_pipeline.summarize_transcripts(run_dir / "transcripts", run_dir / "research" / "merged", overwrite=False)
        print("[research] transcript summary done; use the host agent to read transcripts and refine the generated skill")
        finish_step("completed", "deterministic transcript summary written")

        start_step("build_creator_skill")
        skill_dir = creator_pipeline.build_creator_skill(run_dir, args.project_name, overwrite=False)
        print(f"[skill] built {skill_dir}")
        finish_step("completed")

        start_step("quality_check")
        quality_report = creator_pipeline.creator_quality_check(run_dir)
        creator_pipeline.write_run_summary(run_dir, quality_report)
        print(f"[quality] {'passed' if quality_report['passed'] else 'failed'}")
        if not quality_report.get("ready_for_use"):
            print("[quality] draft requires host-agent refinement before direct use")
            print(f"[next] python scripts/prepare_host_refinement.py --run-dir {run_dir}")
        finish_step("completed" if quality_report["passed"] else "failed", "quality gate executed")
    except BaseException as exc:
        if current_step:
            creator_pipeline.update_workflow_state(run_dir, current_step, "failed", str(exc)[:500])
        raise

    if missing:
        print("warning: missing config for full live execution: " + ", ".join(missing))


if __name__ == "__main__":
    main()
