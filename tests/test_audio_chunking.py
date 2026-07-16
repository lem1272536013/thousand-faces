"""Audio chunk creation must be complete, measurable, and safely reusable."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import run_creator_skill_build as runner


def test_split_audio_writes_complete_manifest_with_actual_boundaries_and_source_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "source.mp3"
    audio_path.write_bytes(b"synthetic source audio")
    chunks_dir = tmp_path / "chunks"
    durations = {
        "source.mp3": 245.0,
        "source.chunk-000.mp3": 120.0,
        "source.chunk-001.mp3": 120.0,
        "source.chunk-002.mp3": 5.0,
    }
    monkeypatch.setattr(runner, "media_duration_seconds", lambda path: durations[path.name])

    def successful_ffmpeg(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        chunks_dir.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            (chunks_dir / f"source.chunk-{index:03d}.mp3").write_bytes(f"chunk-{index}".encode())
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", successful_ffmpeg)

    chunks = runner.split_audio_for_asr(audio_path, chunks_dir)

    assert [path.name for path in chunks] == [
        "source.chunk-000.mp3",
        "source.chunk-001.mp3",
        "source.chunk-002.mp3",
    ]
    manifest_path = runner.chunk_manifest_path(audio_path, chunks_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["source_audio_sha256"] == hashlib.sha256(audio_path.read_bytes()).hexdigest()
    assert manifest["source_duration_ms"] == 245000
    assert manifest["segment_seconds"] == 120
    assert [
        (chunk["start_ms"], chunk["end_ms"], chunk["duration_ms"])
        for chunk in manifest["chunks"]
    ] == [
        (0, 120000, 120000),
        (120000, 240000, 120000),
        (240000, 245000, 5000),
    ]


def test_split_failure_records_failed_manifest_and_never_falls_back_to_full_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "source.mp3"
    audio_path.write_bytes(b"synthetic source audio")
    chunks_dir = tmp_path / "chunks"
    monkeypatch.setattr(runner, "media_duration_seconds", lambda _: 245.0)

    def failed_ffmpeg(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        chunks_dir.mkdir(parents=True, exist_ok=True)
        (chunks_dir / "source.chunk-000.mp3").write_bytes(b"partial")
        return subprocess.CompletedProcess(command, 1, "", "simulated split failure")

    monkeypatch.setattr(runner.subprocess, "run", failed_ffmpeg)

    with pytest.raises(SystemExit, match="failed to split audio for ASR"):
        runner.split_audio_for_asr(audio_path, chunks_dir)

    manifest = json.loads(runner.chunk_manifest_path(audio_path, chunks_dir).read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["chunks"] == []
    assert not list(chunks_dir.glob("source.chunk-*.mp3"))


def test_incomplete_cached_chunks_are_not_reused_as_a_complete_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "source.mp3"
    audio_path.write_bytes(b"synthetic source audio")
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    stale_chunk = chunks_dir / "source.chunk-000.mp3"
    stale_chunk.write_bytes(b"stale partial chunk")
    monkeypatch.setattr(runner, "media_duration_seconds", lambda _: 245.0)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda command, **_: subprocess.CompletedProcess(command, 1, "", "retry failed"),
    )

    with pytest.raises(SystemExit, match="failed to split audio for ASR"):
        runner.split_audio_for_asr(audio_path, chunks_dir)

    assert not stale_chunk.exists()
    manifest = json.loads(runner.chunk_manifest_path(audio_path, chunks_dir).read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"


def test_unknown_audio_duration_fails_before_attempting_full_file_asr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "source.mp3"
    audio_path.write_bytes(b"synthetic source audio")
    monkeypatch.setattr(runner, "media_duration_seconds", lambda _: 0.0)

    with pytest.raises(SystemExit, match="cannot determine audio duration"):
        runner.split_audio_for_asr(audio_path, tmp_path / "chunks")


def test_chunked_transcription_writes_global_timeline_and_separate_source_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "audio" / "source.mp3"
    audio_path.parent.mkdir()
    audio_path.write_bytes(b"synthetic source audio")
    raw_dir = tmp_path / "transcripts" / "raw_json"
    chunks_dir = raw_dir / "chunks"
    chunks_dir.mkdir(parents=True)
    transcript_path = tmp_path / "transcripts" / "source.txt"
    chunks = [chunks_dir / "source.chunk-000.mp3", chunks_dir / "source.chunk-001.mp3"]
    for index, path in enumerate(chunks):
        path.write_bytes(f"chunk-{index}".encode())
    source_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    runner.creator_pipeline.write_json(
        runner.chunk_manifest_path(audio_path, chunks_dir),
        {
            "schema_version": 1,
            "status": "complete",
            "source_audio": str(audio_path),
            "source_audio_sha256": source_hash,
            "source_duration_ms": 240000,
            "segment_seconds": 120,
            "chunks": [
                {
                    "chunk_index": 0,
                    "path": str(chunks[0]),
                    "start_ms": 0,
                    "end_ms": 120000,
                    "duration_ms": 120000,
                },
                {
                    "chunk_index": 1,
                    "path": str(chunks[1]),
                    "start_ms": 120000,
                    "end_ms": 240000,
                    "duration_ms": 120000,
                },
            ],
        },
    )
    monkeypatch.setattr(runner, "split_audio_for_asr", lambda *_: chunks)

    def fake_provider(args: object) -> None:
        input_path = Path(str(getattr(args, "input")))
        if input_path.name.endswith("000.mp3"):
            payload = {"segments": [{"start": 119.0, "end": 120.0, "text": "第一片尾部。"}]}
        else:
            payload = {"segments": [{"start": 5.0, "end": 6.0, "text": "第二片五秒处。"}]}
        runner.creator_pipeline.write_json(Path(str(getattr(args, "output"))), payload)

    monkeypatch.setattr(runner.provider_adapters, "transcribe_compatible_audio_file", fake_provider)

    result = runner.transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)

    assert transcript_path.read_text(encoding="utf-8").splitlines() == [
        "[00:01:59] 第一片尾部。",
        "[00:02:05] 第二片五秒处。",
    ]
    segment_map_path = transcript_path.with_suffix(".segments.json")
    source_map = json.loads(segment_map_path.read_text(encoding="utf-8"))
    assert source_map["source_audio_sha256"] == source_hash
    assert source_map["input_segment_count"] == 2
    assert source_map["output_segment_count"] == 2
    assert source_map["timestamps_monotonic"] is True
    assert [item["chunk_index"] for item in source_map["segments"]] == [0, 1]
    assert all("text" not in item for item in source_map["segments"])
    assert result["segment_map"] == str(segment_map_path)
    assert result["chunks_manifest"] == str(runner.chunk_manifest_path(audio_path, chunks_dir))
