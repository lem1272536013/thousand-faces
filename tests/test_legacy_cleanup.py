"""Contracts preventing retired research paths and configuration from returning."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import settings
import skill_builder
from research import merge_research


RETIRED_SETTINGS = {
    "ALI_ASR_APP_KEY",
    "AUTO_RESUME",
    "MAX_INPUT_TOKENS",
    "MAX_OUTPUT_TOKENS",
}


def test_retired_settings_are_absent_and_every_remaining_setting_has_a_lifecycle() -> None:
    assert settings.SETTINGS_SCHEMA_VERSION == 2
    assert RETIRED_SETTINGS.isdisjoint(settings.CONFIG_KEYS)
    assert set(settings.RETIRED_SETTING_GUIDANCE) == RETIRED_SETTINGS
    assert {spec.status for spec in settings.SETTING_SPECS} <= {
        settings.SettingStatus.ACTIVE,
        settings.SettingStatus.DEPRECATED,
    }
    for spec in settings.SETTING_SPECS:
        if spec.status is settings.SettingStatus.DEPRECATED:
            assert spec.replacement in settings.CONFIG_KEYS


@pytest.mark.parametrize("name", sorted(RETIRED_SETTINGS))
def test_explicit_retired_settings_fail_with_migration_guidance(name: str) -> None:
    with pytest.raises(settings.SettingsError, match=rf"{name} was removed"):
        settings.Settings.from_mapping({name: "legacy-value"})


def test_retired_setting_migration_is_enforced_without_claiming_process_env(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "legacy.env"
    env_file.write_text("AUTO_RESUME=true\n", encoding="utf-8")

    with pytest.raises(settings.SettingsError, match="AUTO_RESUME was removed"):
        settings.load_settings(env_file, environment={})
    with pytest.raises(settings.SettingsError, match="AUTO_RESUME was removed"):
        settings.load_settings(environment={}, overrides={"AUTO_RESUME": True})

    loaded = settings.load_settings(environment={"AUTO_RESUME": "unrelated-application"})
    assert "AUTO_RESUME" not in loaded


def test_research_merge_accepts_current_run_layout_and_rejects_knowledge_layout(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "current-run"
    research_root = run_dir / "research"
    (research_root / "raw").mkdir(parents=True)
    assert merge_research.resolve_research_root(run_dir) == research_root
    assert merge_research.resolve_research_root(research_root) == research_root

    legacy_skill = tmp_path / "legacy-skill"
    (legacy_skill / "knowledge" / "research" / "raw").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="research/raw"):
        merge_research.resolve_research_root(legacy_skill)


def test_creator_builder_has_no_orphan_transcript_or_style_research_fallback() -> None:
    source = Path(skill_builder.__file__).read_text(encoding="utf-8")

    assert not hasattr(skill_builder, "collect_transcript_corpus")
    assert "style_research.json" not in source


def test_generic_creator_prompts_have_an_unambiguous_home(project_root: Path) -> None:
    prompt_root = project_root / "references" / "prompts"
    creator_prompts = prompt_root / "creator"

    assert not (prompt_root / "celebrity").exists()
    assert {path.name for path in creator_prompts.glob("*.md")} == {
        "merger.md",
        "persona_analyzer.md",
        "persona_builder.md",
        "research.md",
    }


def test_each_runtime_requirement_is_imported_by_runtime_code(project_root: Path) -> None:
    requirement_names = {
        re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().replace("-", "_")
        for line in (project_root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-r"))
    }
    imported_modules: set[str] = set()
    for path in (project_root / "scripts").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.partition(".")[0])

    assert requirement_names
    assert requirement_names <= imported_modules
