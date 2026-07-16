"""OSS uploads must be isolated, auditable, short-lived, and secret-free."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import provider_adapters
import run_creator_skill_build as runner
from pipeline_models import StepResult


FIXED_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
ACCESS_ID = "synthetic-access-id"
ACCESS_SECRET = "synthetic-access-secret"
SIGNED_SECRET = "synthetic-signed-secret"


def lifecycle() -> Any:
    return importlib.import_module("oss_lifecycle")


@pytest.fixture
def fake_oss(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    class FakeResult:
        def __init__(self, status: int) -> None:
            self.status = status

    class FakeAuth:
        def __init__(self, access_id: str, access_secret: str) -> None:
            self.access_id = access_id
            self.access_secret = access_secret

    class FakeBucket:
        put_calls: list[tuple[str, str]] = []
        sign_calls: list[tuple[str, str, int]] = []
        delete_calls: list[str] = []
        delete_error: Exception | None = None
        put_statuses: list[int] = []
        delete_statuses: list[int] = []
        put_timeouts: list[float] = []
        delete_timeouts: list[float] = []

        def __init__(self, auth: FakeAuth, endpoint: str, bucket_name: str) -> None:
            assert auth.access_id == ACCESS_ID
            assert auth.access_secret == ACCESS_SECRET
            assert endpoint == "https://oss.example.invalid"
            assert bucket_name == "synthetic-bucket"

        def put_object_from_file(self, object_key: str, file_path: str) -> FakeResult:
            self.put_calls.append((object_key, file_path))
            self.put_timeouts.append(self.timeout)
            status = self.put_statuses.pop(0) if self.put_statuses else 200
            return FakeResult(status)

        def sign_url(self, method: str, object_key: str, expires: int) -> str:
            self.sign_calls.append((method, object_key, expires))
            return (
                f"https://synthetic-bucket.oss.example.invalid/{object_key}"
                f"?OSSAccessKeyId={ACCESS_ID}&Signature={SIGNED_SECRET}"
            )

        def delete_object(self, object_key: str) -> FakeResult:
            self.delete_calls.append(object_key)
            self.delete_timeouts.append(self.timeout)
            if self.delete_error is not None:
                raise self.delete_error
            status = self.delete_statuses.pop(0) if self.delete_statuses else 204
            return FakeResult(status)

    monkeypatch.setitem(
        sys.modules,
        "oss2",
        types.SimpleNamespace(Auth=FakeAuth, Bucket=FakeBucket),
    )
    monkeypatch.setattr(
        provider_adapters.network_policy,
        "validate_url",
        lambda *_args, **_kwargs: None,
    )
    return FakeBucket


@pytest.fixture
def oss_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    values = {
        "ALI_OSS_ENDPOINT": "https://oss.example.invalid",
        "ALI_OSS_BUCKET": "synthetic-bucket",
        "ALI_OSS_ACCESS_KEY_ID": ACCESS_ID,
        "ALI_OSS_ACCESS_KEY_SECRET": ACCESS_SECRET,
        "ALI_OSS_PREFIX": "creator-agent-studio/audio",
        "ALI_OSS_SIGNED_URL_EXPIRES": "900",
        "ALI_OSS_LIFECYCLE_POLICY": "delete_after_asr",
        "ALI_OSS_FAILURE_RETENTION_SECONDS": "86400",
        "ALI_ASR_PROVIDER": "aliyun",
        "ALI_ASR_MODEL": "synthetic-asr",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def create_audio(run_dir: Path, *, name: str = "video-a.mp3", body: bytes = b"same-audio") -> Path:
    audio = run_dir / "media" / "audio" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(body)
    return audio


def read_manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "logs" / "oss_lifecycle.json").read_text(encoding="utf-8"))


def upload_for_run(run_dir: Path, audio: Path, *, video_id: str = "video-a") -> Any:
    module = lifecycle()
    context = module.OSSObjectContext.from_run_dir(
        run_dir,
        video_id=video_id,
        chunk_id="full",
    )
    return provider_adapters.upload_file_to_oss(audio, context=context)


def test_same_audio_name_in_two_runs_uses_distinct_content_addressed_keys(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    run_a = tmp_path / "project-a" / "run-a"
    run_b = tmp_path / "project-a" / "run-b"
    upload_a = upload_for_run(run_a, create_audio(run_a))
    upload_b = upload_for_run(run_b, create_audio(run_b))

    assert upload_a.object_key != upload_b.object_key
    assert "/project-a/run-a/video-a/full/" in upload_a.object_key
    assert "/project-a/run-b/video-a/full/" in upload_b.object_key
    assert upload_a.source_sha256 in upload_a.object_key
    assert upload_b.source_sha256 in upload_b.object_key
    assert upload_a.signed_url.endswith(f"Signature={SIGNED_SECRET}")
    assert [call[0] for call in fake_oss.put_calls] == [upload_a.object_key, upload_b.object_key]
    assert [call[1] for call in fake_oss.sign_calls] == [upload_a.object_key, upload_b.object_key]


def test_oss_upload_and_delete_retry_transient_server_errors(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    run_dir = tmp_path / "project-a" / "run-a"
    audio = create_audio(run_dir)
    context = lifecycle().OSSObjectContext.from_run_dir(
        run_dir,
        video_id="video-a",
        chunk_id="full",
    )
    immediate_retry = provider_adapters.retry_policy.RetryPolicy(
        max_attempts=3,
        request_timeout_seconds=5,
        deadline_seconds=20,
        base_delay_seconds=0,
        max_delay_seconds=0,
        jitter_ratio=0,
    )
    fake_oss.put_statuses = [503, 200]

    upload = provider_adapters.upload_file_to_oss(
        audio,
        context=context,
        retry=immediate_retry,
    )

    assert len(fake_oss.put_calls) == 2
    assert fake_oss.put_timeouts == [5.0, 5.0]
    fake_oss.delete_calls.clear()
    fake_oss.delete_statuses = [503, 204]
    provider_adapters.delete_oss_object(upload.object_key, retry=immediate_retry)
    assert fake_oss.delete_calls == [upload.object_key, upload.object_key]
    assert fake_oss.delete_timeouts[-2:] == [5.0, 5.0]


def test_upload_manifest_records_managed_object_but_never_signed_url(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    run_dir = tmp_path / "project-a" / "run-a"
    upload = upload_for_run(run_dir, create_audio(run_dir))
    lifecycle().register_upload(run_dir, upload, now=FIXED_NOW)

    manifest_text = (run_dir / "logs" / "oss_lifecycle.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)

    assert manifest["objects"][0]["object_key"] == upload.object_key
    assert manifest["objects"][0]["cleanup"]["status"] == "pending"
    assert manifest["objects"][0]["source_sha256"] == upload.source_sha256
    for forbidden in ("signed_url", "OSSAccessKeyId", ACCESS_ID, ACCESS_SECRET, SIGNED_SECRET):
        assert forbidden not in manifest_text


def test_default_success_deletes_object_and_records_terminal_state(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    module = lifecycle()
    run_dir = tmp_path / "project-a" / "run-a"
    upload = upload_for_run(run_dir, create_audio(run_dir))
    module.register_upload(run_dir, upload, now=FIXED_NOW)

    outcome = module.finalize_upload(
        run_dir,
        upload,
        asr_outcome="succeeded",
        delete_callback=provider_adapters.delete_oss_object,
        now=FIXED_NOW,
    )

    assert outcome.cleanup_status == "deleted"
    assert fake_oss.delete_calls == [upload.object_key]
    entry = read_manifest(run_dir)["objects"][0]
    assert entry["asr_outcome"] == "succeeded"
    assert entry["cleanup"]["status"] == "deleted"
    assert entry["cleanup"]["deleted_at"] == FIXED_NOW.isoformat()


def test_delete_refuses_object_outside_managed_prefix(
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="unmanaged"):
        provider_adapters.delete_oss_object("another-application/audio.mp3")

    assert fake_oss.delete_calls == []


def test_failed_asr_retains_object_until_bounded_expiry(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    module = lifecycle()
    run_dir = tmp_path / "project-a" / "run-a"
    upload = upload_for_run(run_dir, create_audio(run_dir))
    module.register_upload(run_dir, upload, now=FIXED_NOW)

    outcome = module.finalize_upload(
        run_dir,
        upload,
        asr_outcome="failed",
        delete_callback=provider_adapters.delete_oss_object,
        now=FIXED_NOW,
    )

    assert outcome.cleanup_status == "pending_expiry"
    assert outcome.retain_until == "2026-07-16T12:00:00+00:00"
    assert fake_oss.delete_calls == []
    cleanup = read_manifest(run_dir)["objects"][0]["cleanup"]
    assert cleanup["status"] == "pending_expiry"
    assert cleanup["retain_until"] == outcome.retain_until


def test_expired_failed_upload_is_deleted_by_lifecycle_sweep(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    module = lifecycle()
    run_dir = tmp_path / "project-a" / "run-a"
    upload = upload_for_run(run_dir, create_audio(run_dir))
    module.register_upload(run_dir, upload, now=FIXED_NOW)
    module.finalize_upload(
        run_dir,
        upload,
        asr_outcome="failed",
        delete_callback=provider_adapters.delete_oss_object,
        now=FIXED_NOW,
    )

    early = module.cleanup_expired_uploads(
        run_dir,
        delete_callback=provider_adapters.delete_oss_object,
        now=datetime(2026, 7, 16, 11, 59, tzinfo=timezone.utc),
    )
    expired = module.cleanup_expired_uploads(
        run_dir,
        delete_callback=provider_adapters.delete_oss_object,
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert early == ()
    assert [outcome.cleanup_status for outcome in expired] == ["deleted"]
    assert fake_oss.delete_calls == [upload.object_key]
    cleanup = read_manifest(run_dir)["objects"][0]["cleanup"]
    assert cleanup["status"] == "deleted"
    assert cleanup["reason"] == "retention_elapsed"


def test_explicit_retain_policy_never_deletes_successful_upload(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALI_OSS_LIFECYCLE_POLICY", "retain")
    module = lifecycle()
    run_dir = tmp_path / "project-a" / "run-a"
    upload = upload_for_run(run_dir, create_audio(run_dir))
    module.register_upload(run_dir, upload, now=FIXED_NOW)

    outcome = module.finalize_upload(
        run_dir,
        upload,
        asr_outcome="succeeded",
        delete_callback=provider_adapters.delete_oss_object,
        now=FIXED_NOW,
    )

    assert outcome.cleanup_status == "retained"
    assert fake_oss.delete_calls == []
    assert read_manifest(run_dir)["objects"][0]["cleanup"]["reason"] == "explicit_retain"


def test_delete_failure_is_scrubbed_recorded_and_propagated_as_step_issue(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    module = lifecycle()
    run_dir = tmp_path / "project-a" / "run-a"
    upload = upload_for_run(run_dir, create_audio(run_dir))
    module.register_upload(run_dir, upload, now=FIXED_NOW)
    fake_oss.delete_error = RuntimeError(
        f"Authorization Bearer {ACCESS_SECRET} "
        f"https://oss.example.invalid/object?Signature={SIGNED_SECRET}"
    )

    outcome = module.finalize_upload(
        run_dir,
        upload,
        asr_outcome="succeeded",
        delete_callback=provider_adapters.delete_oss_object,
        now=FIXED_NOW,
    )
    step = StepResult.from_rows(
        "transcribe_with_aliyun_asr",
        [
            {
                "status": "transcribed",
                "cleanup_issue": outcome.cleanup_issue,
            }
        ],
    )
    manifest_text = (run_dir / "logs" / "oss_lifecycle.json").read_text(encoding="utf-8")

    assert outcome.cleanup_status == "cleanup_failed"
    assert outcome.cleanup_issue
    assert step.status == "succeeded"
    assert step.issues == (outcome.cleanup_issue,)
    assert read_manifest(run_dir)["issues"][0]["code"] == "OSS_CLEANUP_FAILED"
    for forbidden in (ACCESS_ID, ACCESS_SECRET, SIGNED_SECRET, "Authorization Bearer"):
        assert forbidden not in outcome.cleanup_issue
        assert forbidden not in manifest_text


def test_cleanup_failure_remains_retryable_by_lifecycle_sweep(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
) -> None:
    module = lifecycle()
    run_dir = tmp_path / "project-a" / "run-a"
    upload = upload_for_run(run_dir, create_audio(run_dir))
    module.register_upload(run_dir, upload, now=FIXED_NOW)
    fake_oss.delete_error = RuntimeError("synthetic delete outage")
    module.finalize_upload(
        run_dir,
        upload,
        asr_outcome="succeeded",
        delete_callback=provider_adapters.delete_oss_object,
        now=FIXED_NOW,
    )

    fake_oss.delete_error = None
    outcomes = module.cleanup_expired_uploads(
        run_dir,
        delete_callback=provider_adapters.delete_oss_object,
        now=FIXED_NOW,
    )

    assert [outcome.cleanup_status for outcome in outcomes] == ["deleted"]
    assert fake_oss.delete_calls == [upload.object_key, upload.object_key]
    cleanup = read_manifest(run_dir)["objects"][0]["cleanup"]
    assert cleanup["status"] == "deleted"
    assert cleanup["reason"] == "cleanup_retry_succeeded"


def test_runner_success_uploads_signs_deletes_and_never_persists_signed_url(
    tmp_path: Path,
    fixture_root: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "project-a" / "run-a"
    audio = create_audio(run_dir)
    raw_dir = run_dir / "transcripts" / "raw_json"
    transcript_dir = run_dir / "transcripts"
    raw_dir.mkdir(parents=True)
    raw_response = (fixture_root / "asr" / "audio_transcriptions.json").read_text(encoding="utf-8")

    def fake_asr(args: argparse.Namespace) -> None:
        Path(args.result_json).write_text(raw_response, encoding="utf-8")

    monkeypatch.setattr(provider_adapters, "transcribe_aliyun_file_url", fake_asr)

    row = runner.transcribe_one_audio(audio, raw_dir, transcript_dir, strict_asr=True)

    assert row["status"] == "transcribed"
    assert row["oss_cleanup_status"] == "deleted"
    assert fake_oss.put_calls and fake_oss.sign_calls and fake_oss.delete_calls
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    for forbidden in ("signed_url", "OSSAccessKeyId", ACCESS_ID, ACCESS_SECRET, SIGNED_SECRET):
        assert forbidden not in persisted


def test_runner_provider_failure_marks_pending_expiry_before_reraising(
    tmp_path: Path,
    fake_oss: type[Any],
    oss_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "project-a" / "run-a"
    audio = create_audio(run_dir)
    raw_dir = run_dir / "transcripts" / "raw_json"
    transcript_dir = run_dir / "transcripts"
    raw_dir.mkdir(parents=True)

    def fail_asr(_args: argparse.Namespace) -> None:
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(provider_adapters, "transcribe_aliyun_file_url", fail_asr)

    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        runner.transcribe_one_audio(audio, raw_dir, transcript_dir, strict_asr=True)

    assert fake_oss.delete_calls == []
    entry = read_manifest(run_dir)["objects"][0]
    assert entry["asr_outcome"] == "failed"
    assert entry["cleanup"]["status"] == "pending_expiry"
    assert entry["cleanup"]["retain_until"]
