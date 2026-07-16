"""External video identifiers must never control filesystem traversal."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import creator_pipeline
import path_policy
import run_creator_skill_build as runner


def test_path_traversal_fixture_ids_are_rejected(fixture_root: Path) -> None:
    fixture = json.loads((fixture_root / "security" / "path_traversal_ids.json").read_text(encoding="utf-8"))

    for raw_id in fixture["ids"]:
        with pytest.raises(path_policy.VideoIdError):
            path_policy.validate_platform_video_id(raw_id)

    for raw_id in fixture["safe_controls"]:
        assert path_policy.validate_platform_video_id(raw_id) == raw_id


@pytest.mark.parametrize(
    "raw_id",
    [
        ".",
        "..",
        "safe..escape",
        "C:relative-device-path",
        "\\\\server\\share",
        "\\\\?\\C:\\Windows\\system32",
        "\\\\.\\PhysicalDrive0",
        "NUL",
        "nul.txt",
        "PRN",
        "AUX.json",
        "COM1",
        "LPT9.log",
        "trailing-space ",
        "fullwidth／separator",
        "control\x00byte",
    ],
)
def test_cross_platform_dangerous_video_ids_are_rejected(raw_id: str) -> None:
    with pytest.raises(path_policy.VideoIdError):
        path_policy.validate_platform_video_id(raw_id)


@pytest.mark.parametrize(
    "relative",
    [
        "../escape.txt",
        "safe/../../escape.txt",
        "/absolute/path.txt",
        "C:\\Windows\\system32\\drivers\\etc\\hosts",
        "C:drive-relative.txt",
        "\\\\server\\share\\escape.txt",
    ],
)
def test_resolve_within_rejects_escape_and_absolute_paths(tmp_path: Path, relative: str) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(path_policy.PathContainmentError):
        path_policy.resolve_within(root, relative)


def test_resolve_within_accepts_nested_controlled_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    result = path_policy.resolve_within(root, Path("nested") / "artifact.mp4")

    assert result == root.resolve() / "nested" / "artifact.mp4"
    assert result.is_relative_to(root.resolve())


def test_resolve_within_rejects_existing_symlink_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable in this Windows environment")

    with pytest.raises(path_policy.PathContainmentError):
        path_policy.resolve_within(root, Path("linked") / "escape.txt")


def test_normalize_metadata_rejects_malicious_id_before_writing_outputs(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.json"
    output_path = tmp_path / "metadata" / "normalized.json"
    raw_path.write_text(
        json.dumps({"items": [{"aweme_id": "../escape", "play_url": "https://media.example/video.mp4"}]}),
        encoding="utf-8",
    )

    with pytest.raises(path_policy.VideoIdError):
        creator_pipeline.normalize_metadata(raw_path, output_path)

    assert not output_path.exists()
    assert not (output_path.parent / "video_id_map.json").exists()
    assert not (tmp_path / "escape.mp4").exists()


def test_download_rejects_malicious_id_before_network_or_file_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("malicious ID reached the network")

    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", fail_network)

    result = creator_pipeline.download_one(
        {
            "platform_video_id": "..\\escape",
            "download_url": "https://media.example.invalid/video.mp4",
        },
        tmp_path / "videos",
        timeout=5,
        retries=1,
    )

    assert result["status"] == "failed"
    assert "VIDEO_ID" in result["error"]
    assert not list(tmp_path.rglob("*.mp4"))


def test_extract_audio_rejects_unsafe_artifact_stem_before_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_dir = tmp_path / "run" / "media" / "videos"
    audio_dir = tmp_path / "run" / "media" / "audio"
    video_dir.mkdir(parents=True)
    (video_dir / "Unsafe ID.mp4").write_bytes(b"not real media")
    monkeypatch.setattr(creator_pipeline, "ffmpeg_version", lambda _binary: "test")

    def fail_ffmpeg(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("unsafe artifact filename reached ffmpeg")

    monkeypatch.setattr(creator_pipeline.subprocess, "run", fail_ffmpeg)

    status_path = creator_pipeline.extract_audio(video_dir, audio_dir)
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert payload["results"][0]["status"] == "failed"
    assert "ARTIFACT_ID" in payload["results"][0]["error"]
    assert not list(audio_dir.glob("*"))


def test_extract_audio_rejects_path_like_audio_format_before_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_dir = tmp_path / "run" / "media" / "videos"
    audio_dir = tmp_path / "run" / "media" / "audio"
    video_dir.mkdir(parents=True)
    (video_dir / "source.mp4").write_bytes(b"not real media")
    monkeypatch.setenv("ALI_ASR_AUDIO_FORMAT", "../../escape")
    monkeypatch.setattr(creator_pipeline, "ffmpeg_version", lambda _binary: "test")

    def fail_ffmpeg(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("unsafe audio format reached ffmpeg")

    monkeypatch.setattr(creator_pipeline.subprocess, "run", fail_ffmpeg)

    with pytest.raises(path_policy.PathContainmentError, match="PATH_SUFFIX_INVALID"):
        creator_pipeline.extract_audio(video_dir, audio_dir)

    assert not (tmp_path / "run" / "escape").exists()


def test_chunk_artifact_paths_reject_unsafe_audio_stem(tmp_path: Path) -> None:
    audio_path = tmp_path / "Unsafe ID.mp3"
    audio_path.write_bytes(b"audio")

    with pytest.raises(path_policy.VideoIdError, match="ARTIFACT_ID_INVALID"):
        runner.chunk_manifest_path(audio_path, tmp_path / "chunks")


def test_reusable_chunk_manifest_rejects_external_recorded_path(tmp_path: Path) -> None:
    audio_path = tmp_path / "source.mp3"
    audio_path.write_bytes(b"audio")
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    outside_chunk = tmp_path / "outside.chunk-000.mp3"
    outside_chunk.write_bytes(b"external")
    source_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    creator_pipeline.write_json(
        runner.chunk_manifest_path(audio_path, chunks_dir),
        {
            "schema_version": 1,
            "status": "complete",
            "source_audio_sha256": source_hash,
            "source_duration_ms": 240000,
            "segment_seconds": 120,
            "chunks": [
                {
                    "chunk_index": 0,
                    "path": str(outside_chunk),
                    "start_ms": 0,
                    "end_ms": 120000,
                    "duration_ms": 120000,
                },
                {
                    "chunk_index": 1,
                    "path": str(outside_chunk),
                    "start_ms": 120000,
                    "end_ms": 240000,
                    "duration_ms": 120000,
                },
            ],
        },
    )

    assert runner.reusable_chunk_paths(audio_path, chunks_dir, source_hash, 240000, 120) == []
