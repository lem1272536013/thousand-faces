"""Creator media download, extraction, and transcript preparation."""

from __future__ import annotations

import concurrent.futures
import math
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import artifacts
import media_validation
import network_policy
import path_policy
import redaction
import settings
from asr_parsers import ASRParseError, parse_asr_response, render_transcript
from creator_metadata import read_json
from input_validation import (
    DOWNLOAD_CONCURRENCY_RANGE,
    FFMPEG_CONCURRENCY_RANGE,
    validate_bounded_int,
)
from io_utils import atomic_write_json as write_json
from io_utils import atomic_write_text
from pipeline_models import StepResult


DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_VIDEO_BYTES = 512 * 1024 * 1024
DEFAULT_DOWNLOAD_HEADER_TIMEOUT_SECONDS = 30
DEFAULT_DOWNLOAD_DEADLINE_SECONDS = 300
DEFAULT_MEDIA_PROBE_TIMEOUT_SECONDS = 30
_DOWNLOAD_TARGET_LOCKS: dict[str, threading.Lock] = {}
_DOWNLOAD_TARGET_LOCKS_GUARD = threading.Lock()


class DownloadValidationError(ValueError):
    """A stable download failure that must not be retried."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(f"[{code}] {message}")


def download_artifact_spec(
    url: str,
    timeout: int,
    retries: int,
    *,
    max_bytes: int,
    deadline_seconds: int,
    probe_timeout_seconds: int,
    ffprobe_bin: str,
) -> artifacts.ArtifactSpec:
    return artifacts.ArtifactSpec(
        artifact_type="downloaded_video",
        inputs=(artifacts.safe_url_input(url, role="source_url"),),
        config={
            "header_timeout_seconds": timeout,
            "deadline_seconds": deadline_seconds,
            "max_bytes": max_bytes,
            "media_probe_timeout_seconds": probe_timeout_seconds,
            "ffprobe_binary": Path(ffprobe_bin).name,
            "retry_count": retries,
            "user_agent_profile": "mozilla_5",
        },
        producer={"name": "creator_pipeline.download_one", "version": "2"},
    )


def download_response_metadata(response: Any) -> dict[str, Any]:
    """Extract a bounded, non-sensitive allowlist from an HTTP response."""

    metadata: dict[str, Any] = {}
    status = getattr(response, "status", None)
    if isinstance(status, int):
        metadata["http_status"] = status
    headers = getattr(response, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        content_type = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", content_type):
            metadata["content_type"] = content_type
        content_length = str(headers.get("Content-Length") or "").strip()
        if content_length.isdigit():
            metadata["content_length_bytes"] = int(content_length)
    geturl = getattr(response, "geturl", None)
    if callable(geturl):
        final_url = geturl()
        if isinstance(final_url, str) and final_url:
            try:
                metadata["final_url"] = artifacts.safe_url_input(final_url, role="final_url")
            except artifacts.ArtifactManifestError:
                metadata["final_url_valid"] = False
    return metadata


def _download_target_lock(path: Path) -> threading.Lock:
    key = str(path.resolve(strict=False)).casefold()
    with _DOWNLOAD_TARGET_LOCKS_GUARD:
        return _DOWNLOAD_TARGET_LOCKS.setdefault(key, threading.Lock())


def _remove_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise DownloadValidationError(
            "DOWNLOAD_PART_CLEANUP_FAILED",
            "stale or failed partial download could not be removed",
        ) from exc


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        value = getcode()
        return value if isinstance(value, int) else None
    return None


def validate_download_response(response: Any, max_bytes: int) -> tuple[int | None, dict[str, Any]]:
    """Validate headers before reading an untrusted response body."""

    status = _response_status(response)
    if status != 200:
        raise DownloadValidationError(
            "DOWNLOAD_HTTP_STATUS",
            "video download did not return a complete HTTP 200 response",
        )
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        raise DownloadValidationError(
            "DOWNLOAD_HEADERS_MISSING",
            "video download response is missing required headers",
        )
    content_type = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    allowed_application_types = {"application/mp4", "application/octet-stream", "binary/octet-stream"}
    if not (content_type.startswith("video/") or content_type in allowed_application_types):
        raise DownloadValidationError(
            "DOWNLOAD_CONTENT_TYPE",
            "video download response has a missing or unsupported Content-Type",
        )

    content_length: int | None = None
    raw_content_length = str(headers.get("Content-Length") or "").strip()
    if raw_content_length:
        if not raw_content_length.isdigit():
            raise DownloadValidationError(
                "DOWNLOAD_CONTENT_LENGTH_INVALID",
                "video download response has an invalid Content-Length",
            )
        content_length = int(raw_content_length)
        if content_length <= 0:
            raise DownloadValidationError(
                "DOWNLOAD_CONTENT_LENGTH_INVALID",
                "video download response has a non-positive Content-Length",
            )
        if content_length > max_bytes:
            raise DownloadValidationError(
                "DOWNLOAD_TOO_LARGE",
                "video download exceeds the configured byte limit",
            )

    metadata = download_response_metadata(response)
    metadata["http_status"] = status
    metadata["content_type"] = content_type
    if content_length is not None:
        metadata["content_length_bytes"] = content_length
    return content_length, metadata


def _set_response_read_timeout(response: Any, remaining_seconds: float) -> None:
    """Best-effort bound for the next urllib socket read."""

    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    settimeout = getattr(sock, "settimeout", None)
    if callable(settimeout):
        settimeout(max(0.001, remaining_seconds))


def stream_download_response(
    response: Any,
    part_path: Path,
    *,
    max_bytes: int,
    expected_length: int | None,
    deadline_at: float,
) -> int:
    """Stream to a partial file without ever publishing an oversized body."""

    total = 0
    with part_path.open("wb") as handle:
        while True:
            remaining_seconds = deadline_at - time.monotonic()
            if remaining_seconds <= 0:
                raise DownloadValidationError(
                    "DOWNLOAD_DEADLINE_EXCEEDED",
                    "video download exceeded its total deadline",
                )
            _set_response_read_timeout(response, remaining_seconds)
            chunk = response.read(min(DOWNLOAD_CHUNK_SIZE, max_bytes - total + 1))
            if deadline_at - time.monotonic() < 0:
                raise DownloadValidationError(
                    "DOWNLOAD_DEADLINE_EXCEEDED",
                    "video download exceeded its total deadline",
                )
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise DownloadValidationError(
                    "DOWNLOAD_BODY_INVALID",
                    "video download returned a non-binary response body",
                )
            if total + len(chunk) > max_bytes:
                raise DownloadValidationError(
                    "DOWNLOAD_TOO_LARGE",
                    "video download exceeds the configured byte limit",
                )
            handle.write(chunk)
            total += len(chunk)
        handle.flush()
        os.fsync(handle.fileno())

    if total <= 0:
        raise DownloadValidationError("DOWNLOAD_EMPTY", "video download returned an empty body")
    if expected_length is not None and total != expected_length:
        raise DownloadValidationError(
            "DOWNLOAD_LENGTH_MISMATCH",
            "downloaded byte count does not match Content-Length",
        )
    return total


def _validate_download_options(
    timeout: int,
    retries: int,
    max_bytes: int,
    deadline_seconds: int,
    probe_timeout_seconds: int,
) -> None:
    if min(timeout, retries, max_bytes, deadline_seconds, probe_timeout_seconds) < 1:
        raise DownloadValidationError(
            "DOWNLOAD_CONFIG_INVALID",
            "download limits, retries, and timeouts must be positive integers",
        )
    if deadline_seconds < timeout:
        raise DownloadValidationError(
            "DOWNLOAD_CONFIG_INVALID",
            "download deadline cannot be shorter than the response header timeout",
        )


def download_one(
    item: dict,
    output_dir: Path,
    timeout: int,
    retries: int,
    *,
    max_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
    deadline_seconds: int = DEFAULT_DOWNLOAD_DEADLINE_SECONDS,
    probe_timeout_seconds: int = DEFAULT_MEDIA_PROBE_TIMEOUT_SECONDS,
) -> dict:
    try:
        platform_video_id = path_policy.validate_platform_video_id(
            item.get("platform_video_id") or "video"
        )
        artifact_id = path_policy.artifact_id_for_item(item)
        final_path = path_policy.artifact_path(output_dir, artifact_id, ".mp4")
        part_path = path_policy.artifact_path(output_dir, artifact_id, ".mp4.part")
    except (path_policy.VideoIdError, path_policy.PathContainmentError) as exc:
        return {"video_id": "invalid-video-id", "status": "failed", "error": str(exc)}
    identity = {
        "video_id": artifact_id,
        "artifact_id": artifact_id,
        "platform_video_id": platform_video_id,
    }
    url = item.get("download_url")
    if not isinstance(url, str) or not url:
        return {**identity, "status": "failed", "error": "missing download_url"}
    try:
        _validate_download_options(timeout, retries, max_bytes, deadline_seconds, probe_timeout_seconds)
        ffprobe_bin = os.environ.get("FFPROBE_BIN", settings.DEFAULT_ENV["FFPROBE_BIN"])
        spec = download_artifact_spec(
            url,
            timeout,
            retries,
            max_bytes=max_bytes,
            deadline_seconds=deadline_seconds,
            probe_timeout_seconds=probe_timeout_seconds,
            ffprobe_bin=ffprobe_bin,
        )
    except (artifacts.ArtifactManifestError, DownloadValidationError) as error:
        return {**identity, "status": "failed", "error": str(error)}

    output_dir.mkdir(parents=True, exist_ok=True)
    with _download_target_lock(final_path):
        decision = artifacts.assess_artifact(final_path, spec)
        if decision.reusable:
            return {
                **identity,
                "status": "skipped",
                "path": str(final_path),
                "cache_status": decision.reason,
                "manifest": str(decision.manifest_path),
            }

        try:
            _remove_partial(part_path)
        except DownloadValidationError as exc:
            return {**identity, "status": "failed", "error": str(exc)}
        deadline_at = time.monotonic() + deadline_seconds

        for attempt in range(1, retries + 1):
            try:
                remaining_seconds = deadline_at - time.monotonic()
                if remaining_seconds <= 0:
                    raise DownloadValidationError(
                        "DOWNLOAD_DEADLINE_EXCEEDED",
                        "video download exceeded its total deadline",
                    )
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                request_timeout = max(1, min(timeout, math.ceil(remaining_seconds)))
                with network_policy.open_url(
                    request,
                    purpose=network_policy.UNTRUSTED_REMOTE,
                    timeout=request_timeout,
                ) as response:
                    expected_length, response_metadata = validate_download_response(response, max_bytes)
                    stream_download_response(
                        response,
                        part_path,
                        max_bytes=max_bytes,
                        expected_length=expected_length,
                        deadline_at=deadline_at,
                    )
                media_info = media_validation.validate_media_file(
                    part_path,
                    ffprobe_bin=ffprobe_bin,
                    timeout_seconds=probe_timeout_seconds,
                )
                response_metadata["media"] = media_info
                part_path.replace(final_path)
                manifest_path = artifacts.write_artifact_manifest(final_path, spec, metadata=response_metadata)
                return {
                    **identity,
                    "status": "downloaded",
                    "path": str(final_path),
                    "size_bytes": final_path.stat().st_size,
                    "media": media_info,
                    "cache_status": decision.reason,
                    "manifest": str(manifest_path),
                }
            except (DownloadValidationError, media_validation.MediaValidationError) as exc:
                try:
                    _remove_partial(part_path)
                except DownloadValidationError as cleanup_error:
                    return {**identity, "status": "failed", "error": str(cleanup_error)}
                return {**identity, "status": "failed", "error": str(exc)}
            except network_policy.NetworkPolicyError as exc:
                try:
                    _remove_partial(part_path)
                except DownloadValidationError as cleanup_error:
                    return {**identity, "status": "failed", "error": str(cleanup_error)}
                return {**identity, "status": "failed", "error": str(exc)}
            except Exception as exc:  # noqa: BLE001 - provider/network failures are retried and sanitized
                try:
                    _remove_partial(part_path)
                except DownloadValidationError as cleanup_error:
                    return {**identity, "status": "failed", "error": str(cleanup_error)}
                if attempt == retries:
                    return {
                        **identity,
                        "status": "failed",
                        "error": f"[DOWNLOAD_NETWORK_ERROR] download failed after {attempt} attempt(s) ({type(exc).__name__})",
                    }
                remaining_seconds = deadline_at - time.monotonic()
                if remaining_seconds <= 0:
                    return {
                        **identity,
                        "status": "failed",
                        "error": "[DOWNLOAD_DEADLINE_EXCEEDED] video download exceeded its total deadline",
                    }
                time.sleep(min(attempt * 2, 10, remaining_seconds))
        return {**identity, "status": "failed", "error": "unknown download error"}


def _download_group_key(item: dict) -> str:
    return path_policy.artifact_id_for_item(item)


def _duplicate_result(primary: dict[str, Any]) -> dict[str, Any]:
    duplicate = dict(primary)
    duplicate["duplicate"] = True
    duplicate["duplicate_of"] = str(primary.get("video_id") or "video")
    if primary.get("status") in {"downloaded", "skipped"}:
        duplicate["status"] = "skipped"
        duplicate["cache_status"] = "verified"
    return duplicate


def download_videos(
    selected_path: Path,
    output_dir: Path,
    logs_dir: Path,
    *,
    download_fn: Callable[..., dict[str, Any]] | None = None,
) -> Path:
    payload = read_json(selected_path)
    items = payload.get("items", [])
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    concurrency = validate_bounded_int(
        "DOWNLOAD_CONCURRENCY",
        os.environ.get("DOWNLOAD_CONCURRENCY", settings.DEFAULT_ENV["DOWNLOAD_CONCURRENCY"]),
        DOWNLOAD_CONCURRENCY_RANGE,
    )
    retries = int(os.environ.get("DOWNLOAD_RETRY", settings.DEFAULT_ENV["DOWNLOAD_RETRY"]))
    timeout = int(
        os.environ.get(
            "DOWNLOAD_HEADER_TIMEOUT_SECONDS",
            str(DEFAULT_DOWNLOAD_HEADER_TIMEOUT_SECONDS),
        )
    )
    max_bytes = int(os.environ.get("MAX_VIDEO_BYTES", str(DEFAULT_MAX_VIDEO_BYTES)))
    deadline_seconds = int(
        os.environ.get("DOWNLOAD_DEADLINE_SECONDS", str(DEFAULT_DOWNLOAD_DEADLINE_SECONDS))
    )
    probe_timeout_seconds = int(
        os.environ.get("MEDIA_PROBE_TIMEOUT_SECONDS", str(DEFAULT_MEDIA_PROBE_TIMEOUT_SECONDS))
    )

    raw_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    mapped_items, _id_records = path_policy.assign_artifact_ids(raw_items)
    groups: dict[str, list[dict[str, Any]]] = {}
    for normalized_item in mapped_items:
        groups.setdefault(_download_group_key(normalized_item), []).append(normalized_item)

    results: list[dict[str, Any]] = []
    download_groups: list[list[dict[str, Any]]] = []
    for video_id, group in groups.items():
        urls = {
            str(row.get("download_url") or "").strip()
            for row in group
        }
        if len(urls) > 1:
            for index, _row in enumerate(group):
                results.append(
                    {
                        "video_id": video_id,
                        "artifact_id": video_id,
                        "platform_video_id": group[index]["platform_video_id"],
                        "status": "failed",
                        "error": "[DOWNLOAD_ID_CONFLICT] duplicate video ID has conflicting download URLs",
                        "duplicate": index > 0,
                    }
                )
            continue
        download_groups.append(group)

    download_impl = download_fn or download_one
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        future_groups = {
            executor.submit(
                download_impl,
                group[0],
                output_dir,
                timeout,
                retries,
                max_bytes=max_bytes,
                deadline_seconds=deadline_seconds,
                probe_timeout_seconds=probe_timeout_seconds,
            ): group
            for group in download_groups
        }
        for future in concurrent.futures.as_completed(future_groups):
            group = future_groups[future]
            primary = future.result()
            results.append(primary)
            results.extend(_duplicate_result(primary) for _row in group[1:])

    results = [redaction.scrub_diagnostic_fields(row) for row in results]
    output_path = logs_dir / "download_status.json"
    write_json(
        output_path,
        {
            "count": len(results),
            "results": sorted(
                results,
                key=lambda row: (str(row["video_id"]), bool(row.get("duplicate"))),
            ),
        },
    )
    return output_path


def download_videos_step(selected_path: Path, output_dir: Path, logs_dir: Path) -> StepResult:
    started = time.monotonic()
    status_path = download_videos(selected_path, output_dir, logs_dir)
    payload = read_json(status_path)
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    return StepResult.from_rows(
        "download_videos",
        rows if isinstance(rows, list) else [],
        duration_ms=round((time.monotonic() - started) * 1000),
        output_paths=(str(status_path),),
    )


@lru_cache(maxsize=8)
def ffmpeg_version(ffmpeg: str) -> str:
    try:
        proc = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True)
    except OSError as error:
        return f"unavailable:{type(error).__name__}"
    first_line = (proc.stdout or proc.stderr).splitlines()
    if proc.returncode != 0 or not first_line:
        return f"unavailable:exit_{proc.returncode}"
    return first_line[0][:500]


def audio_artifact_spec(
    video_path: Path,
    *,
    ffmpeg_release: str,
    audio_format: str,
    sample_rate: str,
    bitrate: str,
) -> artifacts.ArtifactSpec:
    codec = "libmp3lame" if audio_format in {"mp3", "mpeg"} else "container_default"
    return artifacts.ArtifactSpec(
        artifact_type="extracted_audio",
        inputs=(artifacts.file_input(video_path, role="source_video"),),
        config={
            "ffmpeg_version": ffmpeg_release,
            "audio_format": audio_format,
            "channels": 1,
            "sample_rate": sample_rate,
            "codec": codec,
            "bitrate": bitrate if codec == "libmp3lame" else "not_applicable",
        },
        producer={"name": "creator_pipeline.extract_audio", "version": "1"},
    )


def _extract_one_audio(
    video_path: Path,
    *,
    video_dir: Path,
    audio_dir: Path,
    ffmpeg: str,
    ffmpeg_release: str,
    audio_suffix: str,
    audio_format: str,
    sample_rate: str,
    bitrate: str,
) -> dict[str, Any]:
    try:
        artifact_id = path_policy.validate_artifact_id(video_path.stem)
        source_path = path_policy.resolve_within(video_dir, video_path.name)
        output_path = path_policy.artifact_path(audio_dir, artifact_id, audio_suffix)
    except (path_policy.VideoIdError, path_policy.PathContainmentError) as error:
        return {"video_id": video_path.stem, "status": "failed", "error": str(error)}
    spec = audio_artifact_spec(
        source_path,
        ffmpeg_release=ffmpeg_release,
        audio_format=audio_format,
        sample_rate=sample_rate,
        bitrate=bitrate,
    )
    decision = artifacts.assess_artifact(output_path, spec)
    if decision.reusable:
        return {
            "video_id": video_path.stem,
            "artifact_id": artifact_id,
            "status": "skipped",
            "path": str(output_path),
            "cache_status": decision.reason,
            "manifest": str(decision.manifest_path),
        }
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        sample_rate,
    ]
    if audio_format in {"mp3", "mpeg"}:
        cmd.extend(["-codec:a", "libmp3lame", "-b:a", bitrate])
    cmd.append(str(output_path))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        manifest_path = artifacts.write_artifact_manifest(output_path, spec)
        return {
            "video_id": video_path.stem,
            "artifact_id": artifact_id,
            "status": "extracted",
            "path": str(output_path),
            "cache_status": decision.reason,
            "manifest": str(manifest_path),
        }
    return {
        "video_id": artifact_id,
        "artifact_id": artifact_id,
        "status": "failed",
        "error": proc.stderr[-2000:],
    }


def extract_audio(
    video_dir: Path,
    audio_dir: Path,
    *,
    ffmpeg_version_fn: Callable[[str], str] | None = None,
) -> Path:
    audio_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = os.environ.get("FFMPEG_BIN", settings.DEFAULT_ENV["FFMPEG_BIN"])
    concurrency = validate_bounded_int(
        "FFMPEG_CONCURRENCY",
        os.environ.get("FFMPEG_CONCURRENCY", settings.DEFAULT_ENV["FFMPEG_CONCURRENCY"]),
        FFMPEG_CONCURRENCY_RANGE,
    )
    requested_audio_format = os.environ.get(
        "ALI_ASR_AUDIO_FORMAT", settings.DEFAULT_ENV["ALI_ASR_AUDIO_FORMAT"]
    ).lstrip(".")
    audio_suffix = path_policy.validate_artifact_suffix(f".{requested_audio_format}")
    audio_format = audio_suffix[1:].lower()
    sample_rate = os.environ.get("ASR_SAMPLE_RATE", settings.DEFAULT_ENV["ASR_SAMPLE_RATE"])
    bitrate = os.environ.get("ASR_MP3_BITRATE", settings.DEFAULT_ENV["ASR_MP3_BITRATE"])
    ffmpeg_release = (ffmpeg_version_fn or ffmpeg_version)(ffmpeg)
    video_paths = sorted(video_dir.glob("*.mp4"))
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(concurrency, max(1, len(video_paths)))
    ) as executor:
        futures = [
            executor.submit(
                _extract_one_audio,
                video_path,
                video_dir=video_dir,
                audio_dir=audio_dir,
                ffmpeg=ffmpeg,
                ffmpeg_release=ffmpeg_release,
                audio_suffix=audio_suffix,
                audio_format=audio_format,
                sample_rate=sample_rate,
                bitrate=bitrate,
            )
            for video_path in video_paths
        ]
        results.extend(future.result() for future in futures)
    results.sort(key=lambda row: str(row.get("video_id", "")))
    results = [redaction.scrub_diagnostic_fields(row) for row in results]
    output_status = audio_dir.parent.parent / "logs" / "audio_status.json"
    write_json(output_status, {"count": len(results), "results": results})
    return output_status


def extract_audio_step(video_dir: Path, audio_dir: Path) -> StepResult:
    started = time.monotonic()
    status_path = extract_audio(video_dir, audio_dir)
    payload = read_json(status_path)
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    return StepResult.from_rows(
        "extract_audio_with_ffmpeg",
        rows if isinstance(rows, list) else [],
        duration_ms=round((time.monotonic() - started) * 1000),
        output_paths=(str(status_path),),
    )


def asr_json_to_transcript(input_path: Path, output_path: Path) -> Path:
    data = read_json(input_path)
    try:
        segments = parse_asr_response(data)
    except ASRParseError as error:
        raise ASRParseError(f"{error}; raw response preserved at {input_path}") from error
    atomic_write_text(output_path, render_transcript(segments))
    return output_path


def summarize_transcripts(transcripts_dir: Path, output_dir: Path, overwrite: bool = True) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "summary.md"
    transcript_paths = path_policy.artifact_files(transcripts_dir, ".txt")
    spec = artifacts.ArtifactSpec(
        artifact_type="transcript_summary",
        inputs=tuple(
            artifacts.file_input(path, role=f"transcript:{path.name}") for path in transcript_paths
        ),
        config={"summary_algorithm_version": "1"},
        producer={"name": "creator_pipeline.summarize_transcripts", "version": "1"},
    )
    decision = artifacts.assess_artifact(output_path, spec)
    if decision.reusable and not overwrite:
        return output_path

    rows = []
    all_text = []
    for path in transcript_paths:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        rows.append(f"| {path.stem} | {len(text)} | {len(re.findall(r'[。！？!?]', text))} |")
        all_text.append((path.stem, text))

    top_terms = extract_terms("\n".join(text for _, text in all_text))
    summary = [
        "# Creator Transcript Research Summary",
        "",
        "## Coverage",
        "",
        "| Video | Chars | Sentence-like breaks |",
        "|---|---:|---:|",
        *(rows or ["| none | 0 | 0 |"]),
        "",
        "## Repeated Terms",
        "",
        *(f"- {term}" for term in top_terms[:30]),
        "",
        "## Preliminary Findings",
        "",
        "- This draft is generated from transcripts and should be refined with LLM-assisted style analysis.",
        "- Treat repeated terms, opening patterns, and sentence rhythm as research cues, not final conclusions.",
        "- Keep full transcripts outside the generated skill; only concise evidence notes should be promoted.",
        "- ASR may misrecognize proper nouns, names, brands, and English model names; verify key terms against metadata or source material before finalizing the skill.",
        "",
    ]
    atomic_write_text(output_path, "\n".join(summary))
    artifacts.write_artifact_manifest(output_path, spec)
    return output_path


def summarize_transcripts_step(
    transcripts_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = True,
) -> StepResult:
    started = time.monotonic()
    input_count = len(path_policy.artifact_files(transcripts_dir, ".txt"))
    output_path = summarize_transcripts(transcripts_dir, output_dir, overwrite=overwrite)
    return StepResult.succeeded(
        "research_creator_style",
        input_count=input_count,
        duration_ms=round((time.monotonic() - started) * 1000),
        output_paths=(str(output_path),),
    )


def extract_terms(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
    stop = {
        "这个",
        "一个",
        "我们",
        "你们",
        "他们",
        "就是",
        "然后",
        "因为",
        "所以",
        "但是",
        "the",
        "and",
        "for",
    }
    counts: dict[str, int] = {}
    for token in tokens:
        if token in stop:
            continue
        counts[token] = counts.get(token, 0) + 1
    return [
        f"{term}: {count}"
        for term, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]
