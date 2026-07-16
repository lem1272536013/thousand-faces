"""Encoding diagnostics must detect corruption without penalizing normal text."""

from __future__ import annotations

import json
from pathlib import Path

import content_safety
import creator_pipeline


def test_replacement_character_is_a_blocker() -> None:
    report = content_safety.analyze_text_encoding("正常文字�后续内容")

    assert report["passed"] is False
    assert report["replacement_character_count"] == 1
    assert report["checks"]["no_replacement_characters"] is False


def test_invalid_utf8_is_reported_without_copying_bytes_or_paths() -> None:
    report = content_safety.analyze_encoding_documents(
        {"skill/references/persona.md": b"valid-prefix\xffprivate-tail"}
    )

    assert report["passed"] is False
    assert report["files"] == [
        {
            "path": "skill/references/persona.md",
            "passed": False,
            "checks": {
                "utf8_decodable": False,
                "no_replacement_characters": False,
                "question_mark_density_acceptable": False,
            },
            "error": "invalid_utf8",
        }
    ]
    serialized = json.dumps(report, ensure_ascii=False)
    assert "private-tail" not in serialized
    assert "\\xff" not in serialized


def test_abnormal_question_mark_density_is_blocked() -> None:
    text = "这是一段损坏文本" + "????????????" + "后续仍然无法辨认" + "?" * 8

    report = content_safety.analyze_text_encoding(text)

    assert report["passed"] is False
    assert report["question_mark_count"] == 20
    assert report["question_mark_density"] > 0.1
    assert report["checks"]["question_mark_density_acceptable"] is False


def test_reasonable_questions_are_not_mojibake() -> None:
    text = (
        "为什么要先验证证据？因为结论需要可追溯。"
        "什么时候应该降低置信度？当样本不足或相互冲突时。"
        "如何处理边界请求？明确拒绝冒充，再提供安全替代方案。"
        "这个方法适合所有场景吗？不适合，仍要结合具体语料判断。"
    )

    report = content_safety.analyze_text_encoding(text)

    assert report["passed"] is True
    assert report["question_mark_count"] == 4
    assert creator_pipeline.has_mojibake(text) is False


def test_question_mark_operators_inside_code_fence_are_ignored() -> None:
    code = "\n".join(
        ["value = left ?? right  # nullable fallback ?????" for _ in range(20)]
    )
    text = f"# Example\n\n正常说明文本。\n\n```csharp\n{code}\n```\n"

    report = content_safety.analyze_text_encoding(text)

    assert report["passed"] is True
    assert report["question_mark_count"] == 0
    assert creator_pipeline.has_mojibake(text) is False


def test_question_mark_operators_inside_crlf_code_fence_are_ignored() -> None:
    code = "\r\n".join(
        ["value = left ?? right  # nullable fallback ?????" for _ in range(20)]
    )
    text = f"# Example\r\n\r\n正常说明文本。\r\n\r\n```csharp\r\n{code}\r\n```\r\n"

    report = content_safety.analyze_text_encoding(text)

    assert report["passed"] is True
    assert report["question_mark_count"] == 0


def test_mismatched_fence_markers_cannot_hide_question_mark_corruption() -> None:
    text = "正常说明。\n\n```text\n" + ("????????????\n" * 10) + "~~~\n"

    report = content_safety.analyze_text_encoding(text)

    assert report["passed"] is False
    assert report["question_mark_count"] == 120


def test_longer_matching_closing_fence_is_valid_commonmark_code() -> None:
    text = "正常说明。\n\n```text\n" + ("????????????\n" * 10) + "````\n"

    report = content_safety.analyze_text_encoding(text)

    assert report["passed"] is True
    assert report["question_mark_count"] == 0


def test_encoding_document_report_uses_relative_identity_only(tmp_path: Path) -> None:
    report = content_safety.analyze_encoding_documents(
        {"skill/SKILL.md": "正常内容？可以。".encode("utf-8")}
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["passed"] is True
    assert str(tmp_path) not in serialized
    assert "正常内容" not in serialized


def test_run_content_safety_strictly_reads_utf8_without_leaking_content(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    target = run_dir / "skill" / "SKILL.md"
    transcript = run_dir / "transcripts" / "video-001.txt"
    target.parent.mkdir(parents=True)
    transcript.parent.mkdir(parents=True)
    target.write_bytes(b"valid-prefix\xffPRIVATE_ENCODING_CONTENT")
    transcript.write_text("正常的当前转写文本。" * 20, encoding="utf-8")

    report = content_safety.evaluate_run_content_safety(
        run_dir,
        target_paths=[target],
        transcript_paths=[transcript],
    )

    assert report["passed"] is False
    assert report["checks"]["encoding_valid"] is False
    assert report["encoding"]["failed_files"] == ["skill/SKILL.md"]
    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE_ENCODING_CONTENT" not in serialized
    assert str(run_dir) not in serialized
