"""Media stages must improve throughput without unbounded resource use."""

from __future__ import annotations

import argparse
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

import creator_pipeline
import input_validation
import provider_adapters
import run_creator_skill_build as runner


class ActiveProbe:
    """Record observable peak work without inspecting executor internals."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    @contextmanager
    def task(self) -> Iterator[None]:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.04)
            yield
        finally:
            with self._lock:
                self.active -= 1


def test_downloads_respect_their_own_worker_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_path = tmp_path / "selected.json"
    creator_pipeline.write_json(
        selected_path,
        {
            "items": [
                {
                    "platform_video_id": f"download-{index:03d}",
                    "download_url": f"https://media.example.invalid/{index}.mp4",
                }
                for index in range(8)
            ]
        },
    )
    probe = ActiveProbe()

    def fake_download(item: dict[str, Any], *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        with probe.task():
            return {
                "video_id": item["artifact_id"],
                "artifact_id": item["artifact_id"],
                "platform_video_id": item["platform_video_id"],
                "status": "downloaded",
            }

    monkeypatch.setenv("DOWNLOAD_CONCURRENCY", "3")
    monkeypatch.setattr(creator_pipeline, "download_one", fake_download)

    status_path = creator_pipeline.download_videos(
        selected_path,
        tmp_path / "videos",
        tmp_path / "logs",
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert probe.peak == 3
    assert payload["count"] == 8


def test_ffmpeg_uses_a_conservative_independent_worker_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    video_dir = run_dir / "media" / "videos"
    audio_dir = run_dir / "media" / "audio"
    video_dir.mkdir(parents=True)
    (run_dir / "logs").mkdir()
    for index in range(6):
        (video_dir / f"ffmpeg-{index:03d}.mp4").write_bytes(b"synthetic-video")
    probe = ActiveProbe()

    def fake_ffmpeg(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        with probe.task():
            Path(command[-1]).write_bytes(b"synthetic-audio")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("FFMPEG_CONCURRENCY", "2")
    monkeypatch.setattr(creator_pipeline, "ffmpeg_version", lambda _binary: "ffmpeg-test")
    monkeypatch.setattr(creator_pipeline.subprocess, "run", fake_ffmpeg)

    status_path = creator_pipeline.extract_audio(video_dir, audio_dir)

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert probe.peak == 2
    assert payload["count"] == 6
    assert {row["status"] for row in payload["results"]} == {"extracted"}


def test_asr_uses_its_own_worker_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    audio_dir = run_dir / "media" / "audio"
    audio_dir.mkdir(parents=True)
    (run_dir / "logs").mkdir()
    for index in range(7):
        (audio_dir / f"asr-{index:03d}.mp3").write_bytes(b"synthetic-audio")
    probe = ActiveProbe()

    def fake_transcribe(
        audio_path: Path,
        _raw_dir: Path,
        transcript_dir: Path,
        _strict_asr: bool,
    ) -> dict[str, Any]:
        with probe.task():
            transcript = transcript_dir / f"{audio_path.stem}.txt"
            transcript.write_text("synthetic transcript", encoding="utf-8")
            return {
                "audio": str(audio_path),
                "status": "transcribed",
                "transcript": str(transcript),
            }

    monkeypatch.setenv("ALI_ASR_CONCURRENCY", "4")
    monkeypatch.setattr(runner, "transcribe_one_audio", fake_transcribe)

    rows = runner.transcribe_audio_files(run_dir, None, False)

    assert probe.peak == 4
    assert len(rows) == 7
    assert {row["status"] for row in rows} == {"transcribed"}


def test_oversized_compatible_chat_chunk_is_rejected_before_base64(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "oversized.mp3"
    audio_path.write_bytes(b"12345")
    monkeypatch.setenv("ALI_ASR_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("ALI_ASR_ENDPOINT", "https://provider.example.invalid/v1")
    monkeypatch.setenv("ALI_ASR_MAX_BASE64_AUDIO_BYTES", "4")

    def forbidden_encode(_value: bytes) -> bytes:
        raise AssertionError("Base64 encoding must not run for an oversized chunk")

    monkeypatch.setattr(provider_adapters.base64, "b64encode", forbidden_encode)

    with pytest.raises(SystemExit, match="ASR_AUDIO_TOO_LARGE"):
        provider_adapters.transcribe_compatible_audio_chat(
            argparse.Namespace(input=str(audio_path), output=str(tmp_path / "output.json"))
        )


def test_asr_rejects_an_unsafe_combined_base64_memory_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    audio_dir = run_dir / "media" / "audio"
    audio_dir.mkdir(parents=True)
    (run_dir / "logs").mkdir()
    (audio_dir / "budget.mp3").write_bytes(b"synthetic-audio")
    monkeypatch.setenv("ALI_ASR_PROVIDER", "openai-compatible")
    monkeypatch.setenv("ALI_ASR_CONCURRENCY", "16")
    monkeypatch.setenv("ALI_ASR_MAX_BASE64_AUDIO_BYTES", str(32 * 1024 * 1024))

    def forbidden_transcribe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("ASR work must not start above the in-flight memory budget")

    monkeypatch.setattr(runner, "transcribe_one_audio", forbidden_transcribe)

    with pytest.raises(input_validation.InputValidationError, match="in-flight"):
        runner.transcribe_audio_files(run_dir, None, False)


def test_file_url_asr_is_not_subject_to_the_compatible_base64_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    audio_dir = run_dir / "media" / "audio"
    audio_dir.mkdir(parents=True)
    (run_dir / "logs").mkdir()
    audio_path = audio_dir / "file-url.mp3"
    audio_path.write_bytes(b"synthetic-audio")
    monkeypatch.setenv("ALI_ASR_PROVIDER", "aliyun")
    monkeypatch.setenv("ALI_ASR_CONCURRENCY", "16")
    monkeypatch.setenv("ALI_ASR_MAX_BASE64_AUDIO_BYTES", str(32 * 1024 * 1024))

    monkeypatch.setattr(
        runner,
        "transcribe_one_audio",
        lambda *_args, **_kwargs: {
            "audio": str(audio_path),
            "status": "transcribed",
        },
    )

    rows = runner.transcribe_audio_files(run_dir, None, False)

    assert len(rows) == 1
    assert rows[0]["status"] == "transcribed"
