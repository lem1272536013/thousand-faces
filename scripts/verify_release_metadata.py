#!/usr/bin/env python3
"""Verify release policy documents against persisted schema and preset versions."""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path


SEMANTIC_VERSION = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
VERSION_CONSTANT = re.compile(r"(?:^|_)SCHEMA_VERSION$|_PRESET_VERSION$")
INVENTORY_ROW = re.compile(r"^\| `(?P<key>[^`]+)` \| `(?P<value>[^`]+)` \|")
CHANGELOG_MARKER = "release-metadata:current"
VERSIONING_MARKER = "versioning-metadata:current"
PUBLIC_VERSION_KEYS = (
    "package_cli",
    "scripts/run_diagnostics.py::RUN_FORMAT_SCHEMA_VERSION",
    "scripts/settings.py::SETTINGS_SCHEMA_VERSION",
    "scripts/schema_validation.py::SCHEMA_VERSION",
    "scripts/research_taxonomy.py::TAXONOMY_PRESET_VERSION",
)


class ReleaseMetadataError(RuntimeError):
    """Raised when a source version cannot be read deterministically."""


def is_semantic_version(value: str) -> bool:
    """Return whether *value* follows Semantic Versioning 2.0.0 syntax."""

    return SEMANTIC_VERSION.fullmatch(value) is not None


