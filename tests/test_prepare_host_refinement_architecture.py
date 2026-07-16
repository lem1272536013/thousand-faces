from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import corpus
import prepare_host_refinement
import quality_engine
import research_taxonomy
import text_analysis
import topic_discovery


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARE_PATH = PROJECT_ROOT / "scripts" / "prepare_host_refinement.py"
OWNER_MODULES = (
    "refinement_common",
    "refinement_coverage",
    "refinement_signals",
    "refinement_schemas",
    "refinement_templates",
)


def test_refinement_responsibilities_have_explicit_owner_modules() -> None:
    common = importlib.import_module("refinement_common")
    coverage = importlib.import_module("refinement_coverage")
    signals = importlib.import_module("refinement_signals")
    schemas = importlib.import_module("refinement_schemas")
    templates = importlib.import_module("refinement_templates")

    assert prepare_host_refinement.markdown_data_inline is common.markdown_data_inline
    assert prepare_host_refinement.render_untrusted_markdown_block is (
        common.render_untrusted_markdown_block
    )
    assert prepare_host_refinement.parse_evidence_index is coverage.parse_evidence_index
    assert prepare_host_refinement.build_evidence_coverage is coverage.build_evidence_coverage
    assert prepare_host_refinement.build_coverage_gaps is coverage.build_coverage_gaps
    assert prepare_host_refinement.build_short_form_coverage is coverage.build_short_form_coverage
    assert prepare_host_refinement.build_timeline_shift is coverage.build_timeline_shift
    assert prepare_host_refinement.build_corpus_index is signals.build_corpus_index
    assert prepare_host_refinement.build_topic_candidates is signals.build_topic_candidates
    assert prepare_host_refinement.build_transcript_signals is signals.build_transcript_signals
    assert prepare_host_refinement.build_signal_matrix is signals.build_signal_matrix
    assert prepare_host_refinement.build_asr_entity_review is signals.build_asr_entity_review
    assert prepare_host_refinement.build_brief is templates.build_brief
    assert prepare_host_refinement.build_persona_model_schema is (
        schemas.build_persona_model_schema
    )
    assert prepare_host_refinement.build_evaluation_suite_schema is (
        schemas.build_evaluation_suite_schema
    )
    assert prepare_host_refinement.build_reverse_identification_schema is (
        schemas.build_reverse_identification_schema
    )

    assert signals.corpus is corpus
    assert signals.research_taxonomy is research_taxonomy
    assert signals.text_analysis is text_analysis
    assert signals.topic_discovery is topic_discovery
    assert prepare_host_refinement.quality_engine is quality_engine


def test_refinement_owner_modules_do_not_import_the_cli_facade() -> None:
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
        assert "prepare_host_refinement" not in imported


def test_prepare_file_is_thin_orchestration_without_embedded_templates() -> None:
    source = PREPARE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    long_strings = [
        value.value
        for value in ast.walk(tree)
        if isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and len(value.value) >= 500
    ]

    assert functions == {"main"}
    assert not long_strings
    assert len(source.splitlines()) <= 500


def test_prepare_cli_keeps_its_public_options() -> None:
    result = subprocess.run(
        [sys.executable, str(PREPARE_PATH), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    for option in ("--run-dir", "--top-count", "--excerpt-count", "--excerpt-chars"):
        assert option in result.stdout


def test_quality_derivation_does_not_depend_on_the_cli_facade() -> None:
    source = (PROJECT_ROOT / "scripts" / "quality_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    compute = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "compute_current_derivations"
    )
    imported = {
        alias.name
        for node in ast.walk(compute)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "prepare_host_refinement" not in imported
    assert {"refinement_coverage", "refinement_signals"} <= imported


def test_evidence_rebuild_does_not_depend_on_the_cli_facade() -> None:
    source = (PROJECT_ROOT / "scripts" / "evidence_model.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "prepare_host_refinement" not in imported
    assert {"refinement_coverage", "refinement_signals"} <= imported
