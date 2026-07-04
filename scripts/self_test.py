#!/usr/bin/env python3
"""Offline self-test for Thousand Faces Style Skill."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    skill_root = Path(__file__).resolve().parents[1]
    script = skill_root / "scripts" / "run_creator_skill_build.py"

    with tempfile.TemporaryDirectory(prefix="creator_skill_selftest_") as tmp:
        root = Path(tmp)
        input_dir = root / "input"
        run_root = root / "runs"
        raw_metadata = input_dir / "raw.json"
        transcripts = input_dir / "transcripts"

        write_text(
            raw_metadata,
            json.dumps(
                {
                    "data": {
                        "aweme_list": [
                            {
                                "aweme_id": "1001",
                                "desc": "AI 浏览器 Agent 到底能帮普通人做什么",
                                "create_time": 1782921600,
                                "statistics": {
                                    "digg_count": 10,
                                    "collect_count": 2,
                                    "share_count": 1,
                                    "comment_count": 3,
                                },
                                "video": {"play_addr": {"url_list": ["https://example.com/video.mp4"]}},
                                "share_url": "https://v.douyin.com/example/",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        write_text(
            transcripts / "1001.txt",
            "\n".join(
                [
                    "[00:00:01] 今天我们不聊概念，直接看普通人怎么用 AI 浏览器 Agent。",
                    "[00:00:05] 你以为它只是自动点击，其实真正重要的是它能把复杂流程拆成一步一步。",
                    "[00:00:11] 如果一个工具不能帮你省掉重复劳动，那它就只是一个漂亮玩具。",
                ]
            )
            + "\n",
        )

        cmd = [
            sys.executable,
            str(script),
            "--source-url",
            "https://v.douyin.com/yXlru8nXAZg/",
            "--project-name",
            "linyi-lyi",
            "--sample-count",
            "1",
            "--raw-metadata",
            str(raw_metadata),
            "--transcripts-dir",
            str(transcripts),
            "--skip-download",
            "--skip-audio",
            "--skip-asr",
            "--skip-llm-research",
            "--run-root",
            str(run_root),
        ]
        subprocess.run(cmd, check=True)

        run_dirs = sorted((run_root / "linyi-lyi").iterdir())
        if not run_dirs:
            raise SystemExit("self-test failed: no run directory generated")
        run_dir = run_dirs[-1]
        quality = json.loads((run_dir / "logs" / "creator_quality_report.json").read_text(encoding="utf-8"))
        if not quality.get("passed"):
            raise SystemExit(f"self-test failed quality gate: {quality}")
        summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
        if not summary.get("artifacts", {}).get("skill"):
            raise SystemExit("self-test failed: skill artifact missing")
        selected = json.loads((run_dir / "metadata" / "selected.json").read_text(encoding="utf-8"))
        download_url = selected["items"][0].get("download_url")
        if download_url != "https://example.com/video.mp4":
            raise SystemExit(f"self-test failed: download_url not normalized: {download_url}")
        if selected.get("selection_strategy") != "published_at_desc":
            raise SystemExit(f"self-test failed: selection strategy missing: {selected}")

        compact = json.loads((run_dir / "metadata" / "selected.compact.json").read_text(encoding="utf-8"))
        if "raw" in json.dumps(compact, ensure_ascii=False):
            raise SystemExit("self-test failed: compact metadata leaked raw payload")
        if compact["items"][0].get("platform_video_id") != "1001":
            raise SystemExit(f"self-test failed: compact metadata malformed: {compact}")

        creator_profile = json.loads((run_dir / "metadata" / "creator_profile.json").read_text(encoding="utf-8"))
        if creator_profile.get("platform") != "douyin":
            raise SystemExit(f"self-test failed: creator profile malformed: {creator_profile}")

        if "ready_for_use" not in quality:
            raise SystemExit("self-test failed: quality report missing ready_for_use")

        prepare_script = skill_root / "scripts" / "prepare_host_refinement.py"
        subprocess.run([sys.executable, str(prepare_script), "--run-dir", str(run_dir)], check=True)
        for relative in [
            "research/host_refinement/brief.md",
            "research/host_refinement/corpus_index.json",
            "research/host_refinement/transcript_signal_matrix.md",
            "research/host_refinement/transcript_signals.json",
            "research/host_refinement/transcript_signals.md",
            "research/reviews/evidence_coverage.json",
            "research/reviews/evidence_coverage.md",
            "research/reviews/coverage_gaps.json",
            "research/reviews/coverage_gaps.md",
            "research/reviews/short_form_coverage.json",
            "research/reviews/short_form_coverage.md",
            "research/reviews/timeline_shift.json",
            "research/reviews/timeline_shift.md",
            "research/reviews/asr_entity_review.json",
            "research/reviews/asr_entity_review.md",
            "research/reviews/usage_probe.md",
            "research/reviews/evaluation_suite.md",
            "research/reviews/evaluation_suite.schema.json",
            "research/reviews/evaluation_suite.json",
            "research/reviews/reverse_identification.md",
            "research/reviews/reverse_identification.schema.json",
            "research/reviews/reverse_identification.json",
            "research/reviews/reviewer_findings.md",
            "research/reviews/refinement_audit.md",
            "skill/references/persona_model.schema.json",
            "skill/references/persona_model.json",
        ]:
            if not (run_dir / relative).exists():
                raise SystemExit(f"self-test failed: host refinement artifact missing: {relative}")

        quality_script = skill_root / "scripts" / "creator_pipeline.py"
        subprocess.run([sys.executable, str(quality_script), "quality-check", "--run-dir", str(run_dir)], check=True)
        refined_quality = json.loads((run_dir / "logs" / "creator_quality_report.json").read_text(encoding="utf-8"))
        host_checks = refined_quality.get("content_readiness", {}).get("host_refinement", {}).get("checks", {})
        if (
            not host_checks.get("brief_present")
            or not host_checks.get("corpus_index_present")
            or not host_checks.get("transcript_signals_present")
            or not host_checks.get("coverage_gaps_present")
            or "short_form_coverage_present" not in host_checks
            or "timeline_shift_present" not in host_checks
            or "asr_entity_review_present" not in host_checks
            or "evaluation_suite_filled" not in host_checks
            or "evaluation_suite_json_filled" not in host_checks
            or "reverse_identification_filled" not in host_checks
            or "reverse_identification_json_filled" not in host_checks
        ):
            raise SystemExit(f"self-test failed: host refinement checks malformed: {refined_quality}")
        if not host_checks.get("short_form_coverage_present"):
            raise SystemExit("self-test failed: short form coverage should be present after preparation")
        if not host_checks.get("timeline_shift_present"):
            raise SystemExit("self-test failed: timeline shift should be present after preparation")
        if not host_checks.get("asr_entity_review_present"):
            raise SystemExit("self-test failed: ASR entity review should be present after preparation")
        if host_checks.get("refinement_audit_filled"):
            raise SystemExit("self-test failed: blank refinement audit should not pass")
        if host_checks.get("usage_probe_filled"):
            raise SystemExit("self-test failed: blank usage probe should not pass")
        if host_checks.get("evaluation_suite_filled"):
            raise SystemExit("self-test failed: blank evaluation suite should not pass")
        if host_checks.get("evaluation_suite_json_filled"):
            raise SystemExit("self-test failed: blank evaluation suite json should not pass")
        if host_checks.get("reverse_identification_filled"):
            raise SystemExit("self-test failed: blank reverse identification should not pass")
        if host_checks.get("reverse_identification_json_filled"):
            raise SystemExit("self-test failed: blank reverse identification json should not pass")
        if host_checks.get("reviewer_findings_filled"):
            raise SystemExit("self-test failed: blank reviewer findings should not pass")
        if refined_quality.get("ready_for_use"):
            raise SystemExit("self-test failed: draft with blank audit should not be ready_for_use")
        persona_checks = refined_quality.get("content_readiness", {}).get("persona_model", {}).get("checks", {})
        if not persona_checks.get("schema_file_present") or not persona_checks.get("model_file_present"):
            raise SystemExit(f"self-test failed: persona model checks missing: {refined_quality}")
        if persona_checks.get("not_template"):
            raise SystemExit("self-test failed: draft persona model should remain template")

        # Copy nothing out; the temp directory is intentionally disposable.
        shutil.rmtree(root, ignore_errors=True)

    print("offline self-test passed")


if __name__ == "__main__":
    main()
