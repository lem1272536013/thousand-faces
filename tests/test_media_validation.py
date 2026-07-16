"""Actual media content must be authenticated before becoming a reusable artifact."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import media_validation


def mp4_like_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41"


def valid_probe_payload() -> dict[str, object]:
    return {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "1.250000",
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "duration": "1.250000",
            },
            {"codec_type": "audio", "codec_name": "aac", "duration": "1.250000"},
        ],
    }


def test_valid_video_records_bounded_media_information(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "sample.mp4.part"
    video.write_bytes(mp4_like_bytes())
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(valid_probe_payload()), "")

    monkeypatch.setattr(media_validation.subprocess, "run", fake_run)

    result = media_validation.validate_media_file(video, ffprobe_bin="safe-ffprobe", timeout_seconds=7)

    assert result == {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration_ms": 1250,
        "size_bytes": len(mp4_like_bytes()),
        "video_stream_count": 1,
        "audio_stream_count": 1,
        "video_codec": "h264",
        "width": 1080,
        "height": 1920,
    }
    command, kwargs = calls[0]
    assert command[0] == "safe-ffprobe"
    assert "-show_format" in command
    assert "-show_streams" in command
    assert command[-1] == str(video)
    assert kwargs["timeout"] == 7
    assert kwargs["check"] is False
    assert "shell" not in kwargs


@pytest.mark.parametrize(
    "payload",
    [
        b"<!doctype html><html><body>login</body></html>",
        b"  {\"error\": \"signed URL expired\"}",
        b"\n[ {\"message\": \"not media\"} ]",
    ],
)
def test_obvious_html_and_json_payloads_are_rejected_before_ffprobe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    video = tmp_path / "forged.mp4.part"
    video.write_bytes(payload)
    monkeypatch.setattr(
        media_validation.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("obvious non-media must not reach ffprobe"),
    )

    with pytest.raises(media_validation.MediaValidationError, match="MEDIA_CONTENT_REJECTED"):
        media_validation.validate_media_file(video, ffprobe_bin="ffprobe", timeout_seconds=5)


@pytest.mark.parametrize(
    ("process", "error_code"),
    [
        (subprocess.CompletedProcess(["ffprobe"], 1, "", "invalid data"), "MEDIA_PROBE_FAILED"),
        (subprocess.CompletedProcess(["ffprobe"], 0, "{broken", ""), "MEDIA_PROBE_INVALID"),
        (
            subprocess.CompletedProcess(
                ["ffprobe"],
                0,
                json.dumps({"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]}),
                "",
            ),
            "MEDIA_VIDEO_STREAM_MISSING",
        ),
        (
            subprocess.CompletedProcess(
                ["ffprobe"],
                0,
                json.dumps(
                    {
                        "format": {"duration": "0"},
                        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1, "height": 1}],
                    }
                ),
                "",
            ),
            "MEDIA_DURATION_INVALID",
        ),
    ],
)
def test_ffprobe_failure_or_non_video_structure_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    process: subprocess.CompletedProcess[str],
    error_code: str,
) -> None:
    video = tmp_path / "untrusted.mp4.part"
    video.write_bytes(mp4_like_bytes())
    monkeypatch.setattr(media_validation.subprocess, "run", lambda *_args, **_kwargs: process)

    with pytest.raises(media_validation.MediaValidationError, match=error_code):
        media_validation.validate_media_file(video, ffprobe_bin="ffprobe", timeout_seconds=5)


def test_ffprobe_timeout_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "slow.mp4.part"
    video.write_bytes(mp4_like_bytes())

    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("ffprobe", timeout=3)

    monkeypatch.setattr(media_validation.subprocess, "run", timeout)

    with pytest.raises(media_validation.MediaValidationError, match="MEDIA_PROBE_TIMEOUT"):
        media_validation.validate_media_file(video, ffprobe_bin="ffprobe", timeout_seconds=3)
