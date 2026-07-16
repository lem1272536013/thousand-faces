"""Single-source, typed runtime settings contracts."""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

import build_creator_skill
import config_check
import creator_pipeline
import provider_adapters
import resume_creator_run
import run_creator_skill_build
import settings
from input_validation import validate_stage_threshold_config
from offline_scenarios import offline_subprocess_env


def run_args(run_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        source_url="https://share.example.invalid/profile",
        project_name="typed-settings",
        sample_count=1,
        metadata_fetch_limit=None,
        run_root=str(run_root),
    )


def test_env_file_environment_and_cli_overrides_have_explicit_precedence(tmp_path: Path) -> None:
    env_file = tmp_path / "settings.env"
    env_file.write_text(
        "DOWNLOAD_CONCURRENCY=2\n"
        "RUN_ROOT=from-file\n"
        "TIKHUB_ENABLE_PAGINATION=false\n",
        encoding="utf-8",
    )

    loaded = settings.load_settings(
        env_file,
        environment={"DOWNLOAD_CONCURRENCY": "3", "RUN_ROOT": "from-environment"},
        overrides={"DOWNLOAD_CONCURRENCY": 4, "RUN_ROOT": "from-cli"},
    )

    assert loaded["DOWNLOAD_CONCURRENCY"] == 4
    assert loaded["RUN_ROOT"] == "from-cli"
    assert loaded["TIKHUB_ENABLE_PAGINATION"] is False
    assert loaded.source_for("DOWNLOAD_CONCURRENCY") == "cli"
    assert loaded.source_for("RUN_ROOT") == "cli"
    assert loaded.source_for("TIKHUB_ENABLE_PAGINATION") == ".env"
    assert loaded.source_for("FFMPEG_CONCURRENCY") == "default"


def test_settings_parse_boolean_integer_float_optional_and_enum_values() -> None:
    loaded = settings.Settings.from_mapping(
        {
            "TIKHUB_MAX_PAGES": "7",
            "PROVIDER_RETRY_JITTER_RATIO": "0.25",
            "ALI_ASR_ENDPOINT": "",
            "ALI_ASR_PROVIDER": "aliyun",
            "ALI_ASR_COMPATIBLE_API": "audio-transcriptions",
        }
    )

    assert loaded["TIKHUB_MAX_PAGES"] == 7
    assert loaded["PROVIDER_RETRY_JITTER_RATIO"] == 0.25
    assert loaded["ALI_ASR_ENDPOINT"] is None
    assert loaded["ALI_ASR_PROVIDER"] is settings.AsrProvider.ALIYUN
    assert loaded["ALI_ASR_COMPATIBLE_API"] is settings.CompatibleApi.AUDIO_TRANSCRIPTIONS
    assert loaded.as_env()["ALI_ASR_PROVIDER"] == "aliyun"


def test_legacy_asr_retry_only_fills_an_unconfigured_unified_retry_value() -> None:
    legacy_only = settings.Settings.from_mapping({"ALI_ASR_RETRY": "7"})
    explicit_new = settings.Settings.from_mapping(
        {"ALI_ASR_RETRY": "7", "PROVIDER_RETRY_MAX_ATTEMPTS": "5"}
    )

    assert legacy_only["PROVIDER_RETRY_MAX_ATTEMPTS"] == 7
    assert legacy_only.source_for("PROVIDER_RETRY_MAX_ATTEMPTS") == "ALI_ASR_RETRY compatibility"
    assert explicit_new["PROVIDER_RETRY_MAX_ATTEMPTS"] == 5


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("TIKHUB_ENABLE_PAGINATION", "truthy", "TIKHUB_ENABLE_PAGINATION"),
        ("TIKHUB_MAX_PAGES", "0", "TIKHUB_MAX_PAGES"),
        ("TIKHUB_MAX_PAGES", "1001", "TIKHUB_MAX_PAGES"),
        ("ALI_ASR_PROVIDER", "mystery", "ALI_ASR_PROVIDER"),
        ("ALI_ASR_COMPATIBLE_API", "unknown", "ALI_ASR_COMPATIBLE_API"),
        ("ALI_ASR_ENDPOINT", "ftp://asr.example.invalid/v1", "ALI_ASR_ENDPOINT"),
        ("TIKHUB_API_BASE", "https://user:password@api.example.invalid", "TIKHUB_API_BASE"),
        ("TIKHUB_CREATOR_VIDEOS_ENDPOINT", "https://evil.example.invalid/videos", "TIKHUB_CREATOR_VIDEOS_ENDPOINT"),
        ("TIKHUB_CREATOR_VIDEOS_ENDPOINT", "../admin/videos", "TIKHUB_CREATOR_VIDEOS_ENDPOINT"),
    ],
)
def test_invalid_typed_settings_fail_during_loading(key: str, value: str, message: str) -> None:
    with pytest.raises(settings.SettingsError, match=message):
        settings.Settings.from_mapping({key: value})


