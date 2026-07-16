"""Public CLI validation must fail before creating run artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from offline_scenarios import offline_subprocess_env


ENTRY_SCRIPTS = ("build_creator_skill.py", "run_creator_skill_build.py")


def entry_command(
    project_root: Path,
    run_root: Path,
    script_name: str,
    extra_args: list[str],
    project_name: str = "validation-test",
) -> list[str]:
    return [
        sys.executable,
        str(project_root / "scripts" / script_name),
        "--source-url",
        "https://share.example.invalid/profile",
        "--project-name",
        project_name,
        "--run-root",
        str(run_root),
        *extra_args,
    ]


def run_entry(
    project_root: Path,
    run_root: Path,
    script_name: str,
    extra_args: list[str],
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = offline_subprocess_env()
    env.update(env_override or {})
    return subprocess.run(
        entry_command(project_root, run_root, script_name, extra_args),
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.mark.parametrize("script_name", ENTRY_SCRIPTS)
@pytest.mark.parametrize("value", ["-1", "0", "1001", "not-an-integer"])
def test_invalid_sample_count_exits_nonzero_without_creating_run(
    project_root: Path,
    run_root: Path,
    script_name: str,
    value: str,
) -> None:
    output_root = run_root / "invalid-sample"

    process = run_entry(project_root, output_root, script_name, ["--sample-count", value])

    assert process.returncode != 0
    assert "sample-count" in process.stderr.lower() or "sample_count" in process.stderr.lower()
    assert not output_root.exists()


@pytest.mark.parametrize("script_name", ENTRY_SCRIPTS)
@pytest.mark.parametrize("value", ["0", "5001", "not-an-integer"])
def test_invalid_fetch_limit_exits_nonzero_without_creating_run(
    project_root: Path,
    run_root: Path,
    script_name: str,
    value: str,
) -> None:
    output_root = run_root / "invalid-fetch-limit"

    process = run_entry(project_root, output_root, script_name, ["--metadata-fetch-limit", value])

    assert process.returncode != 0
    assert "metadata-fetch-limit" in process.stderr.lower() or "metadata_fetch_limit" in process.stderr.lower()
    assert not output_root.exists()


@pytest.mark.parametrize("script_name", ENTRY_SCRIPTS)
@pytest.mark.parametrize("project_name", ["", "___", "x" * 81])
def test_invalid_project_name_exits_nonzero_without_creating_run(
    project_root: Path,
    run_root: Path,
    script_name: str,
    project_name: str,
) -> None:
    output_root = run_root / "invalid-project"
    command = entry_command(
        project_root,
        output_root,
        script_name,
        ["--sample-count", "1"],
        project_name,
    )
    process = subprocess.run(
        command,
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode != 0
    assert "project-name" in process.stderr.lower() or "project_name" in process.stderr.lower()
    assert not output_root.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("TIKHUB_METADATA_FETCH_LIMIT", "0"),
        ("TIKHUB_METADATA_FETCH_LIMIT", "5001"),
        ("TIKHUB_MAX_PAGES", "0"),
        ("TIKHUB_MAX_PAGES", "1001"),
        ("TIKHUB_ENABLE_PAGINATION", "sometimes"),
        ("TIKHUB_AUTO_RESOLVE_DOUYIN_URL", "sometimes"),
        ("ALI_ASR_ENABLE_ITN", "sometimes"),
        ("ALI_ASR_PROVIDER", "unknown-provider"),
        ("ALI_ASR_COMPATIBLE_API", "unknown-api"),
        ("TIKHUB_API_BASE", "api.example.invalid"),
        ("TIKHUB_CREATOR_VIDEOS_ENDPOINT", "https://evil.example.invalid/videos"),
        ("ALI_ASR_ENDPOINT", "ftp://asr.example.invalid/v1"),
        ("DOWNLOAD_CONCURRENCY", "0"),
        ("DOWNLOAD_CONCURRENCY", "33"),
        ("DOWNLOAD_CONCURRENCY", "many"),
        ("ALI_ASR_CONCURRENCY", "0"),
        ("ALI_ASR_CONCURRENCY", "17"),
        ("FFMPEG_CONCURRENCY", "0"),
        ("FFMPEG_CONCURRENCY", "9"),
        ("ALI_ASR_MAX_BASE64_AUDIO_BYTES", "0"),
        ("ALI_ASR_MAX_BASE64_AUDIO_BYTES", "33554433"),
        ("DOWNLOAD_RETRY", "0"),
        ("DOWNLOAD_RETRY", "21"),
        ("ALI_ASR_RETRY", "0"),
        ("ALI_ASR_RETRY", "21"),
        ("PROVIDER_RETRY_MAX_ATTEMPTS", "0"),
        ("PROVIDER_RETRY_MAX_ATTEMPTS", "21"),
        ("PROVIDER_RETRY_BASE_SECONDS", "-0.1"),
        ("PROVIDER_RETRY_BASE_SECONDS", "3601"),
        ("PROVIDER_RETRY_MAX_SECONDS", "-0.1"),
        ("PROVIDER_RETRY_MAX_SECONDS", "3601"),
        ("PROVIDER_RETRY_JITTER_RATIO", "-0.1"),
        ("PROVIDER_RETRY_JITTER_RATIO", "1.1"),
        ("PROVIDER_REQUEST_DEADLINE_SECONDS", "0"),
        ("PROVIDER_REQUEST_DEADLINE_SECONDS", "3601"),
        ("ALI_ASR_POLL_SECONDS", "0"),
        ("ALI_ASR_POLL_SECONDS", "3601"),
        ("ALI_ASR_POLL_DEADLINE_SECONDS", "0"),
        ("ALI_ASR_POLL_DEADLINE_SECONDS", "86401"),
        ("HTTP_TIMEOUT_SECONDS", "0"),
        ("HTTP_TIMEOUT_SECONDS", "3601"),
        ("MAX_VIDEO_BYTES", "0"),
        ("MAX_VIDEO_BYTES", "53687091201"),
        ("DOWNLOAD_HEADER_TIMEOUT_SECONDS", "0"),
        ("DOWNLOAD_HEADER_TIMEOUT_SECONDS", "3601"),
        ("DOWNLOAD_DEADLINE_SECONDS", "0"),
        ("DOWNLOAD_DEADLINE_SECONDS", "3601"),
        ("MEDIA_PROBE_TIMEOUT_SECONDS", "0"),
        ("MEDIA_PROBE_TIMEOUT_SECONDS", "3601"),
        ("ALI_ASR_TIMEOUT_SECONDS", "0"),
        ("ALI_ASR_TIMEOUT_SECONDS", "3601"),
        ("ASR_SEGMENT_SECONDS", "0"),
        ("ASR_SEGMENT_SECONDS", "3601"),
        ("ALI_OSS_SIGNED_URL_EXPIRES", "59"),
        ("ALI_OSS_SIGNED_URL_EXPIRES", "3601"),
        ("ALI_OSS_FAILURE_RETENTION_SECONDS", "59"),
        ("ALI_OSS_FAILURE_RETENTION_SECONDS", "2592001"),
        ("DRAFT_MIN_STAGE_COUNT", "0"),
        ("READY_MIN_STAGE_COUNT", "1001"),
        ("DRAFT_MIN_STAGE_RATIO", "0"),
        ("DRAFT_MIN_STAGE_RATIO", "not-a-ratio"),
        ("READY_MIN_STAGE_RATIO", "1.01"),
    ],
)
def test_invalid_runtime_config_exits_before_run_creation(
    project_root: Path,
    run_root: Path,
    key: str,
    value: str,
) -> None:
    output_root = run_root / "invalid-config"

    process = run_entry(
        project_root,
        output_root,
        "build_creator_skill.py",
        ["--sample-count", "1"],
        {key: value},
    )

    assert process.returncode != 0
    assert key in process.stderr
    assert not output_root.exists()


def test_unsafe_compatible_asr_memory_budget_exits_before_run_creation(
    project_root: Path,
    run_root: Path,
) -> None:
    output_root = run_root / "unsafe-asr-memory"

    process = run_entry(
        project_root,
        output_root,
        "build_creator_skill.py",
        ["--sample-count", "1"],
        {
            "ALI_ASR_PROVIDER": "openai-compatible",
            "ALI_ASR_CONCURRENCY": "16",
            "ALI_ASR_MAX_BASE64_AUDIO_BYTES": str(32 * 1024 * 1024),
        },
    )

    assert process.returncode != 0
    assert "in-flight memory budget" in process.stderr
    assert not output_root.exists()


def test_download_deadline_cannot_be_shorter_than_header_timeout(
    project_root: Path,
    run_root: Path,
) -> None:
    output_root = run_root / "invalid-download-deadline"

    process = run_entry(
        project_root,
        output_root,
        "build_creator_skill.py",
        ["--sample-count", "1"],
        {
            "DOWNLOAD_HEADER_TIMEOUT_SECONDS": "60",
            "DOWNLOAD_DEADLINE_SECONDS": "30",
        },
    )

    assert process.returncode != 0
    assert "DOWNLOAD_DEADLINE_SECONDS" in process.stderr
    assert not output_root.exists()


def test_provider_retry_max_delay_cannot_be_shorter_than_base_delay(
    project_root: Path,
    run_root: Path,
) -> None:
    output_root = run_root / "invalid-provider-backoff"

    process = run_entry(
        project_root,
        output_root,
        "build_creator_skill.py",
        ["--sample-count", "1"],
        {
            "PROVIDER_RETRY_BASE_SECONDS": "5",
            "PROVIDER_RETRY_MAX_SECONDS": "2",
        },
    )

    assert process.returncode != 0
    assert "PROVIDER_RETRY_MAX_SECONDS" in process.stderr
    assert not output_root.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ALI_OSS_LIFECYCLE_POLICY", "delete-never"),
        ("ALI_OSS_PREFIX", "../unmanaged"),
        ("ALI_OSS_PREFIX", "creator-agent-studio//audio"),
    ],
)
def test_invalid_oss_policy_exits_before_run_creation(
    project_root: Path,
    run_root: Path,
    key: str,
    value: str,
) -> None:
    output_root = run_root / "invalid-oss-policy"

    process = run_entry(
        project_root,
        output_root,
        "build_creator_skill.py",
        ["--sample-count", "1"],
        {key: value},
    )

    assert process.returncode != 0
    assert key in process.stderr
    assert not output_root.exists()


@pytest.mark.parametrize(
    "env_override",
    [
        {"DRAFT_MIN_STAGE_COUNT": "6", "READY_MIN_STAGE_COUNT": "5"},
        {"DRAFT_MIN_STAGE_RATIO": "0.96", "READY_MIN_STAGE_RATIO": "0.95"},
    ],
)
def test_stage_threshold_order_is_validated_before_run_creation(
    project_root: Path,
    run_root: Path,
    env_override: dict[str, str],
) -> None:
    output_root = run_root / "invalid-stage-order"

    process = run_entry(
        project_root,
        output_root,
        "build_creator_skill.py",
        ["--sample-count", "1"],
        env_override,
    )

    assert process.returncode != 0
    assert "READY_MIN_STAGE" in process.stderr
    assert not output_root.exists()


def test_creator_pipeline_rejects_invalid_sample_count_before_output(
    project_root: Path,
    run_root: Path,
) -> None:
    metadata = run_root / "metadata.json"
    output = run_root / "selected.json"
    metadata.write_text(json.dumps({"items": []}), encoding="utf-8")

    process = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "creator_pipeline.py"),
            "select-samples",
            "--input",
            str(metadata),
            "--output",
            str(output),
            "--sample-count",
            "0",
        ],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode != 0
    assert "sample-count" in process.stderr.lower() or "sample_count" in process.stderr.lower()
    assert not output.exists()


def test_chinese_project_name_remains_cli_compatible(
    project_root: Path,
    run_root: Path,
) -> None:
    output_root = run_root / "valid-chinese"
    command = entry_command(
        project_root,
        output_root,
        "build_creator_skill.py",
        ["--sample-count", "1"],
        "中文项目",
    )
    process = subprocess.run(
        command,
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode == 0
    project_root_dir = output_root / "中文项目"
    assert project_root_dir.is_dir()
    assert len([path for path in project_root_dir.iterdir() if path.is_dir()]) == 1
