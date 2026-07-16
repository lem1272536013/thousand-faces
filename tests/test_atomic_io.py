"""Crash-safe persistence contracts for generated text and JSON artifacts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import build_creator_skill
import creator_pipeline
import offline_scenarios
import provider_adapters


def test_atomic_write_json_preserves_existing_document_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io_utils

    target = tmp_path / "state.json"
    target.write_text('{"generation": 1}\n', encoding="utf-8")

    def interrupted_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        raise OSError(f"simulated interruption before replacing {destination}")

    monkeypatch.setattr(io_utils.os, "replace", interrupted_replace)

    with pytest.raises(OSError, match="simulated interruption"):
        io_utils.atomic_write_json(target, {"generation": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 1}
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_text_fsyncs_before_same_directory_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io_utils

    target = tmp_path / "artifact.txt"
    events: list[str] = []
    real_fsync = io_utils.os.fsync
    real_replace = io_utils.os.replace

    def observed_fsync(file_descriptor: int) -> None:
        events.append("fsync")
        real_fsync(file_descriptor)

    def observed_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        assert events == ["fsync"]
        assert Path(source).parent == target.parent
        assert Path(destination) == target
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(io_utils.os, "fsync", observed_fsync)
    monkeypatch.setattr(io_utils.os, "replace", observed_replace)

    io_utils.atomic_write_text(target, "完整内容\n")

    assert target.read_text(encoding="utf-8") == "完整内容\n"
    assert events == ["fsync", "replace"]


def test_atomic_write_json_emits_utf8_indented_document_with_trailing_newline(tmp_path: Path) -> None:
    import io_utils

    target = tmp_path / "nested" / "artifact.json"
    io_utils.atomic_write_json(target, {"中文": [1, 2]})

    raw = target.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "中文" in raw
    assert json.loads(raw) == {"中文": [1, 2]}


def test_all_shared_json_writers_use_the_single_atomic_implementation(project_root: Path) -> None:
    import io_utils

    assert build_creator_skill.write_json is io_utils.atomic_write_json
    assert creator_pipeline.write_json is io_utils.atomic_write_json
    assert offline_scenarios.write_json is io_utils.atomic_write_json
    assert provider_adapters.write_json is io_utils.atomic_write_json

    direct_json_write = re.compile(r"\.write_text\(\s*json\.dumps\(", re.MULTILINE)
    offenders = [
        path.relative_to(project_root).as_posix()
        for path in (project_root / "scripts").rglob("*.py")
        if direct_json_write.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