def test_every_setting_has_central_type_description_and_bounds_where_required() -> None:
    specs = settings.SETTING_SPECS

    assert len(specs) == len({spec.name for spec in specs})
    assert build_creator_skill.CONFIG_KEYS == settings.CONFIG_KEYS
    assert build_creator_skill.DEFAULTS == dict(settings.DEFAULT_ENV)
    assert all(spec.description.strip() for spec in specs)
    assert all(spec.value_type is not None for spec in specs)
    assert all(
        spec.minimum is not None and spec.maximum is not None
        for spec in specs
        if spec.value_type in {settings.SettingType.INTEGER, settings.SettingType.FLOAT}
    )
    assert {
        "TIKHUB_CURSOR_PARAM",
        "TIKHUB_ENABLE_PAGINATION",
        "TIKHUB_MAX_PAGES",
        "ALI_ASR_RETRY",
    } <= {spec.name for spec in specs}
    assert {
        "TIKHUB_API_KEY",
        "ALI_ASR_API_KEY",
        "DASHSCOPE_API_KEY",
        "ALI_OSS_ACCESS_KEY_ID",
        "ALI_OSS_ACCESS_KEY_SECRET",
    } <= {spec.name for spec in specs if spec.secret}


def test_unknown_cli_override_is_rejected_instead_of_silently_ignored() -> None:
    with pytest.raises(settings.SettingsError, match="UNKNOWN_SETTING"):
        settings.load_settings(environment={}, overrides={"UNKNOWN_SETTING": "value"})


def test_default_asr_provider_and_model_have_one_canonical_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALI_ASR_PROVIDER", raising=False)
    monkeypatch.delenv("ALI_ASR_MODEL", raising=False)

    loaded = settings.load_settings(environment={})

    assert loaded["ALI_ASR_PROVIDER"] is settings.AsrProvider.OPENAI_COMPATIBLE
    assert loaded["ALI_ASR_MODEL"] == "qwen3-asr-flash"
    assert settings.DEFAULT_ENV["ALI_ASR_PROVIDER"] == "openai-compatible"
    assert settings.DEFAULT_ENV["ALI_ASR_MODEL"] == "qwen3-asr-flash"
    assert build_creator_skill.DEFAULTS["ALI_ASR_PROVIDER"] == settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]
    assert build_creator_skill.DEFAULTS["ALI_ASR_MODEL"] == settings.DEFAULT_ENV["ALI_ASR_MODEL"]


def test_explicit_aliyun_provider_uses_its_central_model_default() -> None:
    loaded = settings.Settings.from_mapping({"ALI_ASR_PROVIDER": "aliyun"})

    assert loaded["ALI_ASR_MODEL"] == "fun-asr"
    assert settings.default_asr_model(settings.AsrProvider.ALIYUN) == "fun-asr"


def test_runner_artifact_spec_uses_canonical_asr_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALI_ASR_PROVIDER", raising=False)
    monkeypatch.delenv("ALI_ASR_MODEL", raising=False)
    audio = tmp_path / "default-model.mp3"
    audio.write_bytes(b"synthetic-audio")

    spec = run_creator_skill_build.asr_raw_artifact_spec(audio)

    assert spec.config["provider"] == settings.DEFAULT_ENV["ALI_ASR_PROVIDER"]
    assert spec.config["model"] == settings.DEFAULT_ENV["ALI_ASR_MODEL"]

    monkeypatch.setenv("ALI_ASR_PROVIDER", "aliyun")
    aliyun_spec = run_creator_skill_build.asr_raw_artifact_spec(audio)
    assert aliyun_spec.config["model"] == "fun-asr"


