#!/usr/bin/env python3
"""Generate and verify configuration artifacts from the Settings catalog."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path

import settings
from io_utils import atomic_write_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERIC_PROFILE = "generic"
TIKHUB_APP_V3_PROFILE = "tikhub-app-v3"
GENERATED_TABLE_START = "<!-- BEGIN GENERATED SETTINGS REFERENCE -->"
GENERATED_TABLE_END = "<!-- END GENERATED SETTINGS REFERENCE -->"

_OUTPUT_PATHS = (
    Path(".env.example"),
    Path("references/config.example.env"),
    Path("references/configuration.md"),
    Path("references/settings.schema.json"),
)
_GROUP_TITLES = {
    settings.SettingGroup.TIKHUB: "TikHub collection",
    settings.SettingGroup.ASR: "ASR and audio",
    settings.SettingGroup.OSS: "OSS temporary audio",
    settings.SettingGroup.RECOVERY: "Provider recovery",
    settings.SettingGroup.RUNTIME: "Local runtime",
    settings.SettingGroup.QUALITY: "Quality thresholds",
}


def _specs() -> tuple[settings.SettingSpec, ...]:
    return tuple(settings.SETTING_SPECS)


def _environment_text(value: settings.SettingValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".15g")
    if value is None:
        return ""
    return str(value)


def _json_value(value: settings.SettingValue) -> str | int | float | bool | None:
    return value.value if isinstance(value, StrEnum) else value


def _profile_overrides(profile: str) -> Mapping[str, str]:
    if profile == GENERIC_PROFILE:
        return {}
    if profile == TIKHUB_APP_V3_PROFILE:
        return settings.TIKHUB_APP_V3_PRESET
    raise ValueError(f"unknown configuration profile: {profile}")


def _status_label(spec: settings.SettingSpec) -> str:
    if spec.status is settings.SettingStatus.DEPRECATED:
        return f"deprecated; use {spec.replacement}"
    return spec.status.value


def _type_label(spec: settings.SettingSpec) -> str:
    label = spec.value_type.value
    if spec.optional:
        label += ", optional"
    if spec.enum_type is not None:
        choices = ", ".join(member.value for member in spec.enum_type)
        label += f" ({choices})"
    if spec.minimum is not None or spec.maximum is not None:
        label += f" [{_environment_text(spec.minimum)}..{_environment_text(spec.maximum)}]"
    return label


def render_env_template(profile: str) -> str:
    """Render one complete copyable template from the current Settings catalog."""

    overrides = _profile_overrides(profile)
    if profile == GENERIC_PROFILE:
        profile_note = (
            "Intentional difference from .env.example: generic Settings defaults are used; "
            "no TikHub endpoint preset is applied."
        )
    else:
        profile_note = (
            "Intentional difference from references/config.example.env: only the named "
            "TikHub App V3 preset overrides generic Settings defaults."
        )
    lines = [
        "# GENERATED FILE - edit scripts/settings.py, then run:",
        "#   python scripts/generate_config_docs.py",
        f"# Profile: {profile}",
        f"# {profile_note}",
        "# Copy to .env for a live run; never place real credentials in this template.",
        "",
    ]
    if profile == TIKHUB_APP_V3_PROFILE:
        lines.extend(
            [
                "# Recommended preset values are validated by Settings and remain explicit here:",
                *(f"#   {name}={value}" for name, value in overrides.items()),
                "",
            ]
        )

    specs = _specs()
    for group in settings.SettingGroup:
        grouped = [spec for spec in specs if spec.group is group]
        if not grouped:
            continue
        lines.extend([f"# --- {_GROUP_TITLES[group]} ---", ""])
        for spec in grouped:
            labels = [spec.tier.value, _status_label(spec)]
            if spec.secret:
                labels.append("secret")
            lines.append(f"# {spec.description}")
            lines.append(f"# Metadata: {_type_label(spec)}; {', '.join(labels)}")
            value = "" if spec.secret else overrides.get(spec.name, _environment_text(spec.default))
            assignment = f"{spec.name}={value}"
            if spec.status is not settings.SettingStatus.ACTIVE:
                assignment = f"# {assignment}"
            lines.extend([assignment, ""])
    return "\n".join(lines).rstrip() + "\n"


def _schema_type(spec: settings.SettingSpec) -> str | list[str]:
    value_type = {
        settings.SettingType.STRING: "string",
        settings.SettingType.INTEGER: "integer",
        settings.SettingType.FLOAT: "number",
        settings.SettingType.BOOLEAN: "boolean",
        settings.SettingType.ENUM: "string",
    }[spec.value_type]
    return [value_type, "null"] if spec.optional else value_type


def settings_schema() -> dict[str, object]:
    """Return the normalized Settings catalog as deterministic JSON Schema."""

    properties: dict[str, object] = {}
    for spec in _specs():
        field: dict[str, object] = {
            "description": spec.description,
            "type": _schema_type(spec),
            "x-group": spec.group.value,
            "x-tier": spec.tier.value,
            "x-status": spec.status.value,
            "x-secret": spec.secret,
        }
        if spec.default is not None and not spec.secret:
            field["default"] = _json_value(spec.default)
        if spec.minimum is not None:
            field["minimum"] = spec.minimum
        if spec.maximum is not None:
            field["maximum"] = spec.maximum
        if spec.enum_type is not None:
            field["enum"] = [member.value for member in spec.enum_type]
        if spec.endpoint_kind is not None:
            field["x-endpoint-kind"] = spec.endpoint_kind
        if spec.secret:
            field["writeOnly"] = True
        if spec.replacement is not None:
            field["x-replacement"] = spec.replacement
        properties[spec.name] = field
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://thousand-faces.invalid/schemas/settings-v{settings.SETTINGS_SCHEMA_VERSION}.json",
        "title": "Thousand Faces normalized Settings",
        "type": "object",
        "additionalProperties": False,
        "x-settings-schema-version": settings.SETTINGS_SCHEMA_VERSION,
        "properties": properties,
    }


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _range_or_choices(spec: settings.SettingSpec) -> str:
    if spec.enum_type is not None:
        return ", ".join(f"`{member.value}`" for member in spec.enum_type)
    if spec.minimum is not None or spec.maximum is not None:
        return f"`{_environment_text(spec.minimum)}..{_environment_text(spec.maximum)}`"
    return "—"


def render_reference_table() -> str:
    """Render the generated Markdown catalog and named preset table."""

    lines = [
        "### 自动生成配置目录",
        "",
        "以下内容由 `scripts/settings.py` 生成；请勿手工修改本区块。generic 默认值用于",
        "`references/config.example.env`，根 `.env.example` 仅应用下列已命名 preset。",
        "",
        "#### TikHub App V3 recommended preset",
        "",
        "| 字段 | generic 默认 | App V3 推荐值 |",
        "|---|---|---|",
    ]
    for name, value in settings.TIKHUB_APP_V3_PRESET.items():
        generic = _environment_text(settings.setting_spec(name).default) or "—"
        lines.append(f"| `{name}` | `{_markdown_cell(generic)}` | `{_markdown_cell(value)}` |")
    lines.extend(
        [
            "",
            "#### Settings 字段表",
            "",
            "| 字段 | 分组 | 类型 | generic 默认 | 范围/选项 | secret | 层级 | 状态 | 说明 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for spec in _specs():
        default = "—" if spec.default is None or spec.secret else f"`{_markdown_cell(_environment_text(spec.default))}`"
        lines.append(
            "| "
            f"`{spec.name}` | `{spec.group.value}` | `{spec.value_type.value}` | {default} | "
            f"{_range_or_choices(spec)} | {'yes' if spec.secret else 'no'} | "
            f"{spec.tier.value} | {_status_label(spec)} | {_markdown_cell(spec.description)} |"
        )
    return "\n".join(lines) + "\n"


def render_configuration_document(current: str) -> str:
    """Insert or replace only the generated Settings reference block."""

    normalized = current.replace("\r\n", "\n")
    block = f"{GENERATED_TABLE_START}\n{render_reference_table()}{GENERATED_TABLE_END}"
    if GENERATED_TABLE_START in normalized or GENERATED_TABLE_END in normalized:
        if normalized.count(GENERATED_TABLE_START) != 1 or normalized.count(GENERATED_TABLE_END) != 1:
            raise ValueError("configuration document has incomplete or duplicate generated markers")
        prefix, remainder = normalized.split(GENERATED_TABLE_START, 1)
        _, suffix = remainder.split(GENERATED_TABLE_END, 1)
        return f"{prefix}{block}{suffix}"
    anchor = "## 环境变量\n"
    if anchor not in normalized:
        raise ValueError("configuration document is missing the '## 环境变量' anchor")
    return normalized.replace(anchor, f"{anchor}\n{block}\n\n", 1)


def expected_outputs(root: Path = PROJECT_ROOT) -> dict[Path, str]:
    root = Path(root)
    configuration_path = root / "references" / "configuration.md"
    if not configuration_path.is_file():
        raise ValueError(f"configuration document not found: {configuration_path}")
    return {
        _OUTPUT_PATHS[0]: render_env_template(TIKHUB_APP_V3_PROFILE),
        _OUTPUT_PATHS[1]: render_env_template(GENERIC_PROFILE),
        _OUTPUT_PATHS[2]: render_configuration_document(
            configuration_path.read_text(encoding="utf-8")
        ),
        _OUTPUT_PATHS[3]: json.dumps(settings_schema(), ensure_ascii=False, indent=2) + "\n",
    }


def find_drift(root: Path = PROJECT_ROOT) -> list[Path]:
    expected = expected_outputs(root)
    return [
        relative
        for relative, content in expected.items()
        if not (root / relative).is_file()
        or (root / relative).read_text(encoding="utf-8") != content
    ]


def write_outputs(root: Path = PROJECT_ROOT) -> Iterable[Path]:
    expected = expected_outputs(root)
    for relative, content in expected.items():
        atomic_write_text(root / relative, content)
        yield relative


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Settings templates, schema, and docs")
    parser.add_argument("--check", action="store_true", help="Report drift without writing files")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.check:
            drift = find_drift(root)
            if drift:
                print("configuration artifacts are out of date:")
                for relative in drift:
                    print(f"- {relative.as_posix()}")
                raise SystemExit(1)
            print("configuration artifacts are synchronized")
            return
        written = list(write_outputs(root))
    except ValueError as error:
        parser.error(str(error))
    for relative in written:
        print(relative.as_posix())


if __name__ == "__main__":
    main()
