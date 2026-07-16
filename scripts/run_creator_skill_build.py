#!/usr/bin/env python3
"""Run the Thousand Faces Style Skill pipeline end to end where config permits."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import subprocess
import time
from pathlib import Path

import artifacts
import build_creator_skill
import creator_pipeline
import logging_utils
import oss_lifecycle
import path_policy
import provenance
import provider_adapters
import redaction
import settings
from asr_parsers import (
    ASR_PARSER_VERSION,
    ASRParseError,
    ChunkTranscript,
    merge_chunk_transcripts,
    parse_asr_response,
    render_transcript,
)
from input_validation import (
    InputValidationError,
    metadata_fetch_limit_argument,
    project_name_argument,
    sample_count_argument,
    validate_asr_concurrency,
    validate_asr_memory_budget,
)
from io_utils import atomic_write_text
from pipeline_models import PipelineResult, StepResult, write_pipeline_result


def copy_existing_transcripts(
    source: Path,
    target: Path,
    *,
    selected_path: Path | None = None,
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if selected_path is not None and selected_path.is_file():
        payload = creator_pipeline.read_json(selected_path)
        raw_items = payload.get("items", []) if isinstance(payload, dict) else []
        items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
        mapped_items, _records = path_policy.assign_artifact_ids(items)
        for item in mapped_items:
            raw_id = path_policy.validate_platform_video_id(item["platform_video_id"])
            artifact_id = path_policy.validate_artifact_id(item["artifact_id"])
            candidates = [
                path_policy.resolve_within(source, f"{artifact_id}.txt"),
                path_policy.resolve_within(source, f"{raw_id}.txt"),
            ]
            source_path = next((candidate for candidate in dict.fromkeys(candidates) if candidate.is_file()), None)
            if source_path is None:
                continue
            target_path = path_policy.artifact_path(target, artifact_id, ".txt")
            shutil.copy2(source_path, target_path)
        return

    registry = path_policy.ArtifactIdRegistry()
    for path in sorted(source.glob("*.txt")):
        source_path = path_policy.resolve_within(source, path.name)
        artifact_id = registry.assign(path.stem)
        target_path = path_policy.artifact_path(target, artifact_id, ".txt")
        shutil.copy2(source_path, target_path)


def selected_transcript_counts(run_dir: Path) -> tuple[int, int]:
    selected_path = run_dir / "metadata" / "selected.json"
    if not selected_path.is_file():
        return 0, 0
    payload = creator_pipeline.read_json(selected_path)
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    try:
        declared_count = max(0, int(payload.get("selected_count") or 0))
    except (TypeError, ValueError):
        declared_count = 0
    expected_count = max(declared_count, len(items))
    transcript_ids = {
        path.stem
        for path in path_policy.artifact_files(run_dir / "transcripts", ".txt")
        if path.stat().st_size > 0
    }
    covered_count = 0
    for index, item in enumerate(items):
        artifact_id = path_policy.artifact_id_for_item(item, fallback=f"video-{index + 1}")
        if artifact_id in transcript_ids:
            covered_count += 1
    return expected_count, min(covered_count, expected_count)


def transcript_coverage_step_result(step_id: str, run_dir: Path) -> StepResult:
    expected_count, covered_count = selected_transcript_counts(run_dir)
    missing_count = expected_count - covered_count
    issue = f"{missing_count} of {expected_count} selected videos have no non-empty transcript"
    if expected_count <= 0:
        return StepResult.failed(step_id, issues=("no selected videos are available",))
    if covered_count == expected_count:
        return StepResult.succeeded(step_id, input_count=expected_count)
    if covered_count == 0:
        return StepResult.failed(step_id, input_count=expected_count, issues=(issue,))
    return StepResult(
        step_id=step_id,
        status="partial",
        input_count=expected_count,
        succeeded_count=covered_count,
        failed_count=missing_count,
        issues=(issue,),
    )


def audio_public_url(
    audio_path: Path,
    *,
    run_dir: Path,
    video_id: str,
    chunk_id: str = "full",
) -> tuple[str, str, oss_lifecycle.OSSUpload | None]:
    template = os.environ.get("ALI_ASR_AUDIO_URL_TEMPLATE", "")
    if template:
        return (
            template.format(
                filename=audio_path.name,
                stem=audio_path.stem,
                path=audio_path.as_posix(),
            ),
            "template",
            None,
        )
    base = os.environ.get("AUDIO_PUBLIC_URL_BASE", "").rstrip("/")
    if base:
        return f"{base}/{audio_path.name}", "base_url", None
    if provider_adapters.oss_configured():
        context = oss_lifecycle.OSSObjectContext.from_run_dir(
            run_dir,
            video_id=video_id,
            chunk_id=chunk_id,
        )
        upload = provider_adapters.upload_file_to_oss(audio_path, context=context)
        try:
            oss_lifecycle.register_upload(run_dir, upload)
        except BaseException as registration_error:
            try:
                provider_adapters.delete_oss_object(upload.object_key)
            except Exception as cleanup_error:
                safe_registration = redaction.scrub_text(registration_error, limit=500)
                safe_cleanup = redaction.scrub_text(cleanup_error, limit=500)
                raise RuntimeError(
                    "OSS upload registration and rollback cleanup both failed: "
                    f"registration={safe_registration}; cleanup={safe_cleanup}"
                ) from None
            raise registration_error
        return upload.signed_url, "oss_temporary_url", upload
    return "", "", None


def media_duration_seconds(path: Path) -> float:
    ffprobe = os.environ.get("FFPROBE_BIN", settings.DEFAULT_ENV["FFPROBE_BIN"])
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


def file_sha256(path: Path) -> str:
    return artifacts.file_sha256(path)


def asr_raw_artifact_spec(
    audio_input: Path,
    *,
    source_audio: Path | None = None,
    chunk_entry: dict | None = None,
) -> artifacts.ArtifactSpec:
    provider = os.environ.get("ALI_ASR_PROVIDER", settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]).lower()
    endpoint = os.environ.get("ALI_ASR_ENDPOINT") or os.environ.get("DASHSCOPE_BASE_HTTP_API_URL")
    inputs = [artifacts.file_input(audio_input, role="audio_chunk" if source_audio else "source_audio")]
    if source_audio is not None and source_audio != audio_input:
        inputs.append(artifacts.file_input(source_audio, role="source_audio"))
    if endpoint:
        inputs.append(artifacts.safe_url_input(endpoint, role="asr_endpoint"))
    config: dict[str, object] = {
        "provider": provider,
        "endpoint_identity": "configured" if endpoint else "provider_default",
        "model": os.environ.get("ALI_ASR_MODEL", settings.default_asr_model(provider)),
        "language": os.environ.get("ALI_ASR_LANGUAGE", settings.DEFAULT_ENV["ALI_ASR_LANGUAGE"]),
        "segment_seconds": int(os.environ.get("ASR_SEGMENT_SECONDS", settings.DEFAULT_ENV["ASR_SEGMENT_SECONDS"])),
        "sample_rate": os.environ.get("ASR_SAMPLE_RATE", settings.DEFAULT_ENV["ASR_SAMPLE_RATE"]),
        "compatible_api": os.environ.get(
            "ALI_ASR_COMPATIBLE_API", settings.DEFAULT_ENV["ALI_ASR_COMPATIBLE_API"]
        ).lower(),
        "response_format": os.environ.get(
            "ALI_ASR_RESPONSE_FORMAT", settings.DEFAULT_ENV["ALI_ASR_RESPONSE_FORMAT"]
        ),
        "mime_type": os.environ.get("ALI_ASR_MIME_TYPE", settings.DEFAULT_ENV["ALI_ASR_MIME_TYPE"]),
        "parser_version": ASR_PARSER_VERSION,
    }
    if chunk_entry is not None:
        config["chunk_index"] = chunk_entry.get("chunk_index")
        config["chunk_start_ms"] = chunk_entry.get("start_ms")
        config["chunk_end_ms"] = chunk_entry.get("end_ms")
    return artifacts.ArtifactSpec(
        artifact_type="asr_raw_response",
        inputs=tuple(inputs),
        config=config,
        producer={"name": "run_creator_skill_build.transcribe", "version": "1"},
    )


def transcript_artifact_spec(
    audio_path: Path,
    raw_json_paths: list[Path],
    raw_specs: list[artifacts.ArtifactSpec],
    *,
    artifact_type: str = "asr_transcript",
) -> artifacts.ArtifactSpec:
    inputs = [artifacts.file_input(audio_path, role="source_audio")]
    inputs.extend(
        artifacts.file_input(path, role=f"raw_response:{index}")
        for index, path in enumerate(raw_json_paths)
    )
    return artifacts.ArtifactSpec(
        artifact_type=artifact_type,
        inputs=tuple(inputs),
        config={
            "parser_version": ASR_PARSER_VERSION,
            "merge_version": "1",
            "raw_fingerprints": [spec.fingerprint for spec in raw_specs],
        },
        producer={"name": "run_creator_skill_build.render_transcript", "version": "1"},
    )


def chunk_manifest_path(audio_path: Path, chunks_dir: Path) -> Path:
    artifact_id = path_policy.validate_artifact_id(audio_path.stem)
    return path_policy.artifact_path(chunks_dir, artifact_id, ".chunks.manifest.json")


def chunk_paths(audio_path: Path, chunks_dir: Path, suffix: str) -> list[Path]:
    artifact_id = path_policy.validate_artifact_id(audio_path.stem)
    safe_suffix = path_policy.validate_artifact_suffix(f".{suffix.lstrip('.')}")
    paths = []
    for candidate in sorted(chunks_dir.glob(f"{artifact_id}.chunk-*{safe_suffix}")):
        contained = path_policy.resolve_within(chunks_dir, candidate.name)
        if contained.is_file():
            paths.append(contained)
    return paths


def remove_chunk_paths(audio_path: Path, chunks_dir: Path, suffix: str) -> None:
    for path in chunk_paths(audio_path, chunks_dir, suffix):
        path.unlink(missing_ok=True)


def reusable_chunk_paths(
    audio_path: Path,
    chunks_dir: Path,
    source_hash: str,
    source_duration_ms: int,
    segment_seconds: int,
) -> list[Path]:
    manifest_path = chunk_manifest_path(audio_path, chunks_dir)
    if not manifest_path.is_file():
        return []
    try:
        manifest = creator_pipeline.read_json(manifest_path)
    except (OSError, ValueError):
        return []
    if not isinstance(manifest, dict) or manifest.get("status") != "complete":
        return []
    if manifest.get("source_audio_sha256") != source_hash:
        return []
    if manifest.get("source_duration_ms") != source_duration_ms or manifest.get("segment_seconds") != segment_seconds:
        return []
    entries = manifest.get("chunks")
    if not isinstance(entries, list) or len(entries) < 2:
        return []
    artifact_id = path_policy.validate_artifact_id(audio_path.stem)
    source_suffix = path_policy.validate_artifact_suffix(audio_path.suffix)
    paths: list[Path] = []
    expected_start = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return []
        expected_path = path_policy.artifact_path(
            chunks_dir,
            artifact_id,
            f".chunk-{index:03d}{source_suffix}",
        )
        recorded_path = Path(str(entry.get("path", "")))
        if recorded_path.resolve(strict=False) != expected_path:
            return []
        if not expected_path.is_file() or expected_path.stat().st_size <= 0:
            return []
        if entry.get("chunk_index") != index:
            return []
        start_ms = entry.get("start_ms")
        end_ms = entry.get("end_ms")
        duration_ms = entry.get("duration_ms")
        if start_ms != expected_start or not isinstance(duration_ms, int) or duration_ms <= 0:
            return []
        if not isinstance(end_ms, int) or end_ms != start_ms + duration_ms:
            return []
        expected_start = end_ms
        paths.append(expected_path)
    return paths


def write_failed_chunk_manifest(
    audio_path: Path,
    chunks_dir: Path,
    source_hash: str,
    source_duration_ms: int,
    segment_seconds: int,
    error: str,
) -> None:
    creator_pipeline.write_json(
        chunk_manifest_path(audio_path, chunks_dir),
        {
            "schema_version": 1,
            "status": "failed",
            "source_audio": str(audio_path),
            "source_audio_sha256": source_hash,
            "source_duration_ms": source_duration_ms,
            "segment_seconds": segment_seconds,
            "error": redaction.scrub_text(error, limit=2000),
            "chunks": [],
        },
    )


def split_audio_for_asr(audio_path: Path, chunks_dir: Path) -> list[Path]:
    artifact_id = path_policy.validate_artifact_id(audio_path.stem)
    segment_seconds = int(os.environ.get("ASR_SEGMENT_SECONDS", settings.DEFAULT_ENV["ASR_SEGMENT_SECONDS"]))
    if segment_seconds <= 0:
        return [audio_path]
    duration = media_duration_seconds(audio_path)
    if duration <= 0:
        raise SystemExit(f"cannot determine audio duration for ASR splitting: {audio_path}")
    if duration <= segment_seconds:
        return [audio_path]

    chunks_dir.mkdir(parents=True, exist_ok=True)
    requested_suffix = audio_path.suffix or (
        f".{os.environ.get('ALI_ASR_AUDIO_FORMAT', settings.DEFAULT_ENV['ALI_ASR_AUDIO_FORMAT']).lstrip('.')}"
    )
    safe_suffix = path_policy.validate_artifact_suffix(requested_suffix)
    suffix = safe_suffix[1:].lower()
    source_hash = file_sha256(audio_path)
    source_duration_ms = round(duration * 1000)
    cached = reusable_chunk_paths(
        audio_path,
        chunks_dir,
        source_hash,
        source_duration_ms,
        segment_seconds,
    )
    if cached:
        return cached

    remove_chunk_paths(audio_path, chunks_dir, suffix)
    pattern = path_policy.resolve_within(chunks_dir, f"{artifact_id}.chunk-%03d{safe_suffix}")

    ffmpeg = os.environ.get("FFMPEG_BIN", settings.DEFAULT_ENV["FFMPEG_BIN"])
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
        os.environ.get("ASR_SAMPLE_RATE", settings.DEFAULT_ENV["ASR_SAMPLE_RATE"]),
    ]
    if suffix in {"mp3", "mpeg"}:
        cmd.extend(
            ["-codec:a", "libmp3lame", "-b:a", os.environ.get("ASR_MP3_BITRATE", settings.DEFAULT_ENV["ASR_MP3_BITRATE"])]
        )
    cmd.append(str(pattern))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        remove_chunk_paths(audio_path, chunks_dir, suffix)
        write_failed_chunk_manifest(
            audio_path,
            chunks_dir,
            source_hash,
            source_duration_ms,
            segment_seconds,
            proc.stderr or "ffmpeg returned a non-zero status",
        )
        raise SystemExit(
            f"failed to split audio for ASR: {redaction.scrub_text(proc.stderr, limit=2000)}"
        )
    chunks = chunk_paths(audio_path, chunks_dir, suffix)
    if not chunks:
        message = "ffmpeg completed but produced no chunk files"
        write_failed_chunk_manifest(
            audio_path,
            chunks_dir,
            source_hash,
            source_duration_ms,
            segment_seconds,
            message,
        )
        raise SystemExit(f"failed to split audio for ASR: {message}")

    entries = []
    start_ms = 0
    for index, chunk in enumerate(chunks):
        chunk_duration_ms = round(media_duration_seconds(chunk) * 1000)
        if chunk_duration_ms <= 0:
            remove_chunk_paths(audio_path, chunks_dir, suffix)
            message = f"cannot determine duration of generated chunk: {chunk}"
            write_failed_chunk_manifest(
                audio_path,
                chunks_dir,
                source_hash,
                source_duration_ms,
                segment_seconds,
                message,
            )
            raise SystemExit(f"failed to split audio for ASR: {message}")
        end_ms = start_ms + chunk_duration_ms
        entries.append(
            {
                "chunk_index": index,
                "path": str(chunk),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": chunk_duration_ms,
            }
        )
        start_ms = end_ms

    creator_pipeline.write_json(
        chunk_manifest_path(audio_path, chunks_dir),
        {
            "schema_version": 1,
            "status": "complete",
            "source_audio": str(audio_path),
            "source_audio_sha256": source_hash,
            "source_duration_ms": source_duration_ms,
            "segment_seconds": segment_seconds,
            "chunks": entries,
        },
    )
    return chunks


def ensure_compatible_raw_response(
    audio_input: Path,
    result_json: Path,
    spec: artifacts.ArtifactSpec,
) -> bool:
    decision = artifacts.assess_artifact(result_json, spec)
    if decision.reusable:
        return True
    provider_adapters.transcribe_compatible_audio_file(
        argparse.Namespace(input=str(audio_input), output=str(result_json))
    )
    artifacts.write_artifact_manifest(result_json, spec)
    return False


def transcribe_compatible_audio_path(audio_path: Path, raw_dir: Path, transcript_path: Path) -> dict:
    artifact_id = path_policy.validate_artifact_id(audio_path.stem)
    chunks_dir = path_policy.resolve_within(raw_dir, "chunks")
    chunks = split_audio_for_asr(audio_path, chunks_dir)
    asr_provider = os.environ.get("ALI_ASR_PROVIDER", settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]).lower()
    if len(chunks) == 1:
        result_json = path_policy.artifact_path(raw_dir, artifact_id, ".result.json")
        raw_spec = asr_raw_artifact_spec(chunks[0])
        raw_reused = ensure_compatible_raw_response(chunks[0], result_json, raw_spec)
        transcript_spec = transcript_artifact_spec(audio_path, [result_json], [raw_spec])
        transcript_decision = artifacts.assess_artifact(transcript_path, transcript_spec)
        if raw_reused and transcript_decision.reusable:
            return {
                "audio": str(audio_path),
                "status": "skipped",
                "transcript": str(transcript_path),
                "chunks": 1,
                "raw_json": [str(result_json)],
                "cache_status": "verified",
                "asr_provider": asr_provider,
            }
        creator_pipeline.asr_json_to_transcript(result_json, transcript_path)
        artifacts.write_artifact_manifest(transcript_path, transcript_spec)
        return {
            "audio": str(audio_path),
            "status": "transcribed",
            "transcript": str(transcript_path),
            "chunks": 1,
            "raw_json": [str(result_json)],
            "cache_status": "raw_verified" if raw_reused else "raw_refreshed",
            "asr_provider": asr_provider,
        }

    manifest_path = chunk_manifest_path(audio_path, chunks_dir)
    manifest = creator_pipeline.read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("status") != "complete":
        raise SystemExit(f"chunk manifest is not complete: {manifest_path}")
    entries = manifest.get("chunks")
    if not isinstance(entries, list) or len(entries) != len(chunks):
        raise SystemExit(f"chunk manifest does not match generated chunks: {manifest_path}")

    result_paths: list[Path] = []
    raw_specs: list[artifacts.ArtifactSpec] = []
    raw_reuse: list[bool] = []
    for index, chunk_path in enumerate(chunks, start=1):
        entry = entries[index - 1]
        if not isinstance(entry, dict) or Path(str(entry.get("path", ""))) != chunk_path:
            raise SystemExit(f"chunk manifest path mismatch at index {index - 1}: {manifest_path}")
        result_json = path_policy.artifact_path(raw_dir, artifact_id, f".chunk-{index:03d}.result.json")
        raw_spec = asr_raw_artifact_spec(chunk_path, source_audio=audio_path, chunk_entry=entry)
        raw_reuse.append(ensure_compatible_raw_response(chunk_path, result_json, raw_spec))
        result_paths.append(result_json)
        raw_specs.append(raw_spec)

    transcript_spec = transcript_artifact_spec(audio_path, result_paths, raw_specs)
    segment_map_path = transcript_path.with_suffix(".segments.json")
    segment_map_spec = transcript_artifact_spec(
        audio_path,
        result_paths,
        raw_specs,
        artifact_type="asr_segment_map",
    )
    if (
        all(raw_reuse)
        and artifacts.assess_artifact(transcript_path, transcript_spec).reusable
        and artifacts.assess_artifact(segment_map_path, segment_map_spec).reusable
    ):
        return {
            "audio": str(audio_path),
            "status": "skipped",
            "transcript": str(transcript_path),
            "chunks": len(chunks),
            "raw_json": [str(path) for path in result_paths],
            "chunks_manifest": str(manifest_path),
            "segment_map": str(segment_map_path),
            "cache_status": "verified",
            "asr_provider": asr_provider,
        }

    parsed_chunks = []
    for index, (chunk_path, result_json) in enumerate(zip(chunks, result_paths, strict=True), start=1):
        entry = entries[index - 1]
        chunk_txt = path_policy.artifact_path(raw_dir, artifact_id, f".chunk-{index:03d}.txt")
        try:
            segments = parse_asr_response(creator_pipeline.read_json(result_json))
        except ASRParseError as error:
            raise ASRParseError(f"{error}; raw response preserved at {result_json}") from error
        atomic_write_text(chunk_txt, render_transcript(segments))
        parsed_chunks.append(
            ChunkTranscript(
                chunk_index=int(entry["chunk_index"]),
                chunk_path=str(chunk_path),
                start_ms=int(entry["start_ms"]),
                end_ms=int(entry["end_ms"]),
                segments=tuple(segments),
            )
        )

    merge_result = merge_chunk_transcripts(parsed_chunks)
    atomic_write_text(transcript_path, render_transcript(list(merge_result.segments)))
    artifacts.write_artifact_manifest(transcript_path, transcript_spec)
    timestamped_starts = [item.start_ms for item in merge_result.segments if item.start_ms is not None]
    creator_pipeline.write_json(
        segment_map_path,
        {
            "schema_version": 1,
            "source_audio": str(audio_path),
            "source_audio_sha256": manifest.get("source_audio_sha256"),
            "chunks_manifest": str(manifest_path),
            "input_segment_count": merge_result.input_segment_count,
            "output_segment_count": len(merge_result.segments),
            "dropped_overlap_count": merge_result.dropped_overlap_count,
            "nonempty_ratio": merge_result.nonempty_ratio,
            "timestamps_monotonic": timestamped_starts == sorted(timestamped_starts),
            "segments": [
                {
                    "segment_index": source.segment_index,
                    "chunk_index": source.chunk_index,
                    "chunk_path": source.chunk_path,
                    "chunk_start_ms": source.chunk_start_ms,
                    "local_source_index": source.local_source_index,
                    "provider": source.provider,
                    "global_start_ms": source.global_start_ms,
                    "global_end_ms": source.global_end_ms,
                }
                for source in merge_result.sources
            ],
        },
    )
    artifacts.write_artifact_manifest(segment_map_path, segment_map_spec)

    return {
        "audio": str(audio_path),
        "status": "transcribed",
        "transcript": str(transcript_path),
        "chunks": len(chunks),
        "raw_json": [str(path) for path in result_paths],
        "chunks_manifest": str(manifest_path),
        "segment_map": str(segment_map_path),
        "cache_status": "raw_verified" if all(raw_reuse) else "raw_refreshed",
        "asr_provider": asr_provider,
    }


def transcribe_one_audio(audio_path: Path, raw_dir: Path, transcript_dir: Path, strict_asr: bool) -> dict:
    artifact_id = path_policy.validate_artifact_id(audio_path.stem)
    transcript_path = path_policy.artifact_path(transcript_dir, artifact_id, ".txt")
    run_dir = transcript_dir.parent
    asr_provider = os.environ.get("ALI_ASR_PROVIDER", settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]).lower()
    task_json = path_policy.artifact_path(raw_dir, artifact_id, ".task.json")
    result_json = path_policy.artifact_path(raw_dir, artifact_id, ".result.json")

    if asr_provider in {"openai-compatible", "compatible", "qwen-compatible"}:
        return transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)

    raw_spec = asr_raw_artifact_spec(audio_path)
    source_json: Path | None = None
    raw_reused = False
    for candidate in (result_json, task_json):
        if artifacts.assess_artifact(candidate, raw_spec).reusable:
            source_json = candidate
            raw_reused = True
            break

    url_source = "cached"
    oss_upload: oss_lifecycle.OSSUpload | None = None
    try:
        if source_json is None:
            url, url_source, oss_upload = audio_public_url(
                audio_path,
                run_dir=run_dir,
                video_id=artifact_id,
            )
            if not url:
                message = "missing AUDIO_PUBLIC_URL_BASE, ALI_ASR_AUDIO_URL_TEMPLATE, or OSS config"
                if strict_asr:
                    raise SystemExit(message)
                return {"audio": str(audio_path), "status": "skipped", "reason": message}

            provider_adapters.transcribe_aliyun_file_url(
                argparse.Namespace(
                    file_url=url,
                    output=str(task_json),
                    result_json=str(result_json),
                    timeout=int(os.environ.get("HTTP_TIMEOUT_SECONDS", settings.DEFAULT_ENV["HTTP_TIMEOUT_SECONDS"])),
                )
            )
            source_json = result_json if result_json.exists() else task_json
            artifacts.write_artifact_manifest(source_json, raw_spec)

        transcript_spec = transcript_artifact_spec(audio_path, [source_json], [raw_spec])
        if raw_reused and artifacts.assess_artifact(transcript_path, transcript_spec).reusable:
            return {
                "audio": str(audio_path),
                "status": "skipped",
                "transcript": str(transcript_path),
                "audio_url_source": url_source,
                "cache_status": "verified",
            }
        creator_pipeline.asr_json_to_transcript(source_json, transcript_path)
        artifacts.write_artifact_manifest(transcript_path, transcript_spec)
    except (Exception, SystemExit):
        if oss_upload is not None:
            oss_lifecycle.finalize_upload(
                run_dir,
                oss_upload,
                asr_outcome="failed",
                delete_callback=provider_adapters.delete_oss_object,
            )
        raise

    cleanup = (
        oss_lifecycle.finalize_upload(
            run_dir,
            oss_upload,
            asr_outcome="succeeded",
            delete_callback=provider_adapters.delete_oss_object,
        )
        if oss_upload is not None
        else None
    )
    row = {
        "audio": str(audio_path),
        "status": "transcribed",
        "transcript": str(transcript_path),
        "audio_url_source": url_source,
        "cache_status": "raw_verified" if raw_reused else "raw_refreshed",
    }
    if oss_upload is not None and cleanup is not None:
        row.update(
            {
                "oss_object_key": oss_upload.object_key,
                "oss_cleanup_status": cleanup.cleanup_status,
            }
        )
        if cleanup.retain_until:
            row["oss_retain_until"] = cleanup.retain_until
        if cleanup.cleanup_issue:
            row["cleanup_issue"] = cleanup.cleanup_issue
    return row


def transcribe_audio_files(run_dir: Path, env_path: Path | None, strict_asr: bool) -> list[dict]:
    audio_dir = run_dir / "media" / "audio"
    raw_dir = run_dir / "transcripts" / "raw_json"
    transcript_dir = run_dir / "transcripts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    audio_paths = []
    for candidate in sorted(audio_dir.iterdir() if audio_dir.exists() else []):
        path_policy.validate_artifact_id(candidate.stem)
        contained = path_policy.resolve_within(audio_dir, candidate.name)
        if contained.is_file():
            audio_paths.append(contained)
    asr_provider = os.environ.get("ALI_ASR_PROVIDER", settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]).lower()
    if asr_provider in {"openai-compatible", "compatible", "qwen-compatible"}:
        concurrency, _max_audio_bytes = validate_asr_memory_budget(os.environ)
    else:
        concurrency = validate_asr_concurrency(os.environ)
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(audio_paths)))) as executor:
        futures = {
            executor.submit(transcribe_one_audio, audio_path, raw_dir, transcript_dir, strict_asr): audio_path
            for audio_path in audio_paths
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results = sorted(
        (redaction.scrub_diagnostic_fields(row) for row in results),
        key=lambda row: row.get("audio", ""),
    )
    creator_pipeline.write_json(run_dir / "logs" / "asr_status.json", {"count": len(results), "results": results})
    return results


def transcribe_audio_files_step(run_dir: Path, env_path: Path | None, strict_asr: bool) -> StepResult:
    started = time.monotonic()
    rows = transcribe_audio_files(run_dir, env_path, strict_asr)
    return StepResult.from_rows(
        "transcribe_with_aliyun_asr",
        rows,
        duration_ms=round((time.monotonic() - started) * 1000),
        output_paths=(str(run_dir / "logs" / "asr_status.json"),),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Thousand Faces Style Skill end-to-end")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--project-name", required=True, type=project_name_argument)
    parser.add_argument("--sample-count", type=sample_count_argument, default=50)
    parser.add_argument("--metadata-fetch-limit", type=metadata_fetch_limit_argument)
    parser.add_argument("--run-root")
    parser.add_argument("--env")
    build_creator_skill.add_taxonomy_arguments(parser)
    parser.add_argument(
        "--rights-basis",
        choices=provenance.RIGHTS_BASES,
        default="unspecified",
        help="Auditable source-rights basis; unspecified is draft-only",
    )
    parser.add_argument("--authorization-reference-id")
    parser.add_argument("--authorization-note-path")
    parser.add_argument(
        "--retention-policy",
        choices=provenance.RETENTION_POLICIES,
        default="retain_media",
    )
    parser.add_argument(
        "--takedown-contact",
        default=provenance.TAKEDOWN_CONTACT_NOT_PROVIDED,
    )
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
    try:
        active_settings = settings.load_settings(
            env_path,
            overrides={"RUN_ROOT": args.run_root},
            install=True,
        )
    except settings.SettingsError as exc:
        parser.error(str(exc))
    config = active_settings.as_env()
    missing = build_creator_skill.missing_required(config)
    if args.strict_config and missing:
        raise SystemExit("missing required config: " + ", ".join(missing))

    try:
        run_dir = build_creator_skill.create_run(args, active_settings)
    except InputValidationError as exc:
        parser.error(str(exc))
    print(f"[run] created {run_dir}")
    event_logger = logging_utils.StructuredRunLogger(
        run_dir,
        known_secrets=redaction.configured_secrets(),
    )
    event_logger.pipeline_started(message="run directory created")

    current_step = ""
    current_timer: logging_utils.StepTimer | None = None
    step_results: list[StepResult] = []
    quality_passed: bool | None = None
    quality_report: dict | None = None

    def start_step(step_id: str, note: str = "") -> None:
        nonlocal current_step, current_timer
        current_step = step_id
        current_timer = event_logger.step_started(step_id, message=note)
        creator_pipeline.update_workflow_state(run_dir, step_id, "running", note)

    def finish_step(result: StepResult | str = "succeeded", note: str = "") -> StepResult:
        nonlocal current_step, current_timer
        if not current_step or current_timer is None:
            raise RuntimeError("cannot finish a pipeline step before it starts")
        if isinstance(result, str):
            normalized = "succeeded" if result == "completed" else result
            if normalized == "succeeded":
                step_result = StepResult.succeeded(current_step)
            elif normalized == "skipped":
                step_result = StepResult.skipped(current_step, issues=(note,) if note else ())
            elif normalized == "failed":
                step_result = StepResult.failed(current_step, issues=(note,) if note else ())
            else:
                raise ValueError(f"unsupported terminal step status: {result}")
        else:
            step_result = result
        if step_result.step_id != current_step:
            raise ValueError(f"step result mismatch: expected {current_step}, got {step_result.step_id}")
        workflow_note = note or "; ".join(step_result.issues[:3])
        creator_pipeline.update_workflow_state(run_dir, current_step, step_result.status, workflow_note)
        step_result = event_logger.step_finished(
            current_timer,
            step_result,
            message=workflow_note,
        )
        step_results.append(step_result)
        current_step = ""
        current_timer = None
        return step_result

    raw_metadata = run_dir / "metadata" / "raw.json"
    normalized_metadata = run_dir / "metadata" / "normalized.json"
    selected_metadata = run_dir / "metadata" / "selected.json"
    selected_compact_metadata = run_dir / "metadata" / "selected.compact.json"
    creator_profile = run_dir / "metadata" / "creator_profile.json"

    try:
        start_step("parse_creator_url")
        finish_step("succeeded", "run directory created")

        if args.raw_metadata:
            start_step("fetch_creator_videos_with_tikhub", "using existing raw metadata")
            shutil.copy2(Path(args.raw_metadata).expanduser(), raw_metadata)
            print(f"[metadata] copied {raw_metadata}")
            finish_step("succeeded", "copied raw metadata")
        elif not args.skip_fetch:
            start_step("fetch_creator_videos_with_tikhub")
            provider_adapters.fetch_tikhub_creator_videos(
                argparse.Namespace(
                    source_url=args.source_url,
                    limit=args.metadata_fetch_limit or int(config["TIKHUB_METADATA_FETCH_LIMIT"]),
                    output=str(raw_metadata),
                    timeout=int(config["HTTP_TIMEOUT_SECONDS"]),
                )
            )
            print(f"[metadata] fetched {raw_metadata}")
            finish_step("succeeded", "fetched raw metadata")
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
            selected_payload = creator_pipeline.read_json(selected_metadata)
            selected_count = int(selected_payload.get("selected_count") or 0)
            finish_step(
                StepResult.succeeded("select_recent_samples", input_count=selected_count),
                "normalized and selected samples",
            )
        else:
            finish_step("skipped", "raw metadata was not available")

        start_step("download_videos")
        if selected_metadata.exists() and not args.skip_download:
            download_result = creator_pipeline.download_videos_step(
                selected_metadata,
                run_dir / "media" / "videos",
                run_dir / "logs",
            )
            print("[download] done")
            finish_step(download_result)
        else:
            finish_step("skipped", "--skip-download was set or selected metadata was missing")

        start_step("extract_audio_with_ffmpeg")
        if not args.skip_audio:
            audio_result = creator_pipeline.extract_audio_step(
                run_dir / "media" / "videos",
                run_dir / "media" / "audio",
            )
            print("[audio] done")
            finish_step(audio_result)
        else:
            finish_step("skipped", "--skip-audio was set")

        start_step("transcribe_with_aliyun_asr")
        if args.transcripts_dir:
            copy_existing_transcripts(
                Path(args.transcripts_dir).expanduser(),
                run_dir / "transcripts",
                selected_path=selected_metadata,
            )
            print("[transcripts] copied existing transcripts")
            finish_step(
                transcript_coverage_step_result("transcribe_with_aliyun_asr", run_dir),
                "copied existing transcripts and compared them with selected videos",
            )
        elif not args.skip_asr:
            asr_result = transcribe_audio_files_step(run_dir, env_path, args.strict_asr)
            print("[asr] done")
            finish_step(asr_result)
        else:
            finish_step("skipped", "--skip-asr was set")

        start_step("normalize_transcripts")
        transcript_paths = path_policy.artifact_files(run_dir / "transcripts", ".txt")
        if transcript_paths:
            finish_step(
                transcript_coverage_step_result("normalize_transcripts", run_dir),
                "transcript text files were compared with selected videos",
            )
        else:
            finish_step(
                StepResult.failed("normalize_transcripts", issues=("no transcript text files found",))
            )

        start_step("research_creator_style")
        research_result = creator_pipeline.summarize_transcripts_step(
            run_dir / "transcripts",
            run_dir / "research" / "merged",
            overwrite=False,
        )
        print("[research] transcript summary done; use the host agent to read transcripts and refine the generated skill")
        finish_step(research_result, "deterministic transcript summary written")

        start_step("build_creator_skill")
        build_result = creator_pipeline.build_creator_skill_step(run_dir, args.project_name, overwrite=False)
        skill_dir = run_dir / "skill"
        print(f"[skill] built {skill_dir}")
        finish_step(build_result)

        start_step("quality_check")
        quality_result, quality_report = creator_pipeline.creator_quality_check_step(run_dir)
        quality_passed = bool(quality_report.get("passed"))
        print(f"[quality] {'passed' if quality_report['passed'] else 'failed'}")
        print(
            "[quality] commercial delivery "
            f"{'ready' if quality_report.get('commercial_delivery_ready') else 'not ready'}"
        )
        if not quality_report.get("ready_for_use"):
            print("[quality] draft requires host-agent refinement before direct use")
            print(f"[next] python scripts/prepare_host_refinement.py --run-dir {run_dir}")
        finish_step(quality_result, "quality gate executed")
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

    if missing:
        print("warning: missing config for full live execution: " + ", ".join(missing))
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
    return pipeline_result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
