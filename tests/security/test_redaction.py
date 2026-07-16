"""Secrets and sensitive diagnostics must be irrecoverable in persisted output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

import build_creator_skill
import creator_pipeline
import provider_adapters
import run_creator_skill_build as runner
import settings
from pipeline_models import PipelineResult, StepResult, write_pipeline_result


SECRET = "ABCD-provider-token-WXYZ"
SIGNED_SECRET = "signed-query-secret"
USERINFO_SECRET = "userinfo-password"


def run_args(run_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        source_url="https://share.example.invalid/profile",
        project_name="redaction-contract",
        sample_count=1,
        metadata_fetch_limit=None,
        run_root=str(run_root),
    )


def assert_secrets_absent(text: str) -> None:
    for fragment in (
        SECRET,
        "ABCD",
        "WXYZ",
        SIGNED_SECRET,
        USERINFO_SECRET,
        "Bearer ABCD",
        "C:\\Users\\Alice\\private\\.env",
        "/home/alice/.config/provider/key.json",
    ):
        assert fragment not in text


def test_config_snapshot_omits_secret_fields_and_sanitizes_nonsecret_values(tmp_path: Path) -> None:
    config = {
        **build_creator_skill.DEFAULTS,
        "TIKHUB_API_KEY": SECRET,
        "ALI_OSS_ACCESS_KEY_SECRET": "EFGH-oss-secret-IJKL",
        "ALI_ASR_ENDPOINT": f"https://api.example.invalid/v1?mode=safe&token={SIGNED_SECRET}",
        "TIKHUB_EXTRA_QUERY": f"cursor=2&signature={SIGNED_SECRET}",
    }

    run_dir = build_creator_skill.create_run(run_args(tmp_path), config)
    snapshot_path = run_dir / "config.snapshot.json"
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    snapshot = json.loads(snapshot_text)

    assert "TIKHUB_API_KEY" not in snapshot
    assert "ALI_OSS_ACCESS_KEY_SECRET" not in snapshot
    assert snapshot["settings_schema_version"] == settings.SETTINGS_SCHEMA_VERSION
    assert snapshot["ALI_ASR_ENDPOINT"] == "https://api.example.invalid/v1?mode=safe"
    assert snapshot["TIKHUB_EXTRA_QUERY"] == "cursor=2&signature=<redacted>"
    assert_secrets_absent(snapshot_text)


def test_url_redaction_removes_userinfo_sensitive_query_and_fragment() -> None:
    import redaction

    sanitized = redaction.redact_url(
        f"https://client:{USERINFO_SECRET}@cdn.example.invalid/video.mp4"
        f"?page=2&token={SECRET}&X-Amz-Signature={SIGNED_SECRET}#private-fragment"
    )

    assert sanitized == "https://cdn.example.invalid/video.mp4?page=2"
    assert_secrets_absent(sanitized)
    assert "private-fragment" not in sanitized


def test_url_redaction_removes_common_signing_aliases() -> None:
    import redaction

    sanitized = redaction.redact_url(
        "https://cdn.example.invalid/video.mp4"
        "?part=1&auth=auth-secret&sig=sig-secret&policy=policy-secret"
        "&X-Amz-Credential=credential-secret"
    )

    assert sanitized == "https://cdn.example.invalid/video.mp4?part=1"


def test_text_scrubber_cleans_headers_tokens_signed_urls_and_local_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redaction

    monkeypatch.setenv("ALI_ASR_API_KEY", SECRET)
    diagnostic = (
        f"Authorization: Bearer {SECRET}; token={SECRET}; "
        f"url=https://client:{USERINFO_SECRET}@cdn.example.invalid/a.mp4"
        f"?Signature={SIGNED_SECRET}&page=2; "
        "windows=C:\\Users\\Alice\\private\\.env; "
        "posix=/home/alice/.config/provider/key.json"
    )

    scrubbed = redaction.scrub_text(diagnostic)

    assert_secrets_absent(scrubbed)
    assert "Authorization: <redacted>" in scrubbed
    assert "token=<redacted>" in scrubbed
    assert "https://cdn.example.invalid/a.mp4?page=2" in scrubbed
    assert "<redacted-path>" in scrubbed


def test_provider_error_response_is_scrubbed_before_it_becomes_an_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProviderErrorResponse:
        status_code = 401
        headers: dict[str, str] = {}
        text = ""

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "error": {
                    "message": f"Authorization Bearer {SECRET}",
                    "request_url": (
                        f"https://client:{USERINFO_SECRET}@api.example.invalid/v1"
                        f"?token={SIGNED_SECRET}"
                    ),
                    "debug_path": "C:\\Users\\Alice\\private\\.env",
                }
            }

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"synthetic audio")
    monkeypatch.setenv("ALI_ASR_API_KEY", SECRET)
    monkeypatch.setenv("ALI_ASR_ENDPOINT", "https://api.example.invalid/v1")
    monkeypatch.setattr(provider_adapters.network_policy, "validate_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        provider_adapters.network_policy,
        "reject_requests_redirect",
        lambda *_args, **_kwargs: None,
    )
    requests = pytest.importorskip("requests")
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: ProviderErrorResponse())

    with pytest.raises(SystemExit) as caught:
        provider_adapters.transcribe_compatible_audio_chat(
            argparse.Namespace(input=str(audio), output=str(tmp_path / "result.json"))
        )

    rendered = str(caught.value)
    assert "compatible ASR failed: 401" in rendered
    assert "<redacted>" in rendered
    assert_secrets_absent(rendered)


def test_workflow_notes_and_pipeline_results_scrub_provider_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALI_ASR_API_KEY", SECRET)
    run_dir = tmp_path / "run"
    (run_dir / "logs").mkdir(parents=True)
    creator_pipeline.write_json(
        run_dir / "workflow.plan.json",
        {
            "schema_version": 1,
            "status": "planned",
            "final_status": "pending",
            "steps": [{"step_id": "transcribe_with_aliyun_asr", "status": "pending"}],
        },
    )
    provider_echo = (
        f"Authorization Bearer {SECRET}; "
        f"https://client:{USERINFO_SECRET}@api.example.invalid/v1?token={SIGNED_SECRET}; "
        "C:\\Users\\Alice\\private\\.env"
    )

    creator_pipeline.update_workflow_state(
        run_dir,
        "transcribe_with_aliyun_asr",
        "failed",
        provider_echo,
    )
    step = StepResult.from_rows(
        "transcribe_with_aliyun_asr",
        [{"status": "failed", "error": provider_echo}],
    )
    result = PipelineResult.from_steps(
        str(run_dir),
        [step],
        quality_passed=False,
        error={"type": "ProviderError", "message": provider_echo},
    )
    pipeline_path = write_pipeline_result(run_dir / "logs" / "pipeline_result.json", result)

    persisted = "\n".join(
        (
            (run_dir / "workflow.plan.json").read_text(encoding="utf-8"),
            pipeline_path.read_text(encoding="utf-8"),
        )
    )
    assert "<redacted>" in persisted
    assert_secrets_absent(persisted)


def test_workflow_recovery_diagnostic_scrubs_exception_and_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ALI_ASR_API_KEY", SECRET)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    creator_pipeline.write_json(
        run_dir / "workflow.plan.json",
        {"steps": [{"step_id": "quality_check", "status": "pending"}]},
    )

    def provider_failure(_path: Path) -> object:
        raise OSError(
            f"Authorization Bearer {SECRET} at C:\\Users\\Alice\\private\\.env "
            f"https://api.example.invalid/v1?signature={SIGNED_SECRET}"
        )

    monkeypatch.setattr(creator_pipeline, "read_json", provider_failure)

    with pytest.raises(creator_pipeline.WorkflowStateError) as caught:
        creator_pipeline.update_workflow_state(run_dir, "quality_check", "failed")

    recovery_text = (run_dir / "logs" / "workflow_recovery_error.json").read_text(encoding="utf-8")
    visible = str(caught.value) + capsys.readouterr().err + recovery_text
    assert "<redacted>" in visible
    assert_secrets_absent(visible)


def test_runner_scrubs_provider_echo_from_terminal_workflow_and_all_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", SECRET)
    provider_echo = (
        f"Authorization Bearer {SECRET}; "
        f"https://client:{USERINFO_SECRET}@api.example.invalid/v1?signature={SIGNED_SECRET}; "
        "C:\\Users\\Alice\\private\\.env"
    )

    def fail_provider(_args: argparse.Namespace) -> None:
        raise RuntimeError(provider_echo)

    monkeypatch.setattr(provider_adapters, "fetch_tikhub_creator_videos", fail_provider)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_creator_skill_build.py",
            "--source-url",
            "https://share.example.invalid/profile",
            "--project-name",
            "provider-redaction-e2e",
            "--sample-count",
            "1",
            "--run-root",
            str(tmp_path / "runs"),
        ],
    )

    with pytest.raises(SystemExit) as caught:
        runner.main()

    project_root = tmp_path / "runs" / "provider-redaction-e2e"
    run_dirs = [path for path in project_root.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in run_dirs[0].rglob("*")
        if path.is_file()
    )
    captured = capsys.readouterr()
    visible = str(caught.value) + captured.out + captured.err + persisted
    assert "RuntimeError" in visible
    assert "<redacted>" in visible
    assert_secrets_absent(visible)
