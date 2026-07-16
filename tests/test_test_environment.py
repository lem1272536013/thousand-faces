"""Smoke tests for the isolated development and test environment."""

from __future__ import annotations

import os
from pathlib import Path


def test_project_root_has_runtime_requirements(project_root: Path) -> None:
    assert (project_root / "requirements.txt").is_file()
    assert (project_root / "requirements-dev.txt").is_file()


def test_fixture_root_is_tracked_and_synthetic(fixture_root: Path) -> None:
    guidance = fixture_root / "README.md"
    assert guidance.is_file()
    assert "synthetic" in guidance.read_text(encoding="utf-8").lower()


def test_run_root_is_isolated_from_repository(project_root: Path, run_root: Path) -> None:
    assert run_root.is_dir()
    assert not run_root.is_relative_to(project_root)


def test_sanitized_env_uses_dummy_credentials(sanitized_env: dict[str, str]) -> None:
    assert sanitized_env["TIKHUB_API_KEY"] == "test-tikhub-key"
    assert sanitized_env["ALI_ASR_API_KEY"] == "test-asr-key"
    assert all(os.environ[key] == value for key, value in sanitized_env.items())
    url_keys = {"TIKHUB_API_BASE", "ALI_ASR_ENDPOINT"}
    assert all("example.invalid" in sanitized_env[key] for key in url_keys)