def test_ordinary_serialization_and_run_snapshot_never_include_secret_fields(tmp_path: Path) -> None:
    secret = "synthetic-settings-secret"
    loaded = settings.Settings.from_mapping(
        {
            "TIKHUB_API_KEY": secret,
            "ALI_ASR_API_KEY": "synthetic-asr-secret",
            "ALI_OSS_ACCESS_KEY_ID": "synthetic-access-id",
            "ALI_OSS_ACCESS_KEY_SECRET": "synthetic-access-secret",
            "ALI_ASR_ENDPOINT": f"https://asr.example.invalid/v1?token={secret}",
            "TIKHUB_EXTRA_QUERY": f"cursor=1&signature={secret}",
            "DOWNLOAD_CONCURRENCY": "5",
        }
    )

    ordinary = loaded.to_dict()
    assert ordinary["DOWNLOAD_CONCURRENCY"] == 5
    assert "TIKHUB_API_KEY" not in ordinary
    assert "ALI_ASR_API_KEY" not in ordinary
    assert secret not in json.dumps(ordinary, ensure_ascii=False)
    assert secret not in repr(loaded)

    run_dir = build_creator_skill.create_run(run_args(tmp_path), loaded)
    snapshot_text = (run_dir / "config.snapshot.json").read_text(encoding="utf-8")
    snapshot = json.loads(snapshot_text)
    assert snapshot["settings_schema_version"] == settings.SETTINGS_SCHEMA_VERSION
    assert snapshot["DOWNLOAD_CONCURRENCY"] == 5
    assert snapshot["TIKHUB_ENABLE_PAGINATION"] is True
    assert snapshot["TIKHUB_CURSOR_PARAM"] == "max_cursor"
    assert snapshot["TIKHUB_MAX_PAGES"] == 20
    assert snapshot["ALI_ASR_PROVIDER"] == "openai-compatible"
    assert snapshot["ALI_ASR_MODEL"] == "qwen3-asr-flash"
    assert "TIKHUB_API_KEY" not in snapshot
    assert "ALI_ASR_API_KEY" not in snapshot
    assert "ALI_OSS_ACCESS_KEY_ID" not in snapshot
    assert "ALI_OSS_ACCESS_KEY_SECRET" not in snapshot
    assert secret not in snapshot_text


def test_runtime_entrypoints_use_the_single_settings_loader() -> None:
    runtime_modules = (
        build_creator_skill,
        config_check,
        creator_pipeline,
        provider_adapters,
        resume_creator_run,
        run_creator_skill_build,
    )

    for module in runtime_modules:
        source = inspect.getsource(module)
        assert "def load_env_file" not in source, module.__name__
        assert "settings.load_settings" in source, module.__name__


@pytest.mark.parametrize(
    "arguments",
    [
        ["config_check.py", "--strict"],
        ["creator_pipeline.py", "run-summary", "--run-dir", "missing-run"],
        [
            "provider_adapters.py",
            "compatible-asr-file",
            "--input",
            "missing.mp3",
            "--output",
            "missing.json",
        ],
        ["resume_creator_run.py", "--run-dir", "missing-run", "--project-name", "settings-test"],
    ],
)
def test_each_auxiliary_runtime_entrypoint_fails_invalid_settings_before_work(
    project_root: Path,
    tmp_path: Path,
    arguments: list[str],
) -> None:
    env_file = tmp_path / "invalid.env"
    env_file.write_text("DOWNLOAD_CONCURRENCY=not-an-integer\n", encoding="utf-8")
    command = [sys.executable, str(project_root / "scripts" / arguments[0]), "--env", str(env_file)]
    command.extend(arguments[1:])

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
    assert "DOWNLOAD_CONCURRENCY" in process.stderr


def test_legacy_flat_string_snapshot_remains_readable() -> None:
    legacy_snapshot = {
        "ALI_ASR_PROVIDER": "historic-provider-name",
        "UNRELATED_LEGACY_FIELD": "preserve-for-diagnostics",
        "DRAFT_MIN_STAGE_COUNT": "2",
        "DRAFT_MIN_STAGE_RATIO": "0.80",
        "READY_MIN_STAGE_COUNT": "5",
        "READY_MIN_STAGE_RATIO": "0.95",
    }

    assert validate_stage_threshold_config(legacy_snapshot) == {
        "draft": {"min_count": 2, "min_ratio": 0.8},
        "ready": {"min_count": 5, "min_ratio": 0.95},
    }
