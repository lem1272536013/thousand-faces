"""Taxonomy presets keep domain dictionaries explicit and reproducible."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

import build_creator_skill
import prepare_host_refinement
import quality_engine
import research_taxonomy
from io_utils import atomic_write_json


TECH_VIDEO_ID = "190000000000000601"


def run_args(
    run_root: Path,
    *,
    taxonomy_preset: str | None = None,
    taxonomy_version: str | None = None,
) -> argparse.Namespace:
    values: dict[str, object] = {
        "source_url": "https://share.example.invalid/taxonomy-profile",
        "project_name": "taxonomy-contract",
        "sample_count": 1,
        "metadata_fetch_limit": None,
        "run_root": str(run_root),
        "rights_basis": "unspecified",
        "retention_policy": "retain_media",
        "takedown_contact": "not_provided",
    }
    if taxonomy_preset is not None:
        values["taxonomy_preset"] = taxonomy_preset
    if taxonomy_version is not None:
        values["taxonomy_version"] = taxonomy_version
    return argparse.Namespace(**values)


def write_selected(run_dir: Path, item: dict[str, object]) -> None:
    atomic_write_json(
        run_dir / "metadata" / "selected.compact.json",
        {
            "requested_count": 1,
            "selected_count": 1,
            "selection_strategy": "published_at_desc",
            "creator_profile": {},
            "items": [item],
        },
    )


def test_default_preset_is_minimal_generic_without_technology_entities() -> None:
    preset = research_taxonomy.get_taxonomy_preset()
    serialized = json.dumps(preset.identity(), ensure_ascii=False) + json.dumps(
        dict(preset.theme_keywords),
        ensure_ascii=False,
    )

    assert isinstance(preset, research_taxonomy.TaxonomyPreset)
    assert preset.name == "generic_zh_creator"
    assert preset.version == "1.0.0"
    assert "AI / Agent / 模型" not in preset.theme_keywords
    assert "OpenAI" not in serialized
    assert preset.entity_patterns == ()


def test_registered_preset_keyword_maps_cannot_be_mutated() -> None:
    preset = research_taxonomy.get_taxonomy_preset()
    keyword_map = cast(Any, preset.theme_keywords)

    try:
        with pytest.raises(TypeError):
            keyword_map["意外写入"] = ("污染",)
    finally:
        if "意外写入" in keyword_map:
            keyword_map.pop("意外写入", None)


def test_tech_preset_preserves_legacy_technology_fixture_signals(
    tmp_path: Path,
) -> None:
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    transcript = (
        "你以为这只是普通工具？没想到我在发布会现场体验后发现安全风险。"
        "第一步打开设置，接下来输入参数并点击测试。"
        "这个实验比赛背后的机制和原理是什么？"
        "比如国内和国外案例相比，未来趋势意味着能力边界。"
        "最后建议大家不要违规，也要警惕安全风险。"
    )
    (transcript_dir / f"{TECH_VIDEO_ID}.txt").write_text(
        transcript,
        encoding="utf-8",
    )
    item = {
        "platform_video_id": TECH_VIDEO_ID,
        "artifact_id": TECH_VIDEO_ID,
        "title": (
            "OpenAI Agent 免费工具教程参加机器人比赛，"
            "我在发布会现场聊高考学习和黑客安全风险"
        ),
        "published_at": "2026-01-01T00:00:00+00:00",
        "stats": {},
    }
    preset = research_taxonomy.get_taxonomy_preset("tech_creator")

    record = prepare_host_refinement.transcript_record(
        item,
        transcript_dir,
        preset=preset,
    )
    signal = prepare_host_refinement.transcript_signal(
        record,
        transcript_dir,
        preset=preset,
    )
    entity_review = prepare_host_refinement.build_asr_entity_review(
        tmp_path,
        {"records": [record], "taxonomy": preset.identity()},
        preset=preset,
    )

    assert record["themes"] == [
        "AI / Agent / 模型",
        "工具教程 / 低门槛",
        "比赛 / 实验 / 模拟",
        "硬件 / 机器人 / 汽车",
        "现场 / 发布会 / 探访",
        "教育 / 高考 / 学习",
        "风险 / 灰区 / 安全",
    ]
    assert {
        "反常识 / 离谱设定",
        "直接任务 / 教程入口",
        "现场目击 / 发布会入口",
        "风险提示 / 灰区入口",
    }.issubset(signal["hook_type"])
    assert {
        "实验演示",
        "步骤教程",
        "机制拆解",
        "案例对照",
        "现场观察",
    }.issubset(signal["argument_mode"])
    assert {
        "script_template:experiment",
        "topic_model:low_barrier_tutorial",
        "script_template:field_report",
        "safety_boundary:risk_gray_area",
        "judgment_heuristic:mechanism_explanation",
        "topic_model:industry_context",
    }.issubset(signal["contribution_types"])
    assert {"OpenAI", "Agent"}.issubset(entity_review["known_entities"])


def test_non_technology_corpus_defaults_to_generic_without_ai_theme(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "legacy-run-without-taxonomy-fields"
    (run_dir / "metadata").mkdir(parents=True)
    (run_dir / "transcripts").mkdir()
    item = {
        "platform_video_id": "190000000000000602",
        "artifact_id": "190000000000000602",
        "title": "用 AI 帮孩子收玩具：三个可选择的步骤",
        "published_at": "2026-01-02T00:00:00+00:00",
        "stats": {},
    }
    write_selected(run_dir, item)
    (run_dir / "transcripts" / "190000000000000602.txt").write_text(
        "先描述孩子不愿收玩具的情境，再给出两个选择，最后说明适用边界。",
        encoding="utf-8",
    )

    corpus = prepare_host_refinement.build_corpus_index(run_dir)
    signals = prepare_host_refinement.build_transcript_signals(run_dir, corpus)

    assert corpus["taxonomy"] == {
        "preset": "generic_zh_creator",
        "version": "1.0.0",
    }
    assert signals["taxonomy"] == corpus["taxonomy"]
    assert all(
        "AI" not in theme and "Agent" not in theme
        for theme in corpus["records"][0]["themes"]
    )


def test_new_run_records_default_and_explicit_taxonomy_identity(
    tmp_path: Path,
) -> None:
    default_run = build_creator_skill.create_run(
        run_args(tmp_path / "default"),
        dict(build_creator_skill.DEFAULTS),
    )
    tech = research_taxonomy.get_taxonomy_preset("tech_creator")
    tech_run = build_creator_skill.create_run(
        run_args(
            tmp_path / "tech",
            taxonomy_preset=tech.name,
            taxonomy_version=tech.version,
        ),
        dict(build_creator_skill.DEFAULTS),
    )

    default_input = json.loads(
        (default_run / "input.json").read_text(encoding="utf-8")
    )
    tech_input = json.loads((tech_run / "input.json").read_text(encoding="utf-8"))

    assert default_input["taxonomy_preset"] == "generic_zh_creator"
    assert default_input["taxonomy_version"] == "1.0.0"
    assert tech_input["taxonomy_preset"] == "tech_creator"
    assert tech_input["taxonomy_version"] == tech.version
    assert research_taxonomy.resolve_run_taxonomy(tech_run) is tech


def test_refinement_manifest_contract_includes_taxonomy_name_and_version(
    tmp_path: Path,
) -> None:
    tech = research_taxonomy.get_taxonomy_preset("tech_creator")
    run_dir = build_creator_skill.create_run(
        run_args(
            tmp_path / "runs",
            taxonomy_preset=tech.name,
            taxonomy_version=tech.version,
        ),
        dict(build_creator_skill.DEFAULTS),
    )
    write_selected(
        run_dir,
        {
            "platform_video_id": TECH_VIDEO_ID,
            "artifact_id": TECH_VIDEO_ID,
            "title": "OpenAI Agent 测试",
            "stats": {},
        },
    )

    specs = quality_engine.refinement_artifact_specs(run_dir)

    assert specs["corpus_index"].config == {
        "corpus_algorithm_version": "1",
        "taxonomy_preset": "tech_creator",
        "taxonomy_version": tech.version,
    }
    assert specs["transcript_signals"].config["taxonomy_preset"] == "tech_creator"


def test_unknown_preset_and_wrong_version_have_actionable_errors(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        research_taxonomy.TaxonomyPresetError,
        match=r"unknown taxonomy preset 'missing'.*generic_zh_creator.*tech_creator",
    ):
        research_taxonomy.get_taxonomy_preset("missing")

    with pytest.raises(
        research_taxonomy.TaxonomyPresetError,
        match=r"tech_creator.*version mismatch.*requested '9.9.9'.*available '1.0.0'",
    ):
        research_taxonomy.get_taxonomy_preset("tech_creator", "9.9.9")

    run_dir = tmp_path / "tampered-run"
    run_dir.mkdir()
    atomic_write_json(
        run_dir / "input.json",
        {"taxonomy_preset": "generic_zh_creator", "taxonomy_version": "0.0.0"},
    )
    with pytest.raises(
        research_taxonomy.TaxonomyPresetError,
        match="version mismatch",
    ):
        research_taxonomy.resolve_run_taxonomy(run_dir)

    atomic_write_json(
        run_dir / "input.json",
        {"taxonomy_preset": "generic_zh_creator"},
    )
    with pytest.raises(
        research_taxonomy.TaxonomyPresetError,
        match=r"taxonomy metadata is incomplete.*preset and version",
    ):
        research_taxonomy.resolve_run_taxonomy(run_dir)


@pytest.mark.parametrize(
    "script_name",
    ["build_creator_skill.py", "run_creator_skill_build.py"],
)
@pytest.mark.parametrize(
    ("extra_args", "expected_error"),
    [
        (["--taxonomy-preset", "missing"], "unknown taxonomy preset"),
        (
            [
                "--taxonomy-preset",
                "tech_creator",
                "--taxonomy-version",
                "9.9.9",
            ],
            "version mismatch",
        ),
    ],
)
def test_public_build_clis_reject_invalid_taxonomy_before_creating_run(
    project_root: Path,
    tmp_path: Path,
    script_name: str,
    extra_args: list[str],
    expected_error: str,
) -> None:
    run_root = tmp_path / "runs"
    command = [
        sys.executable,
        str(project_root / "scripts" / script_name),
        "--source-url",
        "https://share.example.invalid/taxonomy-profile",
        "--project-name",
        "invalid-taxonomy",
        "--run-root",
        str(run_root),
        *extra_args,
    ]

    process = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert process.returncode != 0
    assert expected_error in process.stderr.lower()
    assert "available" in process.stderr.lower()
    assert not run_root.exists()