def _literal_versions(path: Path, project_root: Path) -> dict[str, str]:
    """Read module-level persisted-format version constants without importing code."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ReleaseMetadataError(f"cannot parse version source {path}: {exc}") from exc

    versions: dict[str, str] = {}
    for statement in tree.body:
        assignments: list[tuple[str, ast.expr | None]] = []
        if isinstance(statement, ast.Assign):
            assignments.extend(
                (target.id, statement.value)
                for target in statement.targets
                if isinstance(target, ast.Name)
            )
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            assignments.append((statement.target.id, statement.value))

        for name, node in assignments:
            if not VERSION_CONSTANT.search(name):
                continue
            try:
                value = ast.literal_eval(node) if node is not None else None
            except (ValueError, TypeError) as exc:
                raise ReleaseMetadataError(
                    f"version constant must be a literal: {path.name}::{name}"
                ) from exc
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise ReleaseMetadataError(
                    f"version constant must be an integer or string: {path.name}::{name}"
                )
            relative = path.relative_to(project_root).as_posix()
            versions[f"{relative}::{name}"] = str(value)
    return versions


def collect_release_inventory(project_root: Path) -> dict[str, str]:
    """Collect package, persisted schema, and preset versions from source literals."""

    pyproject_path = project_root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        package_version = pyproject["project"]["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise ReleaseMetadataError(f"cannot read project.version from {pyproject_path}") from exc
    if not isinstance(package_version, str) or not is_semantic_version(package_version):
        raise ReleaseMetadataError("pyproject.toml project.version must be Semantic Versioning 2.0.0")

    discovered: dict[str, str] = {}
    scripts_root = project_root / "scripts"
    for path in sorted(scripts_root.rglob("*.py")):
        discovered.update(_literal_versions(path, project_root))
    if not discovered:
        raise ReleaseMetadataError("no persisted schema or preset version constants were found")

    invalid = [
        f"{key}={value}"
        for key, value in discovered.items()
        if not (
            (value.isdigit() and int(value) > 0 and str(int(value)) == value)
            or is_semantic_version(value)
        )
    ]
    if invalid:
        raise ReleaseMetadataError(
            "schema/preset versions must be positive integers or semantic versions: "
            + ", ".join(invalid)
        )

    inventory = {"package_cli": package_version}
    inventory.update(dict(sorted(discovered.items())))
    missing = [key for key in PUBLIC_VERSION_KEYS if key not in inventory]
    if missing:
        raise ReleaseMetadataError(
            "missing required public version source(s): " + ", ".join(missing)
        )
    return inventory


def parse_inventory_block(text: str, marker: str) -> tuple[dict[str, str], list[str]]:
    """Parse one current-version Markdown table delimited by stable comments."""

    start_token = f"<!-- {marker}:start -->"
    end_token = f"<!-- {marker}:end -->"
    if text.count(start_token) != 1 or text.count(end_token) != 1:
        return {}, [f"expected exactly one {marker} inventory block"]
    start_position = text.index(start_token)
    end = text.index(end_token)
    start = start_position + len(start_token)
    if end <= start_position:
        return {}, [f"invalid {marker} inventory block order"]

    inventory: dict[str, str] = {}
    errors: list[str] = []
    for line in text[start:end].splitlines():
        match = INVENTORY_ROW.match(line.strip())
        if match is None:
            continue
        key = match.group("key")
        if key in inventory:
            errors.append(f"duplicate version inventory key: {key}")
        inventory[key] = match.group("value")
    if not inventory:
        errors.append(f"{marker} inventory block contains no version rows")
    return inventory, errors


def _compare_inventory(
    documented: Mapping[str, str],
    expected: Mapping[str, str],
    *,
    label: str,
) -> list[str]:
    errors: list[str] = []
    for key, value in expected.items():
        actual = documented.get(key)
        if actual != value:
            errors.append(f"{label} version drift: {key} must be {value}, found {actual!r}")
    extras = sorted(set(documented).difference(expected))
    if extras:
        errors.append(f"{label} has unknown version source(s): {', '.join(extras)}")
    return errors


def verify_changelog(changelog: str, inventory: Mapping[str, str]) -> list[str]:
    """Check release notes, migration warnings, and the full current inventory."""

    errors: list[str] = []
    package_version = inventory.get("package_cli", "<missing>")
    settings_version = inventory.get(
        "scripts/settings.py::SETTINGS_SCHEMA_VERSION",
        "<missing>",
    )
    required_text = (
        "## [Unreleased]",
        f"计划发布版本：`{package_version}`",
        "legacy_unverified",
        "不原地迁移",
        f"settings_schema_version={settings_version}",
        "### Security",
        "### Deprecated",
        "### 迁移 / Breaking Changes",
    )
    for value in required_text:
        if value not in changelog:
            errors.append(f"CHANGELOG.md missing required release note: {value}")

    documented, parse_errors = parse_inventory_block(changelog, CHANGELOG_MARKER)
    errors.extend(parse_errors)
    errors.extend(_compare_inventory(documented, inventory, label="CHANGELOG.md"))
    return errors


def verify_security_policy(policy: str) -> list[str]:
    """Check that the current no-detail public handoff is explicit and safe."""

    required_text = (
        "<!-- security-reporting: public-contact-with-private-handoff -->",
        "https://github.com/lem1272536013/thousand-faces/issues/new",
        "不要在公开 issue 中提交漏洞细节",
        "draft security advisory",
        "API key",
        "签名 URL",
        "完整 transcript",
        "个人信息",
        "撤销或轮换",
    )
    return [f"SECURITY.md missing required policy: {value}" for value in required_text if value not in policy]


def verify_contribution_policy(guide: str) -> list[str]:
    """Check tests, fixture hygiene, task size, and version-change obligations."""

    required_text = (
        "新增或改变行为必须先有失败测试",
        "一个 PR 只处理一个 TF",
        "example.invalid",
        "不得使用真实凭证",
        "CHANGELOG.md",
        "schema/preset",
        "python scripts/verify_release_metadata.py",
    )
    return [
        f"CONTRIBUTING.md missing required contribution rule: {value}"
        for value in required_text
        if value not in guide
    ]


def verify_versioning_policy(policy: str, inventory: Mapping[str, str]) -> list[str]:
    """Check the independent public compatibility axes and their current values."""

    required_text = (
        "版本号不要求相同",
        "不能静默替换",
        "0.x",
        "MINOR",
        "additionalProperties: false",
    )
    errors = [
        f"references/versioning.md missing required rule: {value}"
        for value in required_text
        if value not in policy
    ]
    documented, parse_errors = parse_inventory_block(policy, VERSIONING_MARKER)
    errors.extend(parse_errors)
    expected = {key: inventory[key] for key in PUBLIC_VERSION_KEYS}
    errors.extend(_compare_inventory(documented, expected, label="references/versioning.md"))
    return errors


def verify_project(project_root: Path) -> list[str]:
    """Return every release metadata failure without accessing git, network, or secrets."""

    try:
        inventory = collect_release_inventory(project_root)
    except ReleaseMetadataError as exc:
        return [str(exc)]

    paths = {
        "SECURITY.md": project_root / "SECURITY.md",
        "CONTRIBUTING.md": project_root / "CONTRIBUTING.md",
        "CHANGELOG.md": project_root / "CHANGELOG.md",
        "references/versioning.md": project_root / "references" / "versioning.md",
    }
    texts: dict[str, str] = {}
    errors: list[str] = []
    for label, path in paths.items():
        try:
            texts[label] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"missing or unreadable release document {label}: {exc}")
    if errors:
        return errors

    errors.extend(verify_security_policy(texts["SECURITY.md"]))
    errors.extend(verify_contribution_policy(texts["CONTRIBUTING.md"]))
    errors.extend(verify_changelog(texts["CHANGELOG.md"], inventory))
    errors.extend(verify_versioning_policy(texts["references/versioning.md"], inventory))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify security, contribution, changelog, and version compatibility metadata"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to verify (defaults to this script's parent repository)",
    )
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    errors = verify_project(project_root)
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        print(f"release metadata verification failed ({len(errors)} error(s))", file=sys.stderr)
        return 1
    inventory = collect_release_inventory(project_root)
    print(f"PASS release metadata verified ({len(inventory)} version sources)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
