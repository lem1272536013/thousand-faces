"""High-cost pipeline steps only reuse artifacts with matching provenance."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

import artifacts
import creator_pipeline
import run_creator_skill_build as runner


class FakeDownloadResponse(io.BytesIO):
    status = 200

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(payload)),
            "Authorization": "Bearer response-secret",
            "Set-Cookie": "session=response-secret",
        }

    def geturl(self) -> str:
        return "https://cdn.example.invalid/final.mp4?Signature=redirect-secret"


def test_compatible_asr_cache_invalidates_on_model_segment_and_audio_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "audio" / "source.mp3"
    audio_path.parent.mkdir()
    audio_path.write_bytes(b"source audio version one")
    raw_dir = tmp_path / "transcripts" / "raw_json"
    raw_dir.mkdir(parents=True)
    transcript_path = tmp_path / "transcripts" / "source.txt"
    calls: list[Path] = []
    monkeypatch.setenv("ALI_ASR_PROVIDER", "openai-compatible")
    monkeypatch.setenv("ALI_ASR_ENDPOINT", "https://asr.example.invalid/v1?token=do-not-persist")
    monkeypatch.setenv("ALI_ASR_MODEL", "model-a")
    monkeypatch.setenv("ALI_ASR_LANGUAGE", "zh-CN")
    monkeypatch.setenv("ASR_SEGMENT_SECONDS", "120")
    monkeypatch.setattr(runner, "media_duration_seconds", lambda _: 30.0)

    def fake_provider(args: object) -> None:
        calls.append(Path(str(getattr(args, "input"))))
        creator_pipeline.write_json(Path(str(getattr(args, "output"))), {"text": "verified transcript"})

    monkeypatch.setattr(runner.provider_adapters, "transcribe_compatible_audio_file", fake_provider)

    first = runner.transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)
    second = runner.transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)
    monkeypatch.setenv("ALI_ASR_MODEL", "model-b")
    third = runner.transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)
    monkeypatch.setenv("ASR_SEGMENT_SECONDS", "60")
    fourth = runner.transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)
    audio_path.write_bytes(b"source audio version two")
    fifth = runner.transcribe_compatible_audio_path(audio_path, raw_dir, transcript_path)

    assert first["status"] == "transcribed"
    assert second["status"] == "skipped"
    assert third["status"] == "transcribed"
    assert fourth["status"] == "transcribed"
    assert fifth["status"] == "transcribed"
    assert len(calls) == 4
    manifest_text = artifacts.artifact_manifest_path(raw_dir / "source.result.json").read_text(encoding="utf-8")
    assert "do-not-persist" not in manifest_text


def test_summary_cache_tracks_all_transcript_hashes(tmp_path: Path) -> None:
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    transcript = transcripts_dir / "video-a.txt"
    transcript.write_text("第一版内容。", encoding="utf-8")
    output_dir = tmp_path / "research"

    summary_path = creator_pipeline.summarize_transcripts(transcripts_dir, output_dir, overwrite=False)
    first_manifest = json.loads(
        artifacts.artifact_manifest_path(summary_path).read_text(encoding="utf-8")
    )
    creator_pipeline.summarize_transcripts(transcripts_dir, output_dir, overwrite=False)
    unchanged_manifest = json.loads(
        artifacts.artifact_manifest_path(summary_path).read_text(encoding="utf-8")
    )
    transcript.write_text("第二版内容，发生了变化。", encoding="utf-8")
    creator_pipeline.summarize_transcripts(transcripts_dir, output_dir, overwrite=False)
    changed_manifest = json.loads(
        artifacts.artifact_manifest_path(summary_path).read_text(encoding="utf-8")
    )

    assert unchanged_manifest["fingerprint"] == first_manifest["fingerprint"]
    assert changed_manifest["fingerprint"] != first_manifest["fingerprint"]
    assert summary_path.read_text(encoding="utf-8").find("video-a") >= 0


def test_download_replaces_legacy_cache_then_reuses_verified_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    artifact = output_dir / "video-a.mp4"
    artifact.write_bytes(b"legacy bytes")
    calls = 0

    def fake_urlopen(*_: object, **__: object) -> FakeDownloadResponse:
        nonlocal calls
        calls += 1
        return FakeDownloadResponse(b"verified video")

    monkeypatch.setattr(creator_pipeline.network_policy, "open_url", fake_urlopen)
    monkeypatch.setattr(
        creator_pipeline.media_validation,
        "validate_media_file",
        lambda path, **_kwargs: {
            "format_name": "mov,mp4",
            "duration_ms": 1000,
            "size_bytes": path.stat().st_size,
            "video_stream_count": 1,
            "audio_stream_count": 1,
            "video_codec": "h264",
            "width": 1080,
            "height": 1920,
        },
    )
    item = {
        "platform_video_id": "video-a",
        "download_url": "https://cdn.example.invalid/video.mp4?token=source-secret",
    }

    first = creator_pipeline.download_one(item, output_dir, timeout=10, retries=1)
    second = creator_pipeline.download_one(item, output_dir, timeout=10, retries=1)

    assert first["status"] == "downloaded"
    assert first["cache_status"] == "legacy_unverified"
    assert second["status"] == "skipped"
    assert second["cache_status"] == "verified"
    assert calls == 1
    manifest_text = artifacts.artifact_manifest_path(artifact).read_text(encoding="utf-8")
    assert "source-secret" not in manifest_text
    assert "redirect-secret" not in manifest_text
    assert "response-secret" not in manifest_text
    assert "Authorization" not in manifest_text
    assert "Set-Cookie" not in manifest_text


def test_audio_cache_invalidates_when_source_video_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    video_dir = run_dir / "media" / "videos"
    audio_dir = run_dir / "media" / "audio"
    video_dir.mkdir(parents=True)
    video_path = video_dir / "video-a.mp4"
    video_path.write_bytes(b"video version one")
    audio_dir.mkdir(parents=True)
    legacy_audio = audio_dir / "video-a.wav"
    legacy_audio.write_bytes(b"legacy audio")
    calls: list[list[str]] = []
    monkeypatch.setenv("ALI_ASR_AUDIO_FORMAT", "wav")
    monkeypatch.setenv("ASR_SAMPLE_RATE", "16000")
    monkeypatch.setattr(creator_pipeline, "ffmpeg_version", lambda _: "ffmpeg version test")

    def fake_ffmpeg(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        Path(command[-1]).write_bytes(f"audio-{len(calls)}".encode())
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(creator_pipeline.subprocess, "run", fake_ffmpeg)

    creator_pipeline.extract_audio(video_dir, audio_dir)
    creator_pipeline.extract_audio(video_dir, audio_dir)
    video_path.write_bytes(b"video version two")
    creator_pipeline.extract_audio(video_dir, audio_dir)

    assert len(calls) == 2
    manifest = json.loads(artifacts.artifact_manifest_path(legacy_audio).read_text(encoding="utf-8"))
    assert manifest["artifact_type"] == "extracted_audio"
    assert manifest["config"]["ffmpeg_version"] == "ffmpeg version test"
    assert manifest["inputs"][0]["sha256"] == artifacts.file_sha256(video_path)
