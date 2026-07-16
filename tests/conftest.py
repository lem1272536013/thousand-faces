"""Shared pytest fixtures for isolated, credential-free tests."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"

# The production entry points are standalone scripts and import sibling modules
# by name. Mirror that execution environment without turning tests into a package.
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the repository root resolved from the test suite location."""

    return PROJECT_ROOT


@pytest.fixture(scope="session")
def fixture_root() -> Path:
    """Return the root for synthetic, sanitized regression fixtures."""

    return FIXTURE_ROOT


@pytest.fixture
def run_root() -> Iterator[Path]:
    """Create an isolated run root outside the repository working tree."""

    with tempfile.TemporaryDirectory(prefix="thousand_faces_tests_") as temp_dir:
        path = Path(temp_dir) / "runs"
        path.mkdir()
        yield path


@pytest.fixture
def sanitized_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Install deterministic dummy provider settings and restore the environment afterwards."""

    values = {
        "TIKHUB_API_KEY": "test-tikhub-key",
        "TIKHUB_API_BASE": "https://api.example.invalid",
        "TIKHUB_CREATOR_VIDEOS_ENDPOINT": "/creator/videos",
        "ALI_ASR_PROVIDER": "openai-compatible",
        "ALI_ASR_API_KEY": "test-asr-key",
        "ALI_ASR_ENDPOINT": "https://asr.example.invalid/v1",
        "ALI_ASR_MODEL": "test-asr-model",
        "RUN_ROOT": "runs",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    yield values
