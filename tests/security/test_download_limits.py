"""Bounded, authenticated downloads must fail closed without reusable partial files."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

import artifacts
import creator_pipeline
import media_validation


VALID_MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
VALID_MEDIA_INFO = {
    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
    "duration_ms": 1250,
    "size_bytes": len(VALID_MP4_BYTES),
    "video_stream_count": 1,
    "audio_stream_count": 1,
    "video_codec": "h264",
    "width": 1080,
    "height": 1920,
}


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        content_type: str | None = "video/mp4",
        content_length: int | str | None = None,
    ) -> None:
        super().__init__(payload)
        self.status = status
        self.headers: dict[str, str] = {}
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def geturl(self) -> str:
        return "https://cdn.example.invalid/final.mp4?Signature=redacted"


class NoReadResponse(FakeResponse):
    def read(self, _size: int = -1) -> bytes:
        raise AssertionError("response body must not be read")


def item(video_id: str = "video-a", url: str = "https://cdn.example.invalid/video.mp4") -> dict[str, str]:
    return {"platform_video_id": video_id, "download_url": url}


def download(
    output_dir: Path,
    *,
    max_bytes: int,
    timeout: int = 5,
    deadline_seconds: int = 30,
    retries: int = 1,
) -> dict[str, Any]:
    return creator_pipeline.download_one(
        item(),
        output_dir,
        timeout=timeout,
        retries=retries,
        max_bytes=max_bytes,
        deadline_seconds=deadline_seconds,
        probe_timeout_seconds=5,
    )


def assert_no_download_artifacts(output_dir: Path) -> None:
    final_path = output_dir / "video-a.mp4"
    assert not final_path.exists()
    assert not (output_dir / "video-a.mp4.part").exists()
    assert not artifacts.artifact_manifest_path(final_path).exists()


def test_declared_oversize_is_rejected_before_body_read_and_cleans_old_part(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    (output_dir / "video-a.mp4.part").write_bytes(b"stale partial bytes")
    response = NoReadResponse(b"ignored", content_length=1000)
    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        creator_pipeline.media_validation,
        "validate_media_file",
        lambda *_args, **_kwargs: pytest.fail("oversize response must not reach media validation"),
    )

    result = download(output_dir, max_bytes=32)

    assert result["status"] == "failed"
    assert "DOWNLOAD_TOO_LARGE" in result["error"]
    assert_no_download_artifacts(output_dir)


def test_stream_without_content_length_stops_before_writing_over_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    response = FakeResponse(b"x" * 33, content_length=None)
    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        creator_pipeline.media_validation,
        "validate_media_file",
        lambda *_args, **_kwargs: pytest.fail("oversize response must not reach media validation"),
    )

    result = download(output_dir, max_bytes=32)

    assert result["status"] == "failed"
    assert "DOWNLOAD_TOO_LARGE" in result["error"]
    assert_no_download_artifacts(output_dir)


@pytest.mark.parametrize(
    ("status", "content_type", "error_code"),
    [
        (206, "video/mp4", "DOWNLOAD_HTTP_STATUS"),
        (200, "text/html", "DOWNLOAD_CONTENT_TYPE"),
        (200, "application/json", "DOWNLOAD_CONTENT_TYPE"),
        (200, None, "DOWNLOAD_CONTENT_TYPE"),
    ],
)
def test_status_and_content_type_are_validated_before_body_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    content_type: str | None,
    error_code: str,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    response = NoReadResponse(VALID_MP4_BYTES, status=status, content_type=content_type, content_length=len(VALID_MP4_BYTES))
    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", lambda *_args, **_kwargs: response)

    result = download(output_dir, max_bytes=1024)

    assert result["status"] == "failed"
    assert error_code in result["error"]
    assert_no_download_artifacts(output_dir)


def test_declared_length_must_match_streamed_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    response = FakeResponse(VALID_MP4_BYTES, content_length=len(VALID_MP4_BYTES) + 1)
    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", lambda *_args, **_kwargs: response)

    result = download(output_dir, max_bytes=1024)

    assert result["status"] == "failed"
    assert "DOWNLOAD_LENGTH_MISMATCH" in result["error"]
    assert_no_download_artifacts(output_dir)


def test_deadline_is_enforced_during_streaming_and_partial_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    response = NoReadResponse(VALID_MP4_BYTES, content_length=None)
    ticks = iter([0.0, 0.0, 6.0])
    monkeypatch.setattr(creator_pipeline.time, "monotonic", lambda: next(ticks, 6.0))
    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", lambda *_args, **_kwargs: response)

    result = download(output_dir, max_bytes=1024, timeout=2, deadline_seconds=5)

    assert result["status"] == "failed"
    assert "DOWNLOAD_DEADLINE_EXCEEDED" in result["error"]
    assert_no_download_artifacts(output_dir)


def test_valid_media_is_atomically_published_with_hash_and_probe_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    response = FakeResponse(VALID_MP4_BYTES, content_length=len(VALID_MP4_BYTES))
    opened_with: dict[str, object] = {}

    def fake_open_url(*_args: object, **kwargs: object) -> FakeResponse:
        opened_with.update(kwargs)
        return response

    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", fake_open_url)
    monkeypatch.setattr(
        creator_pipeline.media_validation,
        "validate_media_file",
        lambda *_args, **_kwargs: dict(VALID_MEDIA_INFO),
    )

    result = download(output_dir, max_bytes=1024, timeout=7)

    final_path = output_dir / "video-a.mp4"
    manifest = json.loads(artifacts.artifact_manifest_path(final_path).read_text(encoding="utf-8"))
    assert result["status"] == "downloaded"
    assert final_path.read_bytes() == VALID_MP4_BYTES
    assert not (output_dir / "video-a.mp4.part").exists()
    assert opened_with["timeout"] == 7
    assert manifest["artifact"]["sha256"] == hashlib.sha256(VALID_MP4_BYTES).hexdigest()
    assert manifest["metadata"]["media"] == VALID_MEDIA_INFO
    assert manifest["metadata"]["content_type"] == "video/mp4"


def test_failed_media_probe_removes_partial_and_never_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    response = FakeResponse(VALID_MP4_BYTES, content_length=len(VALID_MP4_BYTES))
    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", lambda *_args, **_kwargs: response)

    def reject(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise media_validation.MediaValidationError("MEDIA_PROBE_FAILED", "ffprobe rejected the payload")

    monkeypatch.setattr(creator_pipeline.media_validation, "validate_media_file", reject)

    result = download(output_dir, max_bytes=1024, retries=3)

    assert result["status"] == "failed"
    assert "MEDIA_PROBE_FAILED" in result["error"]
    assert_no_download_artifacts(output_dir)


def test_duplicate_video_id_is_downloaded_once_and_reported_for_each_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "selected.json"
    creator_pipeline.write_json(selected, {"items": [item(), item()]})
    calls: list[str] = []

    def fake_download_one(row: dict[str, str], output_dir: Path, *_args: object, **_kwargs: object) -> dict[str, str]:
        video_id = row["platform_video_id"]
        calls.append(video_id)
        path = output_dir / f"{video_id}.mp4"
        path.write_bytes(VALID_MP4_BYTES)
        return {"video_id": video_id, "status": "downloaded", "path": str(path), "cache_status": "artifact_missing"}

    monkeypatch.setattr(creator_pipeline, "download_one", fake_download_one)

    status_path = creator_pipeline.download_videos(selected, tmp_path / "videos", tmp_path / "logs")
    payload = creator_pipeline.read_json(status_path)

    assert calls == ["video-a"]
    assert payload["count"] == 2
    assert [row["status"] for row in payload["results"]] == ["downloaded", "skipped"]
    assert payload["results"][1]["duplicate"] is True
    assert payload["results"][1]["cache_status"] == "verified"


def test_duplicate_video_id_with_conflicting_urls_fails_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "selected.json"
    creator_pipeline.write_json(
        selected,
        {
            "items": [
                item(url="https://cdn.example.invalid/a.mp4"),
                item(url="https://cdn.example.invalid/b.mp4"),
            ]
        },
    )
    monkeypatch.setattr(
        creator_pipeline,
        "download_one",
        lambda *_args, **_kwargs: pytest.fail("conflicting duplicate IDs must not reach downloader"),
    )

    status_path = creator_pipeline.download_videos(selected, tmp_path / "videos", tmp_path / "logs")
    payload = creator_pipeline.read_json(status_path)

    assert payload["count"] == 2
    assert all(row["status"] == "failed" for row in payload["results"])
    assert all("DOWNLOAD_ID_CONFLICT" in row["error"] for row in payload["results"])
