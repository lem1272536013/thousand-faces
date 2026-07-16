"""Developer documentation must remain executable, complete, and safe by default."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import verify_docs_commands
from offline_scenarios import offline_subprocess_env


DOCUMENTS = (
    Path("README.md"),
    Path("SKILL.md"),
    Path("references/pipeline.md"),
    Path("references/host_refinement.md"),
)


def read_document(project_root: Path, relative: Path) -> str:
    return (project_root / relative).read_text(encoding="utf-8")


def test_readme_has_a_standalone_onboarding_path(project_root: Path) -> None:
    readme = read_document(project_root, Path("README.md"))

    assert "把这个项目发给 AI" not in readme
    for heading in (
        "## 快速开始",
        "### 安装",
        "### 离线自测",
        "### 离线 Demo",
        "### 真实运行",
        "### 宿主精修",
        "### 质量检查",
    ):
        assert heading in readme

    for command in (
        "python -m venv .venv",
        "python -m pip install -r requirements.txt",
        "python scripts/self_test.py",
        "python scripts/run_creator_skill_build.py",
        "--raw-metadata tests/fixtures/corpora/tech/metadata.json",
        "--transcripts-dir tests/fixtures/corpora/tech/transcripts",
        "python scripts/config_check.py --env .env --strict",
        "python scripts/prepare_host_refinement.py",
        "python scripts/creator_pipeline.py quality-check",
        "python scripts/verify_docs_commands.py",
    ):
        assert command in readme


def test_readme_explains_architecture_artifact_states_and_diagnostics(
    project_root: Path,
) -> None:
    readme = read_document(project_root, Path("README.md"))

    assert "```mermaid" in readme
    assert "run_summary.json" in readme
    for state in ("passed", "ready_for_use", "commercial_delivery_ready"):
        assert state in readme

    for diagnostic in (
        "TikHub 参数",
        "ffmpeg / ffprobe",
        "429 / RATE_LIMIT",
        "ASR endpoint",
        "部分 transcript",
        "STALE_ARTIFACT",
    ):
        assert diagnostic in readme


def test_readme_security_guide_covers_each_project_trust_boundary(
    project_root: Path,
) -> None:
    readme = read_document(project_root, Path("README.md"))

    for boundary in (
        "提示注入",
        "SSRF",
        "凭证",
        "OSS 生命周期",
        "授权",
        "删除",
    ):
        assert boundary in readme
    assert "不可信语料" in readme
    assert "--apply" in readme


def test_operational_docs_share_the_canonical_commands(project_root: Path) -> None:
    texts = {relative: read_document(project_root, relative) for relative in DOCUMENTS}

    for relative, text in texts.items():
        assert "python scripts/verify_docs_commands.py" in text, relative

    for relative in (
        Path("README.md"),
        Path("SKILL.md"),
        Path("references/pipeline.md"),
        Path("references/host_refinement.md"),
    ):
        text = texts[relative]
        assert "python scripts/prepare_host_refinement.py" in text, relative
        assert "python scripts/creator_pipeline.py quality-check" in text, relative

    pipeline = texts[Path("references/pipeline.md")]
    assert "--raw-metadata tests/fixtures/corpora/tech/metadata.json" in pipeline
    assert "--transcripts-dir tests/fixtures/corpora/tech/transcripts" in pipeline

    host = texts[Path("references/host_refinement.md")]
    assert "修改 evidence" in host
    assert "重新 prepare" in host
    assert "再次 quality-check" in host


def test_documentation_verifier_is_a_ci_gate_and_passes_offline(
    project_root: Path,
) -> None:
    workflow = read_document(project_root, Path(".github/workflows/ci.yml"))
    verifier = project_root / "scripts" / "verify_docs_commands.py"

    assert verifier.is_file()
    assert "python scripts/verify_docs_commands.py" in workflow
    assert workflow.index("python scripts/verify_docs_commands.py") < workflow.index(
        "python -m pytest"
    )

    process = subprocess.run(
        [sys.executable, str(verifier)],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    assert "documentation commands verified" in process.stdout
    assert "secret" not in process.stdout.lower()


def test_documentation_parser_treats_fence_content_as_data() -> None:
    text = """```powershell
Write-Output \"do not execute\"
python scripts/creator_pipeline.py quality-check `
  --run-dir .\\runs\\demo\\run-id `
  --json
```
"""

    commands = verify_docs_commands.documented_python_commands(text)

    assert commands == [
        "python scripts/creator_pipeline.py quality-check --run-dir .\\runs\\demo\\run-id --json"
    ]


def test_documentation_parser_includes_posix_python_commands() -> None:
    text = """```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```
"""

    commands = verify_docs_commands.documented_python_commands(text)

    assert commands == [
        "python3 -m venv .venv",
        "./.venv/bin/python -m pip install -r requirements.txt",
    ]


def test_documentation_parser_rejects_non_allowlisted_scripts() -> None:
    with pytest.raises(
        verify_docs_commands.DocumentationCommandError,
        match="not in the documentation allowlist",
    ):
        verify_docs_commands.parse_documented_command(
            Path("README.md"),
            "python scripts/provider_adapters.py oss-cleanup --run-dir .\\runs\\demo",
        )


def test_documentation_parser_rejects_unknown_pipeline_subcommand() -> None:
    with pytest.raises(
        verify_docs_commands.DocumentationCommandError,
        match="unknown creator_pipeline subcommand",
    ):
        verify_docs_commands.parse_documented_command(
            Path("README.md"),
            "python scripts/creator_pipeline.py quailty-check --run-dir .\\runs\\demo",
        )


def test_documentation_static_verifier_rejects_unknown_module_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "README.md").write_text(
        """```powershell
python -m pytest --definitely-not-a-pytest-option
```
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(verify_docs_commands, "DOCUMENT_PATHS", (Path("README.md"),))

    with pytest.raises(
        verify_docs_commands.DocumentationCommandError,
        match="unsupported option",
    ):
        verify_docs_commands.verify_static_commands(tmp_path)


def test_documentation_static_verifier_checks_current_cli_options(project_root: Path) -> None:
    assert verify_docs_commands.verify_static_commands(project_root) >= 40


def test_documentation_verifier_removes_project_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "synthetic-value")
    monkeypatch.setenv("ALI_ASR_API_KEY", "synthetic-value")

    environment = verify_docs_commands.sanitized_environment()

    assert "TIKHUB_API_KEY" not in environment
    assert "ALI_ASR_API_KEY" not in environment
