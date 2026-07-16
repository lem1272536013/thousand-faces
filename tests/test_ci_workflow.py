"""The checked-in GitHub Actions workflow must enforce the project quality gates."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import build_creator_skill
import pytest


WORKFLOW_RELATIVE = Path(".github/workflows/ci.yml")
PINNED_ACTIONS = {
    "actions/checkout": (
        "de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "v6.0.2",
    ),
    "actions/setup-python": (
        "a309ff8b426b58ec0e2a45f0f869d46889d02405",
        "v6.2.0",
    ),
    "actions/upload-artifact": (
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "v7.0.1",
    ),
}


@pytest.fixture
def workflow_text(project_root: Path) -> str:
    path = project_root / WORKFLOW_RELATIVE
    assert path.is_file(), "TF-039 requires .github/workflows/ci.yml"
    return path.read_text(encoding="utf-8")


def test_ci_runs_for_main_and_pull_requests_with_bounded_concurrency(
    workflow_text: str,
) -> None:
    assert re.search(r"(?m)^  push:\s*$", workflow_text)
    assert re.search(r"(?ms)^  push:\s*\n    branches:\s*\n      - main\s*$", workflow_text)
    assert re.search(r"(?m)^  pull_request:\s*$", workflow_text)
    assert re.search(r"(?m)^  workflow_dispatch:\s*$", workflow_text)
    assert "cancel-in-progress: true" in workflow_text
    assert "timeout-minutes: 15" in workflow_text
    assert "fail-fast: false" in workflow_text


def test_ci_matrix_matches_the_declared_python_support(
    project_root: Path,
    workflow_text: str,
) -> None:
    project = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["requires-python"] == ">=3.11"
    assert project["tool"]["ruff"]["target-version"] == "py311"
    assert project["tool"]["mypy"]["python_version"] == "3.11"
    assert re.search(
        r"os:\s*\[\s*ubuntu-latest,\s*windows-latest\s*\]",
        workflow_text,
    )
    assert re.search(r"python-version:\s*\[\s*[\"']3\.11[\"']\s*\]", workflow_text)


def test_ci_uses_immutable_official_actions_and_minimal_permissions(
    workflow_text: str,
) -> None:
    assert re.search(r"(?ms)^permissions:\s*\n  contents: read\s*$", workflow_text)
    assert "persist-credentials: false" in workflow_text

    uses_lines = re.findall(r"(?m)^\s+uses:\s*([^\s#]+)(?:\s+#\s*(\S+))?\s*$", workflow_text)
    assert len(uses_lines) == len(PINNED_ACTIONS)
    for action, (commit, version) in PINNED_ACTIONS.items():
        assert (f"{action}@{commit}", version) in uses_lines


def test_ci_runs_every_project_gate_without_failure_suppression(
    workflow_text: str,
) -> None:
    required_commands = (
        "python -m pip install --upgrade pip",
        "python -m pip install -r requirements-dev.txt",
        "python -m pip check",
        "python -m ruff check .",
        "python -m mypy scripts",
        "python scripts/generate_config_docs.py --check",
        "python scripts/verify_release_metadata.py",
        "python -m pytest",
        "python scripts/self_test.py",
    )
    for command in required_commands:
        assert command in workflow_text

    pytest_line = next(
        line.strip() for line in workflow_text.splitlines() if "python -m pytest" in line
    )
    assert "--cov=scripts" in pytest_line
    assert "--cov-report=term-missing" in pytest_line
    assert "--cov-report=xml:reports/coverage.xml" in pytest_line
    assert "--cov-report=json:reports/coverage.json" in pytest_line
    assert "--junitxml=reports/junit.xml" in pytest_line
    assert pytest_line.endswith("-q")

    forbidden_suppression = ("continue-on-error", "|| true", "; true", "exit 0")
    assert not any(value in workflow_text for value in forbidden_suppression)


def test_ci_has_no_provider_secrets_or_live_provider_commands(
    workflow_text: str,
) -> None:
    assert "${{ secrets." not in workflow_text
    assert ".env" not in workflow_text
    assert "config_check.py --strict" not in workflow_text
    assert "provider_adapters.py" not in workflow_text
    for key in build_creator_skill.CONFIG_KEYS:
        assert key not in workflow_text


def test_ci_uploads_only_bounded_test_and_coverage_reports(
    workflow_text: str,
) -> None:
    assert "if: ${{ always() }}" in workflow_text
    assert "path: reports/" in workflow_text
    assert "retention-days: 14" in workflow_text
    assert "if-no-files-found: warn" in workflow_text
    assert "tests/fixtures" not in workflow_text
    assert "transcripts" not in workflow_text
    assert "runs/" not in workflow_text


def test_readme_links_ci_and_lists_local_parity_commands(
    project_root: Path,
) -> None:
    readme = (project_root / "README.md").read_text(encoding="utf-8")

    assert ".github/workflows/ci.yml" in readme
    assert "Windows" in readme and "Linux" in readme
    for command in (
        "python -m ruff check .",
        "python -m mypy scripts",
        "python -m pip check",
        "python scripts/generate_config_docs.py --check",
        "python scripts/verify_release_metadata.py",
        "python -m pytest --cov=scripts",
        "python scripts/self_test.py",
    ):
        assert command in readme
