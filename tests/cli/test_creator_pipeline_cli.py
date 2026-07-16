"""Compatibility contracts for the public creator_pipeline command surface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import creator_pipeline
from offline_scenarios import offline_subprocess_env


COMMAND_CASES = {
    "normalize-metadata": (
        ["--input", "input.json", "--output", "normalized.json"],
        {"--input", "--output"},
    ),
    "select-samples": (
        ["--input", "normalized.json", "--output", "selected.json", "--sample-count", "1"],
        {"--input", "--output", "--sample-count"},
    ),
    "download-videos": (
        ["--input", "selected.json", "--output-dir", "videos", "--logs-dir", "logs"],
        {"--input", "--output-dir", "--logs-dir"},
    ),
    "extract-audio": (
        ["--video-dir", "videos", "--audio-dir", "audio"],
        {"--video-dir", "--audio-dir"},
    ),
    "asr-json-to-transcript": (
        ["--input", "asr.json", "--output", "transcript.txt"],
        {"--input", "--output"},
    ),
    "summarize-transcripts": (
        ["--transcripts-dir", "transcripts", "--output-dir", "research"],
        {"--transcripts-dir", "--output-dir"},
    ),
    "build-skill": (
        ["--run-dir", "run", "--project-name", "compatibility-test"],
        {"--run-dir", "--project-name"},
    ),
    "quality-check": (
        ["--run-dir", "run", "--json", "--report-only"],
        {"--run-dir", "--json", "--report-only"},
    ),
    "run-summary": (["--run-dir", "run"], {"--run-dir"}),
    "inspect-run": (
        ["--run-dir", "run", "--json"],
        {"--run-dir", "--json"},
    ),
}


def test_root_and_every_subcommand_help_are_stable(
    project_root: Path,
) -> None:
    pipeline = project_root / "scripts" / "creator_pipeline.py"
    root_help = subprocess.run(
        [sys.executable, str(pipeline), "--help"],
        cwd=project_root,
        env=offline_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert root_help.returncode == 0
    assert "--env" in root_help.stdout
    for command, (_arguments, expected_options) in COMMAND_CASES.items():
        assert command in root_help.stdout
        help_result = subprocess.run(
            [sys.executable, str(pipeline), command, "--help"],
            cwd=project_root,
            env=offline_subprocess_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert help_result.returncode == 0
        assert expected_options <= set(help_result.stdout.split())


@pytest.mark.parametrize(("command", "case"), COMMAND_CASES.items())
def test_every_subcommand_accepts_its_documented_arguments(
    command: str,
    case: tuple[list[str], set[str]],
) -> None:
    arguments, _expected_options = case

    parsed = creator_pipeline.build_parser().parse_args([command, *arguments])

    assert parsed.command == command
    assert callable(parsed.func)


@pytest.mark.parametrize("command", COMMAND_CASES)
def test_every_subcommand_rejects_missing_required_arguments_with_exit_2(
    command: str,
) -> None:
    with pytest.raises(SystemExit) as error:
        creator_pipeline.build_parser().parse_args([command])

    assert error.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["unknown-command"],
        ["select-samples", "--input", "in.json", "--output", "out.json", "--sample-count", "0"],
        ["inspect-run", "--run-dir", "run", "--unknown-option"],
    ],
)
def test_illegal_arguments_have_stable_parser_exit_code(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        creator_pipeline.build_parser().parse_args(arguments)

    assert error.value.code == 2
