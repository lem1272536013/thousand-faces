"""Generated configuration artifacts must stay synchronized with Settings."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path

import config_check
import generate_config_docs
import settings
from jsonschema import Draft202012Validator
from offline_scenarios import offline_subprocess_env


ASSIGNMENT = re.compile(r"^(?:# )?([A-Z][A-Z0-9_]*)=(.*)$")
HISTORICALLY_OMITTED = {
    "TIKHUB_CURSOR_PARAM",
    "TIKHUB_ENABLE_PAGINATION",
    "TIKHUB_MAX_PAGES",
    "ALI_ASR_RETRY",
}


def template_values(content: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for line in content.splitlines()
        if (match := ASSIGNMENT.fullmatch(line))
    }


def test_setting_metadata_classifies_advanced_and_deprecated_fields() -> None:
    specs = settings.SETTING_SPECS

    assert all(isinstance(spec.group, settings.SettingGroup) for spec in specs)
    assert all(isinstance(spec.tier, settings.SettingTier) for spec in specs)
    assert all(isinstance(spec.status, settings.SettingStatus) for spec in specs)
    assert any(spec.tier is settings.SettingTier.ADVANCED for spec in specs)
    assert settings.setting_spec("ALI_ASR_RETRY").status is settings.SettingStatus.DEPRECATED
    assert settings.setting_spec("ALI_ASR_RETRY").replacement == "PROVIDER_RETRY_MAX_ATTEMPTS"
    assert all(spec.status is not settings.SettingStatus.DEPRECATED or spec.replacement for spec in specs)


def test_generic_and_tikhub_v3_templates_cover_every_setting_with_only_preset_differences() -> None:
    generic = generate_config_docs.render_env_template(generate_config_docs.GENERIC_PROFILE)
    app_v3 = generate_config_docs.render_env_template(generate_config_docs.TIKHUB_APP_V3_PROFILE)
    generic_values = template_values(generic)
    app_v3_values = template_values(app_v3)

    assert set(generic_values) == set(settings.CONFIG_KEYS)
    assert set(app_v3_values) == set(settings.CONFIG_KEYS)
    assert {
        key for key in settings.CONFIG_KEYS if generic_values[key] != app_v3_values[key]
    } == set(settings.TIKHUB_APP_V3_PRESET)
    assert {
        key: app_v3_values[key]
        for key in settings.TIKHUB_APP_V3_PRESET
    } == dict(settings.TIKHUB_APP_V3_PRESET)
    assert "Profile: generic" in generic
    assert "Profile: tikhub-app-v3" in app_v3
    assert "Intentional difference" in generic
    assert "Intentional difference" in app_v3
    for spec in settings.SETTING_SPECS:
        expected_generic = "" if spec.default is None else str(spec.default)
        if isinstance(spec.default, bool):
            expected_generic = "true" if spec.default else "false"
        elif isinstance(spec.default, float):
            expected_generic = format(spec.default, ".15g")
        assert generic_values[spec.name] == ("" if spec.secret else expected_generic)
        if spec.secret:
            assert generic_values[spec.name] == ""
            assert app_v3_values[spec.name] == ""
    loaded_preset = settings.Settings.from_mapping(settings.TIKHUB_APP_V3_PRESET)
    assert all(loaded_preset.as_env()[name] == value for name, value in settings.TIKHUB_APP_V3_PRESET.items())


def test_generated_schema_table_templates_and_snapshot_include_historic_omissions() -> None:
    schema = generate_config_docs.settings_schema()
    generic = generate_config_docs.render_env_template(generate_config_docs.GENERIC_PROFILE)
    table = generate_config_docs.render_reference_table()
    snapshot = settings.Settings.from_mapping({}).snapshot()

    assert set(schema["properties"]) == set(settings.CONFIG_KEYS)
    assert HISTORICALLY_OMITTED <= set(schema["properties"])
    assert HISTORICALLY_OMITTED <= set(template_values(generic))
    assert HISTORICALLY_OMITTED <= set(snapshot)
    settings_table = table.split("#### Settings 字段表", 1)[1]
    for name in settings.CONFIG_KEYS:
        assert settings_table.count(f"| `{name}` |") == 1
    assert "advanced" in table
    assert "deprecated" in table
    assert "TikHub App V3 recommended preset" in table


def test_generated_schema_is_valid_and_accepts_normalized_nonsecret_settings() -> None:
    schema = generate_config_docs.settings_schema()

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(settings.Settings.from_mapping({}).to_dict())


def test_committed_generated_outputs_are_exactly_current(project_root: Path) -> None:
    assert generate_config_docs.find_drift(project_root) == []


def test_new_setting_metadata_causes_all_generated_artifacts_to_drift(
    project_root: Path,
    monkeypatch,
) -> None:
    extra = dataclasses.replace(
        settings.SETTING_SPECS[-1],
        name="FUTURE_CONFIG_FOR_DRIFT_TEST",
        description="Synthetic setting proving generated artifact drift.",
    )
    monkeypatch.setattr(settings, "SETTING_SPECS", (*settings.SETTING_SPECS, extra))

    drift = set(generate_config_docs.find_drift(project_root))

    assert {
        Path(".env.example"),
        Path("references/config.example.env"),
        Path("references/configuration.md"),
        Path("references/settings.schema.json"),
    } <= drift


def test_check_mode_reports_drift_without_modifying_files(project_root: Path, tmp_path: Path) -> None:
    for relative, expected in generate_config_docs.expected_outputs(project_root).items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")
    template = tmp_path / ".env.example"
    template.write_text(template.read_text(encoding="utf-8") + "# manual drift\n", encoding="utf-8")
    before = template.read_bytes()

    process = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "generate_config_docs.py"),
            "--check",
            "--root",
            str(tmp_path),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode == 1
    assert ".env.example" in process.stdout
    assert template.read_bytes() == before


def test_include_config_uses_settings_metadata_and_never_exposes_secret_fragments(
    monkeypatch,
) -> None:
    secret = "synthetic-config-check-secret"
    active = settings.Settings.from_mapping(
        {
            "TIKHUB_API_KEY": secret,
            "ALI_ASR_ENDPOINT": f"https://asr.example.invalid/v1?mode=safe&token={secret}",
            "TIKHUB_EXTRA_QUERY": f"cursor=1&signature={secret}",
        }
    )
    monkeypatch.setattr(config_check.settings, "load_settings", lambda *args, **kwargs: active)
    monkeypatch.setattr(config_check, "check_package", lambda _name: False)
    monkeypatch.setattr(config_check.shutil, "which", lambda _name: None)
    monkeypatch.setattr(config_check.provider_adapters, "oss_configured", lambda: False)

    report = config_check.check_config(argparse.Namespace(env=None, include_config=True))
    rendered = json.dumps(report["redacted_config"], ensure_ascii=False)

    assert report["redacted_config"]["TIKHUB_API_KEY"] == "<redacted>"
    assert report["redacted_config"]["ALI_ASR_ENDPOINT"] == "https://asr.example.invalid/v1?mode=safe"
    assert report["redacted_config"]["TIKHUB_EXTRA_QUERY"] == "cursor=1&signature=<redacted>"
    assert secret not in rendered
    assert "synthetic" not in rendered


def test_include_config_cli_never_prints_secret_fragments(project_root: Path, tmp_path: Path) -> None:
    secret = "synthetic-cli-config-secret"
    env_file = tmp_path / "synthetic.env"
    env_file.write_text(
        "TIKHUB_API_KEY=" + secret + "\n"
        "ALI_ASR_ENDPOINT=https://asr.example.invalid/v1?mode=safe&token=" + secret + "\n"
        "TIKHUB_EXTRA_QUERY=cursor=1&signature=" + secret + "\n",
        encoding="utf-8",
    )

    process = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "config_check.py"),
            "--env",
            str(env_file),
            "--include-config",
        ],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode == 0, process.stderr
    payload = json.loads(process.stdout)
    assert payload["redacted_config"]["TIKHUB_API_KEY"] == "<redacted>"
    assert payload["redacted_config"]["ALI_ASR_ENDPOINT"] == "https://asr.example.invalid/v1?mode=safe"
    assert secret not in process.stdout
    assert "synthetic-cli" not in process.stdout
