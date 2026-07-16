"""Run directory identity and non-overwrite contracts."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

import build_creator_skill


RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{9}Z-[0-9a-f]{32}$")


def run_args(run_root: Path, project_name: str = "normal-project") -> argparse.Namespace:
    return argparse.Namespace(
        source_url="https://share.example.invalid/profile",
        project_name=project_name,
        sample_count=2,
        metadata_fetch_limit=None,
        run_root=str(run_root),
    )


def test_create_run_generates_1000_unique_directories(run_root: Path) -> None:
    config = dict(build_creator_skill.DEFAULTS)

    created = {build_creator_skill.create_run(run_args(run_root), config) for _ in range(1000)}

    assert len(created) == 1000
    assert all(path.is_dir() for path in created)
    assert all(RUN_ID_PATTERN.fullmatch(path.name) for path in created)


def test_create_run_retries_a_generated_id_collision(
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = iter(["fixed-run-id", "fixed-run-id", "replacement-run-id"])
    monkeypatch.setattr(build_creator_skill, "now_id", lambda: next(generated))
    config = dict(build_creator_skill.DEFAULTS)

    first = build_creator_skill.create_run(run_args(run_root), config)
    second = build_creator_skill.create_run(run_args(run_root), config)

    assert first.name == "fixed-run-id"
    assert second.name == "replacement-run-id"
    assert first != second


def test_create_run_never_reuses_an_existing_directory(
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_creator_skill, "now_id", lambda: "always-collides")
    config = dict(build_creator_skill.DEFAULTS)
    first = build_creator_skill.create_run(run_args(run_root), config)
    marker = first / "user-marker.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unique run directory"):
        build_creator_skill.create_run(run_args(run_root), config)

    assert marker.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    ("project_name", "expected_slug"),
    [("Normal Project", "normal-project"), ("中文项目", "中文项目")],
)
def test_normal_and_chinese_project_names_create_expected_slug(
    run_root: Path,
    project_name: str,
    expected_slug: str,
) -> None:
    path = build_creator_skill.create_run(
        run_args(run_root / expected_slug, project_name),
        dict(build_creator_skill.DEFAULTS),
    )

    assert path.parent.name == expected_slug
    assert RUN_ID_PATTERN.fullmatch(path.name)
