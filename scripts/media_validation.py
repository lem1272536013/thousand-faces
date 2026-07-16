#!/usr/bin/env python3
"""Fail-closed validation for downloaded video files."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


SNIFF_BYTES = 4096
MAX_PROBE_SIZE_BYTES = 10 * 1024 * 1024
MAX_ANALYZE_DURATION_MICROSECONDS = 10_000_000
_SAFE_LABEL = re.compile(r"[^a-zA-Z0-9,._+-]+")


class MediaValidationError(ValueError):
    """A stable, non-sensitive media authentication failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(f"[{code}] {message}")


def _safe_label(value: object, fallback: str = "unknown") -> str:
    text = _SAFE_LABEL.sub("", str(value or "").strip())[:200]
    return text or fallback


def _positive_float(value: object) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _positive_dimension(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed <= 65_535 else None


def _reject_obvious_non_media(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            prefix = stream.read(SNIFF_BYTES).lstrip().lower()
    except OSError as exc:
        raise MediaValidationError("MEDIA_READ_FAILED", "downloaded payload cannot be inspected") from exc
    if not prefix:
        raise MediaValidationError("MEDIA_EMPTY", "downloaded payload is empty")
    html_markers = (b"<!doctype html", b"<html", b"<head", b"<body", b"<?xml")
    if prefix.startswith(html_markers) or prefix.startswith((b"{", b"[")):
        raise MediaValidationError(
            "MEDIA_CONTENT_REJECTED",
            "downloaded payload is HTML, XML, or JSON rather than video",
        )


def _probe_command(ffprobe_bin: str, path: Path) -> list[str]:
    return [
        ffprobe_bin,
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-probesize",
        str(MAX_PROBE_SIZE_BYTES),
        "-analyzeduration",
        str(MAX_ANALYZE_DURATION_MICROSECONDS),
        "-show_entries",
        "format=format_name,duration:stream=codec_type,codec_name,width,height,duration",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]


def validate_media_file(
    path: Path,
    *,
    ffprobe_bin: str,
    timeout_seconds: int,
) -> dict[str, int | str]:
    """Authenticate a local video and return bounded, manifest-safe metadata."""

    source = Path(path)
    if timeout_seconds < 1:
        raise MediaValidationError("MEDIA_PROBE_CONFIG_INVALID", "media probe timeout must be positive")
    if not source.is_file():
        raise MediaValidationError("MEDIA_FILE_MISSING", "downloaded payload is missing")
    _reject_obvious_non_media(source)

    command = _probe_command(ffprobe_bin, source)
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaValidationError(
            "MEDIA_PROBE_TIMEOUT",
            "media inspection exceeded its configured timeout",
        ) from exc
    except OSError as exc:
        raise MediaValidationError(
            "MEDIA_PROBE_UNAVAILABLE",
            "ffprobe is unavailable or could not be started",
        ) from exc
    if process.returncode != 0:
        raise MediaValidationError("MEDIA_PROBE_FAILED", "ffprobe rejected the downloaded payload")
    try:
        payload = json.loads(process.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MediaValidationError("MEDIA_PROBE_INVALID", "ffprobe returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise MediaValidationError("MEDIA_PROBE_INVALID", "ffprobe returned an invalid result object")

    raw_streams = payload.get("streams")
    streams = [stream for stream in raw_streams if isinstance(stream, Mapping)] if isinstance(raw_streams, list) else []
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if not video_streams:
        raise MediaValidationError(
            "MEDIA_VIDEO_STREAM_MISSING",
            "downloaded payload does not contain a video stream",
        )

    raw_format = payload.get("format")
    media_format: Mapping[str, Any] = raw_format if isinstance(raw_format, Mapping) else {}
    duration = _positive_float(media_format.get("duration"))
    if duration is None:
        durations = [_positive_float(stream.get("duration")) for stream in streams]
        valid_durations = [value for value in durations if value is not None]
        duration = max(valid_durations, default=None)
    if duration is None:
        raise MediaValidationError(
            "MEDIA_DURATION_INVALID",
            "downloaded payload has no positive finite duration",
        )

    first_video = video_streams[0]
    width = _positive_dimension(first_video.get("width"))
    height = _positive_dimension(first_video.get("height"))
    if width is None or height is None:
        raise MediaValidationError(
            "MEDIA_DIMENSIONS_INVALID",
            "downloaded payload has invalid video dimensions",
        )

    return {
        "format_name": _safe_label(media_format.get("format_name")),
        "duration_ms": round(duration * 1000),
        "size_bytes": source.stat().st_size,
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "video_codec": _safe_label(first_video.get("codec_name")),
        "width": width,
        "height": height,
    }
