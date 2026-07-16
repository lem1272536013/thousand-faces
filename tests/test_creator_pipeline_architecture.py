from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import asr_parsers
import creator_pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = PROJECT_ROOT / "scripts" / "creator_pipeline.py"
OWNER_MODULES = (
    "creator_metadata",
    "creator_media",
    "skill_builder",
    "creator_quality",
)


def test_pipeline_responsibilities_have_explicit_owner_modules() -> None:
    metadata = importlib.import_module("creator_metadata")
    media = importlib.import_module("creator_media")
    builder = importlib.import_module("skill_builder")
    quality = importlib.import_module("creator_quality")

    assert creator_pipeline.normalize_metadata is metadata.normalize_metadata
    assert creator_pipeline.select_samples is metadata.select_samples
    assert creator_pipeline.compact_metadata_item is metadata.compact_metadata_item

    assert creator_pipeline.download_one is media.download_one
    assert creator_pipeline.ffmpeg_version is media.ffmpeg_version
    assert creator_pipeline.asr_json_to_transcript is media.asr_json_to_transcript
    assert creator_pipeline.summarize_transcripts is media.summarize_transcripts
    assert media.parse_asr_response is asr_parsers.parse_asr_response

    assert creator_pipeline.build_creator_skill is builder.build_creator_skill
    assert creator_pipeline.host_refinement_stats is quality.host_refinement_stats
    assert creator_pipeline.compute_persona_model_stats is quality.compute_persona_model_stats
    assert creator_pipeline.creator_content_readiness is quality.creator_content_readiness


def test_owner_modules_do_not_import_the_compatibility_facade() -> None:
    for module_name in OWNER_MODULES:
        path = PROJECT_ROOT / "scripts" / f"{module_name}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert "creator_pipeline" not in imported


def test_creator_pipeline_is_a_thin_cli_and_compatibility_facade() -> None:
    source = PIPELINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    compatibility_wrappers = {
        "download_videos",
        "extract_audio",
        "creator_quality_check",
    }
    workflow_and_cli = {
        "read_json",
        "raise_workflow_state_error",
        "update_workflow_state",
        "write_run_summary",
        "command_normalize_metadata",
        "command_select_samples",
        "command_download_videos",
        "command_extract_audio",
        "command_asr_json_to_transcript",
        "command_summarize_transcripts",
        "command_build_skill",
        "command_quality_check",
        "command_run_summary",
        "command_inspect_run",
        "build_parser",
        "main",
    }
    assert functions <= compatibility_wrappers | workflow_and_cli
    assert len(source.splitlines()) <= 700


def test_creator_pipeline_keeps_the_public_cli_surface() -> None:
    expected_options = {
        "normalize-metadata": {"--input", "--output"},
        "select-samples": {"--input", "--output", "--sample-count"},
        "download-videos": {"--input", "--output-dir", "--logs-dir"},
        "extract-audio": {"--video-dir", "--audio-dir"},
        "asr-json-to-transcript": {"--input", "--output"},
        "summarize-transcripts": {"--transcripts-dir", "--output-dir"},
        "build-skill": {"--run-dir", "--project-name"},
        "quality-check": {"--run-dir", "--json", "--report-only"},
        "run-summary": {"--run-dir"},
        "inspect-run": {"--run-dir", "--json"},
    }

    root_help = subprocess.run(
        [sys.executable, str(PIPELINE_PATH), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert root_help.returncode == 0
    assert "--env" in root_help.stdout
    for command, options in expected_options.items():
        assert command in root_help.stdout
        result = subprocess.run(
            [sys.executable, str(PIPELINE_PATH), command, "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert result.returncode == 0
        assert options <= set(result.stdout.split())
