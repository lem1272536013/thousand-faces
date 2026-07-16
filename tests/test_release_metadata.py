"""Release policy, disclosure, and persisted-format metadata must stay in sync."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import verify_docs_commands
import verify_release_metadata
from offline_scenarios import offline_subprocess_env


PUBLIC_VERSION_EXPECTATIONS = {
    "package_cli": "0.1.0",
    "scripts/run_diagnostics.py::RUN_FORMAT_SCHEMA_VERSION": "1",
    "scripts/settings.py::SETTINGS_SCHEMA_VERSION": "2",
    "scripts/schema_validation.py::SCHEMA_VERSION": "1.1.0",
    "scripts/research_taxonomy.py::TAXONOMY_PRESET_VERSION": "1.0.0",
}


def read_text(project_root: Path, relative: str) -> str:
    return (project_root / relative).read_text(encoding="utf-8")


def test_release_inventory_discovers_every_literal_schema_and_preset_version(
    project_root: Path,
) -> None:
    inventory = verify_release_metadata.collect_release_inventory(project_root)

    for key, value in PUBLIC_VERSION_EXPECTATIONS.items():
        assert inventory[key] == value

    assert "scripts/artifacts.py::ARTIFACT_SCHEMA_VERSION" in inventory
    assert "scripts/quality_engine.py::FRESHNESS_SCHEMA_VERSION" in inventory
    assert "scripts/oss_lifecycle.py::_MANIFEST_SCHEMA_VERSION" in inventory
    assert all(value.isdigit() or verify_release_metadata.is_semantic_version(value) for value in inventory.values())


def test_release_documents_and_source_versions_are_machine_verified(
    project_root: Path,
) -> None:
    assert verify_release_metadata.verify_project(project_root) == []


def test_changelog_current_inventory_rejects_undocumented_version_drift(
    project_root: Path,
) -> None:
    inventory = verify_release_metadata.collect_release_inventory(project_root)
    changelog = read_text(project_root, "CHANGELOG.md")
    drifted = dict(inventory)
    drifted["scripts/run_diagnostics.py::RUN_FORMAT_SCHEMA_VERSION"] = "2"

    errors = verify_release_metadata.verify_changelog(changelog, drifted)

    assert any("RUN_FORMAT_SCHEMA_VERSION" in error and "2" in error for error in errors)


def test_changelog_uses_the_current_package_version_instead_of_a_hardcoded_release(
    project_root: Path,
) -> None:
    inventory = verify_release_metadata.collect_release_inventory(project_root)
    future_inventory = {**inventory, "package_cli": "0.2.0"}
    future_changelog = read_text(project_root, "CHANGELOG.md").replace("0.1.0", "0.2.0")

    assert verify_release_metadata.verify_changelog(future_changelog, future_inventory) == []


def test_inventory_parser_reports_reversed_markers_without_crashing() -> None:
    text = """<!-- release-metadata:current:end -->
| `package_cli` | `0.1.0` |
<!-- release-metadata:current:start -->
"""

    inventory, errors = verify_release_metadata.parse_inventory_block(
        text,
        verify_release_metadata.CHANGELOG_MARKER,
    )

    assert inventory == {}
    assert errors == ["invalid release-metadata:current inventory block order"]


def test_changelog_lists_first_release_breaks_and_legacy_run_handling(
    project_root: Path,
) -> None:
    changelog = read_text(project_root, "CHANGELOG.md")

    assert "## [Unreleased]" in changelog
    assert "计划发布版本：`0.1.0`" in changelog
    assert "legacy_unverified" in changelog
    assert "不原地迁移" in changelog
    assert "settings_schema_version=2" in changelog
    assert "ALI_ASR_APP_KEY" in changelog


def test_security_policy_has_a_no_detail_public_handoff_and_log_rules(
    project_root: Path,
) -> None:
    policy = read_text(project_root, "SECURITY.md")

    assert "<!-- security-reporting: public-contact-with-private-handoff -->" in policy
    assert "https://github.com/lem1272536013/thousand-faces/issues/new" in policy
    assert "不要在公开 issue 中提交漏洞细节" in policy
    assert "draft security advisory" in policy.lower()
    for sensitive_kind in ("API key", "签名 URL", "完整 transcript", "个人信息"):
        assert sensitive_kind in policy
    assert "撤销或轮换" in policy


def test_contribution_policy_requires_tests_redacted_fixtures_and_small_changes(
    project_root: Path,
) -> None:
    guide = read_text(project_root, "CONTRIBUTING.md")

    assert "新增或改变行为必须先有失败测试" in guide
    assert "一个 PR 只处理一个 TF" in guide
    assert "example.invalid" in guide
    assert "不得使用真实凭证" in guide
    assert "CHANGELOG.md" in guide
    assert "schema/preset" in guide
    assert "python scripts/verify_release_metadata.py" in guide


def test_version_policy_keeps_release_and_artifact_axes_independent(
    project_root: Path,
) -> None:
    policy = read_text(project_root, "references/versioning.md")

    for key, value in PUBLIC_VERSION_EXPECTATIONS.items():
        assert f"| `{key}` | `{value}` |" in policy
    assert "版本号不要求相同" in policy
    assert "不能静默替换" in policy
    assert "0.x" in policy and "MINOR" in policy
    assert "additionalProperties: false" in policy


def test_release_verifier_is_documented_and_runs_before_tests_in_ci(
    project_root: Path,
) -> None:
    workflow = read_text(project_root, ".github/workflows/ci.yml")

    assert Path("CONTRIBUTING.md") in verify_docs_commands.DOCUMENT_PATHS
    assert "verify_release_metadata.py" in verify_docs_commands.ALLOWED_SCRIPTS
    assert "python scripts/verify_release_metadata.py" in workflow
    assert workflow.index("python scripts/verify_release_metadata.py") < workflow.index("python -m pytest")

    process = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "verify_release_metadata.py")],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert "release metadata verified" in process.stdout
