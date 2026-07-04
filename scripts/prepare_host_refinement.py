#!/usr/bin/env python3
"""Prepare a compact research brief for host-agent Creator Skill refinement."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


THEME_KEYWORDS = {
    "AI / Agent / 模型": [
        "AI",
        "Agent",
        "智能体",
        "模型",
        "DeepSeek",
        "豆包",
        "Kimi",
        "Gemini",
        "Grok",
        "OpenAI",
        "Codex",
        "Claude",
    ],
    "工具教程 / 低门槛": ["教程", "免费", "上手", "工具", "PPT", "学习", "API", "中转站", "提示词", "vibecoding"],
    "比赛 / 实验 / 模拟": ["比赛", "竞技", "大逃杀", "测评", "挑战", "预测", "外挂", "测试", "PK", "大战"],
    "硬件 / 机器人 / 汽车": ["机器人", "手机", "汽车", "眼镜", "iPhone", "Siri", "华为", "宇树", "硬件"],
    "现场 / 发布会 / 探访": ["现场", "发布会", "I/O", "迪士尼", "探访", "谷歌", "香港", "实验室"],
    "教育 / 高考 / 学习": ["高考", "志愿", "作文", "数学", "学习", "学生", "论文", "毕业"],
    "风险 / 灰区 / 安全": ["黑客", "注入", "安全", "举报", "灰色", "中转站", "攻击", "造假", "跑路"],
}

HOOK_KEYWORDS = {
    "反常识 / 离谱设定": ["你以为", "没想到", "离谱", "疯了", "炸了", "震惊", "竟然", "到底"],
    "直接任务 / 教程入口": ["怎么", "如何", "教程", "上手", "一步", "免费", "工具", "普通人"],
    "现场目击 / 发布会入口": ["现场", "发布会", "我在", "探访", "体验", "刚刚", "今天"],
    "风险提示 / 灰区入口": ["风险", "黑客", "攻击", "注入", "安全", "举报", "灰色", "跑路"],
}

ARGUMENT_KEYWORDS = {
    "实验演示": ["实验", "测试", "测评", "比赛", "PK", "挑战", "规则"],
    "步骤教程": ["第一步", "第二步", "接下来", "打开", "输入", "点击", "设置"],
    "机制拆解": ["原理", "机制", "为什么", "本质", "逻辑", "背后", "拆解"],
    "案例对照": ["比如", "案例", "相比", "对比", "以前", "现在", "国外", "国内"],
    "现场观察": ["现场", "看到", "体验", "发布会", "展台", "工作人员"],
}

ENDING_KEYWORDS = {
    "能力边界判断": ["说明", "证明", "边界", "能力", "短板", "局限"],
    "行动建议": ["建议", "可以试试", "不要", "最好", "记住", "收藏"],
    "趋势判断": ["未来", "趋势", "接下来", "会变成", "意味着"],
    "风险收束": ["风险", "警惕", "安全", "别碰", "违规", "灰色"],
}

JUDGMENT_KEYWORDS = [
    "普通人",
    "门槛",
    "效率",
    "成本",
    "风险",
    "安全",
    "能力",
    "边界",
    "体验",
    "生态",
    "平台",
    "开源",
]

KNOWN_ENTITY_PATTERNS = [
    "OpenAI",
    "Claude",
    "Gemini",
    "Kimi",
    "DeepSeek",
    "Codex",
    "Qoder",
    "TRAE",
    "Grok",
    "Google I/O",
    "Vision Pro",
    "Seedance",
    "GPT",
    "Agent",
    "API",
    "Steam",
    "eSIM",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def item_score(item: dict) -> int:
    stats = item.get("stats") or {}
    return int(stats.get("like") or 0) + 3 * int(stats.get("favorite") or 0) + 4 * int(stats.get("share") or 0) + 2 * int(stats.get("comment") or 0)


def transcript_excerpt(path: Path, chars: int) -> str:
    if not path.exists():
        return "_转写稿缺失_"
    text = clean_text(path.read_text(encoding="utf-8-sig", errors="replace"))
    if len(text) <= chars:
        return text
    head = text[: chars // 3]
    mid_start = max(0, len(text) // 2 - chars // 6)
    mid = text[mid_start : mid_start + chars // 3]
    tail = text[-chars // 3 :]
    return "\n\n".join(
        [
            f"开头：{head}",
            f"中段：{mid}",
            f"结尾：{tail}",
        ]
    )


def count_table_row(path: Path) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"(?m)^\|[^|\n]+\|", text))


def covered_video_ids(run_dir: Path, corpus_index: dict) -> set[str]:
    evidence_path = run_dir / "skill" / "references" / "evidence_index.md"
    if not evidence_path.exists():
        return set()
    evidence_text = evidence_path.read_text(encoding="utf-8", errors="replace")
    ids = {record["video_id"] for record in corpus_index.get("records", [])}
    return {video_id for video_id in ids if video_id and video_id in evidence_text}


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def coverage_bucket(ids: list[str], covered: set[str]) -> dict:
    unique_ids = [video_id for video_id in dict.fromkeys(ids) if video_id]
    covered_ids = [video_id for video_id in unique_ids if video_id in covered]
    return {
        "total": len(unique_ids),
        "covered": len(covered_ids),
        "ratio": ratio(len(covered_ids), len(unique_ids)),
        "covered_ids": covered_ids,
        "missing_ids": [video_id for video_id in unique_ids if video_id not in covered],
    }


def build_evidence_coverage(run_dir: Path, corpus_index: dict, signal_payload: dict) -> dict:
    records = corpus_index.get("records", [])
    covered = covered_video_ids(run_dir, corpus_index)
    by_score = sorted(records, key=lambda item: item["weighted_score"], reverse=True)
    by_length = sorted(records, key=lambda item: item["transcript_chars"], reverse=True)
    short_ids = [record["video_id"] for record in records if 0 < record["transcript_chars"] < 800]
    boundary_ids = [signal["video_id"] for signal in signal_payload["signals"] if signal["boundary_or_risk_sample"]]
    theme_buckets = {
        theme: [record["video_id"] for record in records if theme in (record.get("themes") or [])]
        for theme in THEME_KEYWORDS
    }
    theme_coverage = {theme: coverage_bucket(ids, covered) for theme, ids in theme_buckets.items() if ids}
    buckets = {
        "top_interaction": coverage_bucket([record["video_id"] for record in by_score[:10]], covered),
        "top_transcript_length": coverage_bucket([record["video_id"] for record in by_length[:10]], covered),
        "short_transcripts": coverage_bucket(short_ids[:10], covered),
        "boundary_or_risk": coverage_bucket(boundary_ids[:10], covered),
    }
    theme_ratio = ratio(
        sum(1 for bucket in theme_coverage.values() if bucket["covered"] > 0),
        len(theme_coverage),
    )
    bucket_ratios = [bucket["ratio"] for bucket in buckets.values()]
    bucket_ratios.append(theme_ratio)
    return {
        "covered_video_count": len(covered),
        "covered_video_ids": sorted(covered),
        "total_video_count": len(records),
        "buckets": buckets,
        "theme_coverage": theme_coverage,
        "theme_cluster_ratio": theme_ratio,
        "overall_score": round(sum(bucket_ratios) / len(bucket_ratios), 4) if bucket_ratios else 0.0,
    }


def build_evidence_coverage_markdown(coverage: dict) -> str:
    lines = [
        "# Evidence Coverage",
        "",
        "该文件由脚本根据 `skill/references/evidence_index.md` 中出现的视频 ID 生成，用于检查证据是否覆盖全量 ASR 语料的关键区域。",
        "",
        f"- Covered video count: {coverage['covered_video_count']} / {coverage['total_video_count']}",
        f"- Theme cluster ratio: {coverage['theme_cluster_ratio']}",
        f"- Overall score: {coverage['overall_score']}",
        "",
        "## Buckets",
        "",
        "| Bucket | Covered | Total | Ratio | Missing IDs |",
        "|---|---:|---:|---:|---|",
    ]
    for name, bucket in coverage["buckets"].items():
        lines.append(
            f"| {name} | {bucket['covered']} | {bucket['total']} | {bucket['ratio']} | {', '.join(bucket['missing_ids'][:10])} |"
        )
    lines.extend(["", "## Theme Coverage", ""])
    lines.append("| Theme | Covered | Total | Ratio | Missing IDs |")
    lines.append("|---|---:|---:|---:|---|")
    for theme, bucket in coverage["theme_coverage"].items():
        lines.append(
            f"| {theme} | {bucket['covered']} | {bucket['total']} | {bucket['ratio']} | {', '.join(bucket['missing_ids'][:10])} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def build_coverage_gaps(corpus_index: dict, signal_payload: dict, coverage: dict) -> dict:
    records = corpus_index.get("records", [])
    record_by_id = {record["video_id"]: record for record in records}
    signal_by_id = {signal["video_id"]: signal for signal in signal_payload.get("signals", [])}
    recommendations: dict[str, dict[str, Any]] = {}

    def add(video_id: str, reason: str, priority: int) -> None:
        if not video_id:
            return
        record = record_by_id.get(video_id, {})
        signal = signal_by_id.get(video_id, {})
        item = recommendations.setdefault(
            video_id,
            {
                "video_id": video_id,
                "priority": priority,
                "reasons": [],
                "title": record.get("title", ""),
                "published_at": record.get("published_at", ""),
                "weighted_score": record.get("weighted_score", 0),
                "transcript_chars": record.get("transcript_chars", 0),
                "themes": record.get("themes", []),
                "opener": signal.get("opener", ""),
                "ending": signal.get("ending", ""),
            },
        )
        item["priority"] = min(item["priority"], priority)
        if reason not in item["reasons"]:
            item["reasons"].append(reason)

    for bucket_name, bucket in coverage.get("buckets", {}).items():
        priority = 1 if bucket_name in {"top_interaction", "top_transcript_length"} else 2
        for video_id in bucket.get("missing_ids", [])[:10]:
            add(video_id, f"missing from {bucket_name} evidence bucket", priority)

    for theme, bucket in coverage.get("theme_coverage", {}).items():
        if bucket.get("covered", 0) == 0:
            for video_id in bucket.get("missing_ids", [])[:3]:
                add(video_id, f"theme cluster has no evidence: {theme}", 1)
        elif bucket.get("ratio", 0) < 0.3:
            for video_id in bucket.get("missing_ids", [])[:2]:
                add(video_id, f"theme cluster under-covered: {theme}", 3)

    top_items = sorted(
        recommendations.values(),
        key=lambda item: (item["priority"], -int(item.get("weighted_score") or 0), -int(item.get("transcript_chars") or 0)),
    )
    return {
        "status": "generated",
        "recommendation_count": len(top_items),
        "top_recommendations": top_items[:20],
        "summary": {
            "overall_score": coverage.get("overall_score", 0),
            "covered_video_count": coverage.get("covered_video_count", 0),
            "total_video_count": coverage.get("total_video_count", 0),
            "theme_cluster_ratio": coverage.get("theme_cluster_ratio", 0),
        },
        "usage": "Read these videos before rewriting persona/topic/script files. High priority items should either be cited in evidence_index.md or explicitly rejected as weak/noisy evidence.",
    }


def build_coverage_gaps_markdown(payload: dict) -> str:
    lines = [
        "# Coverage Gaps",
        "",
        "该文件列出宿主 agent 下一轮最应该补读和补证据的视频。高优先级视频必须进入 `evidence_index.md`，或在 raw notes 中说明为什么不采用。",
        "",
        f"- Overall score: {payload['summary']['overall_score']}",
        f"- Covered videos: {payload['summary']['covered_video_count']} / {payload['summary']['total_video_count']}",
        f"- Recommendation count: {payload['recommendation_count']}",
        "",
        "| Priority | Video ID | Reasons | Score | Chars | Title |",
        "|---:|---|---|---:|---:|---|",
    ]
    for item in payload.get("top_recommendations", []):
        reasons = "; ".join(item.get("reasons", []))
        title = str(item.get("title", "")).replace("|", " ")
        lines.append(
            f"| {item.get('priority')} | {item.get('video_id')} | {reasons} | {item.get('weighted_score')} | {item.get('transcript_chars')} | {title} |"
        )
    lines.extend(
        [
            "",
            "## 使用要求",
            "",
            "- 优先补读 priority=1 的视频。",
            "- 每个被采用的视频要进入 `skill/references/evidence_index.md`。",
            "- 不采用的视频要在 `research/raw/*` 里说明噪声、重复或证据弱的原因。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_short_form_coverage(corpus_index: dict, signal_payload: dict) -> dict:
    records_by_id = {record["video_id"]: record for record in corpus_index.get("records", [])}
    signal_by_id = {signal["video_id"]: signal for signal in signal_payload.get("signals", [])}
    short_ids = [
        record["video_id"]
        for record in corpus_index.get("records", [])
        if 0 < record.get("transcript_chars", 0) < 800
    ]
    buckets = Counter()
    rows = []
    for video_id in short_ids:
        record = records_by_id[video_id]
        signal = signal_by_id.get(video_id, {})
        hook = ", ".join(signal.get("hook_type") or [])
        ending = ", ".join(signal.get("ending_mode") or [])
        contribution = ", ".join(signal.get("contribution_types") or [])
        for label in signal.get("hook_type") or []:
            buckets[f"hook:{label}"] += 1
        for label in signal.get("ending_mode") or []:
            buckets[f"ending:{label}"] += 1
        rows.append(
            {
                "video_id": video_id,
                "title": record.get("title", ""),
                "chars": record.get("transcript_chars", 0),
                "score": record.get("weighted_score", 0),
                "hook_type": hook,
                "ending_mode": ending,
                "contribution_types": contribution,
                "evidence_strength": "weak" if record.get("transcript_chars", 0) < 300 else "medium",
            }
        )
    return {
        "short_form_count": len(short_ids),
        "analyzed_count": len(rows),
        "pattern_counts": dict(buckets.most_common()),
        "records": rows,
        "note": "Short-form records are useful for hook and ending patterns, but should usually be weak evidence for deep persona claims.",
    }


def build_short_form_coverage_markdown(payload: dict) -> str:
    lines = [
        "# Short Form Coverage",
        "",
        "该文件专门检查短转写样本。短样本常能支撑 hook、标题和快速收束，但通常不足以单独支撑深层人格判断。",
        "",
        f"- Short form count: {payload['short_form_count']}",
        f"- Analyzed count: {payload['analyzed_count']}",
        "",
        "## Pattern Counts",
        "",
    ]
    for label, count in payload["pattern_counts"].items():
        lines.append(f"- {label}: {count}")
    lines.extend(["", "## Short Records", ""])
    lines.append("| Video ID | Chars | Score | Evidence | Hook | Ending | Contribution | Title |")
    lines.append("|---|---:|---:|---|---|---|---|---|")
    for record in payload["records"]:
        lines.append(
            "| {video_id} | {chars} | {score} | {evidence} | {hook} | {ending} | {contribution} | {title} |".format(
                video_id=record["video_id"],
                chars=record["chars"],
                score=record["score"],
                evidence=record["evidence_strength"],
                hook=record["hook_type"].replace("|", "/"),
                ending=record["ending_mode"].replace("|", "/"),
                contribution=record["contribution_types"].replace("|", "/"),
                title=record["title"].replace("|", "/"),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def build_timeline_shift(corpus_index: dict, signal_payload: dict) -> dict:
    records = sorted(corpus_index.get("records", []), key=lambda item: str(item.get("published_at", "")))
    if not records:
        return {"periods": [], "shift_score": 0.0, "notes": []}
    signal_by_id = {signal["video_id"]: signal for signal in signal_payload.get("signals", [])}
    period_count = min(3, len(records))
    periods = []
    for index in range(period_count):
        start = round(index * len(records) / period_count)
        end = round((index + 1) * len(records) / period_count)
        chunk = records[start:end]
        theme_counts = Counter(theme for record in chunk for theme in record.get("themes", []))
        hook_counts = Counter(
            label
            for record in chunk
            for label in (signal_by_id.get(record["video_id"], {}).get("hook_type") or [])
        )
        contribution_counts = Counter(
            label
            for record in chunk
            for label in (signal_by_id.get(record["video_id"], {}).get("contribution_types") or [])
        )
        periods.append(
            {
                "name": ["early", "middle", "recent"][index] if period_count == 3 else f"period_{index + 1}",
                "start_date": str(chunk[0].get("published_at", ""))[:10],
                "end_date": str(chunk[-1].get("published_at", ""))[:10],
                "count": len(chunk),
                "theme_counts": dict(theme_counts.most_common()),
                "hook_counts": dict(hook_counts.most_common()),
                "contribution_counts": dict(contribution_counts.most_common()),
                "top_video_ids": [record["video_id"] for record in sorted(chunk, key=lambda item: item["weighted_score"], reverse=True)[:5]],
            }
        )
    first_terms = set(periods[0].get("theme_counts", {}).keys()) | set(periods[0].get("contribution_counts", {}).keys())
    last_terms = set(periods[-1].get("theme_counts", {}).keys()) | set(periods[-1].get("contribution_counts", {}).keys())
    overlap = len(first_terms & last_terms)
    union = len(first_terms | last_terms)
    shift_score = round(1 - ratio(overlap, union), 4) if union else 0.0
    return {
        "periods": periods,
        "shift_score": shift_score,
        "notes": [
            "Higher shift_score means stronger topic or contribution drift across periods.",
            "Use this to avoid treating a recent platform trend as permanent persona core.",
        ],
    }


def build_timeline_shift_markdown(payload: dict) -> str:
    lines = [
        "# Timeline Shift",
        "",
        "该文件按发布时间切分样本，帮助判断哪些模式是长期稳定内核，哪些可能只是近期热点。",
        "",
        f"- Shift score: {payload.get('shift_score', 0.0)}",
        "",
    ]
    for period in payload.get("periods", []):
        lines.extend(
            [
                f"## {period['name']} ({period['start_date']} to {period['end_date']})",
                "",
                f"- Count: {period['count']}",
                f"- Top video IDs: {', '.join(period['top_video_ids'])}",
                "",
                "### Theme Counts",
                "",
            ]
        )
        for label, count in period.get("theme_counts", {}).items():
            lines.append(f"- {label}: {count}")
        lines.extend(["", "### Contribution Counts", ""])
        for label, count in period.get("contribution_counts", {}).items():
            lines.append(f"- {label}: {count}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_asr_entity_review(run_dir: Path, corpus_index: dict) -> dict:
    transcript_dir = run_dir / "transcripts"
    candidates: dict[str, dict[str, Any]] = {}
    suspicious_terms = Counter()
    for record in corpus_index.get("records", []):
        text = " ".join(
            [
                record.get("title", ""),
                transcript_text(transcript_dir, record.get("video_id", "")),
            ]
        )
        for entity in KNOWN_ENTITY_PATTERNS:
            if re.search(re.escape(entity), text, re.IGNORECASE):
                entry = candidates.setdefault(entity, {"count": 0, "video_ids": []})
                entry["count"] += 1
                entry["video_ids"].append(record["video_id"])
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+/-]{2,}", text):
            if token.lower() not in {"the", "and", "for", "with"}:
                suspicious_terms[token] += 1
    return {
        "known_entities": candidates,
        "additional_ascii_candidates": [
            {"term": term, "count": count}
            for term, count in suspicious_terms.most_common(60)
            if term not in candidates
        ],
        "candidate_count": len(candidates) + len(suspicious_terms),
        "review_required": True,
        "note": "ASR may misrecognize model names, companies, people, and product names. Review high-impact names before commercial delivery.",
    }


def build_asr_entity_review_markdown(payload: dict) -> str:
    lines = [
        "# ASR Entity Review",
        "",
        "该文件列出 ASR 中需要人工复核的英文模型名、品牌名、公司名、产品名和疑似专名。正式交付前应抽检高影响条目。",
        "",
        "## Known Entities",
        "",
        "| Entity | Count | Video IDs |",
        "|---|---:|---|",
    ]
    for entity, data in payload.get("known_entities", {}).items():
        lines.append(f"| {entity} | {data['count']} | {', '.join(data['video_ids'][:10])} |")
    lines.extend(["", "## Additional ASCII Candidates", ""])
    lines.append("| Term | Count |")
    lines.append("|---|---:|")
    for item in payload.get("additional_ascii_candidates", [])[:50]:
        lines.append(f"| {item['term']} | {item['count']} |")
    return "\n".join(lines).rstrip() + "\n"


def sentence_like_count(text: str) -> int:
    return len(re.findall(r"[。！？!?]", text))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?])\s*", text)
    return [part.strip() for part in parts if part.strip()]


def keyword_labels(text: str, groups: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    labels = []
    for label, keywords in groups.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            labels.append(label)
    return labels


def first_matching_sentence(sentences: list[str], keywords: list[str]) -> str:
    for sentence in sentences:
        if any(keyword.lower() in sentence.lower() for keyword in keywords):
            return sentence[:180]
    return sentences[0][:180] if sentences else ""


def reusable_phrase_candidates(text: str, limit: int = 6) -> list[str]:
    candidates: Counter[str] = Counter()
    for phrase in re.findall(r"[\u4e00-\u9fff]{4,14}", text):
        if len(set(phrase)) <= 2:
            continue
        if any(marker in phrase for marker in ["你以为", "其实", "真正", "普通人", "这就是", "说白了", "意味着"]):
            candidates[phrase] += 2
        else:
            candidates[phrase] += 1
    return [phrase for phrase, _ in candidates.most_common(limit)]


def contribution_types(title: str, text: str, themes: list[str]) -> list[str]:
    combined = f"{title}\n{text}"
    labels = []
    if any(theme in themes for theme in ["比赛 / 实验 / 模拟"]):
        labels.append("script_template:experiment")
    if any(theme in themes for theme in ["工具教程 / 低门槛", "教育 / 高考 / 学习"]):
        labels.append("topic_model:low_barrier_tutorial")
    if any(theme in themes for theme in ["现场 / 发布会 / 探访"]):
        labels.append("script_template:field_report")
    if any(theme in themes for theme in ["风险 / 灰区 / 安全"]):
        labels.append("safety_boundary:risk_gray_area")
    if re.search(r"机制|原理|本质|为什么|背后", combined):
        labels.append("judgment_heuristic:mechanism_explanation")
    if re.search(r"未来|趋势|生态|平台|产业|全球|中国", combined):
        labels.append("topic_model:industry_context")
    return labels or ["evidence:general_style"]


def transcript_text(transcript_dir: Path, video_id: str) -> str:
    path = transcript_dir / f"{video_id}.txt"
    if not path.exists():
        return ""
    return clean_text(path.read_text(encoding="utf-8-sig", errors="replace"))


def transcript_record(item: dict, transcript_dir: Path) -> dict:
    video_id = str(item.get("platform_video_id") or "")
    text = transcript_text(transcript_dir, video_id)
    title = str(item.get("title", "")).replace("\n", " ")
    stats = item.get("stats") or {}
    themes = [
        theme
        for theme, keywords in THEME_KEYWORDS.items()
        if any(keyword.lower() in title.lower() for keyword in keywords)
    ]
    return {
        "video_id": video_id,
        "published_at": item.get("published_at", ""),
        "title": title,
        "duration": item.get("duration"),
        "stats": stats,
        "weighted_score": item_score(item),
        "transcript_chars": len(text),
        "sentence_like_breaks": sentence_like_count(text),
        "themes": themes,
        "opener": text[:180],
        "ending": text[-180:] if text else "",
    }


def transcript_signal(record: dict, transcript_dir: Path) -> dict:
    video_id = record["video_id"]
    text = transcript_text(transcript_dir, video_id)
    sentences = split_sentences(text)
    title = record["title"]
    themes = record.get("themes") or []
    combined = f"{title}\n{text}"
    hook_labels = keyword_labels(" ".join(sentences[:3]) or title, HOOK_KEYWORDS)
    argument_labels = keyword_labels(combined, ARGUMENT_KEYWORDS)
    ending_labels = keyword_labels(" ".join(sentences[-3:]) if sentences else title, ENDING_KEYWORDS)
    judgment_markers = [keyword for keyword in JUDGMENT_KEYWORDS if keyword.lower() in combined.lower()]
    boundary_sample = "风险 / 灰区 / 安全" in themes or bool(re.search(r"黑客|注入|安全|攻击|灰色|跑路|举报|违规", combined))
    return {
        "video_id": video_id,
        "title": title,
        "published_at": record.get("published_at", ""),
        "weighted_score": record.get("weighted_score", 0),
        "transcript_chars": record.get("transcript_chars", 0),
        "themes": themes,
        "hook_type": hook_labels or ["未显式命中"],
        "core_question_candidate": first_matching_sentence(
            sentences,
            ["到底", "为什么", "怎么", "如何", "能不能", "是不是", "意味着"],
        ),
        "conflict_or_turning_point": first_matching_sentence(
            sentences,
            ["但是", "没想到", "结果", "问题是", "真正", "其实", "反而"],
        ),
        "argument_mode": argument_labels or ["未显式命中"],
        "ending_mode": ending_labels or ["未显式命中"],
        "value_judgment_markers": judgment_markers,
        "reusable_phrases": reusable_phrase_candidates(text),
        "boundary_or_risk_sample": boundary_sample,
        "contribution_types": contribution_types(title, text, themes),
    }


def build_corpus_index(run_dir: Path) -> dict:
    selected = read_json(run_dir / "metadata" / "selected.compact.json")
    transcript_dir = run_dir / "transcripts"
    records = [transcript_record(item, transcript_dir) for item in selected.get("items", [])]
    records_by_score = sorted(records, key=lambda item: item["weighted_score"], reverse=True)
    records_by_length = sorted(records, key=lambda item: item["transcript_chars"], reverse=True)
    return {
        "creator_profile": selected.get("creator_profile") or {},
        "requested_count": selected.get("requested_count"),
        "selected_count": selected.get("selected_count"),
        "selection_strategy": selected.get("selection_strategy"),
        "coverage": {
            "transcript_count": sum(1 for record in records if record["transcript_chars"] > 0),
            "total_transcript_chars": sum(record["transcript_chars"] for record in records),
            "long_transcripts_over_5000_chars": sum(1 for record in records if record["transcript_chars"] >= 5000),
            "short_transcripts_under_800_chars": sum(1 for record in records if 0 < record["transcript_chars"] < 800),
        },
        "top_by_weighted_score": [record["video_id"] for record in records_by_score[:30]],
        "top_by_transcript_length": [record["video_id"] for record in records_by_length[:30]],
        "records": records,
    }


def build_transcript_signals(run_dir: Path, corpus_index: dict) -> dict:
    transcript_dir = run_dir / "transcripts"
    signals = [transcript_signal(record, transcript_dir) for record in corpus_index["records"]]
    by_contribution = Counter(label for signal in signals for label in signal["contribution_types"])
    by_hook = Counter(label for signal in signals for label in signal["hook_type"])
    by_argument = Counter(label for signal in signals for label in signal["argument_mode"])
    return {
        "summary": {
            "signal_count": len(signals),
            "boundary_or_risk_count": sum(1 for signal in signals if signal["boundary_or_risk_sample"]),
            "contribution_counts": dict(by_contribution.most_common()),
            "hook_counts": dict(by_hook.most_common()),
            "argument_counts": dict(by_argument.most_common()),
        },
        "signals": signals,
    }


def build_transcript_signals_markdown(signal_payload: dict) -> str:
    lines = [
        "# Transcript Signals",
        "",
        "该文件由启发式脚本生成，逐条抽取 ASR 的结构信号。它不是最终结论，宿主 agent 必须用原文抽检和修正。",
        "",
        "## Summary",
        "",
    ]
    summary = signal_payload["summary"]
    lines.append(f"- Signal count: {summary['signal_count']}")
    lines.append(f"- Boundary or risk samples: {summary['boundary_or_risk_count']}")
    lines.extend(["", "### Contribution Counts", ""])
    for label, count in summary["contribution_counts"].items():
        lines.append(f"- {label}: {count}")
    lines.extend(["", "### Hook Counts", ""])
    for label, count in summary["hook_counts"].items():
        lines.append(f"- {label}: {count}")
    lines.extend(["", "### Argument Counts", ""])
    for label, count in summary["argument_counts"].items():
        lines.append(f"- {label}: {count}")

    lines.extend(["", "## Per-Video Signal Table", ""])
    lines.append("| Video ID | Hook | Argument | Ending | Boundary | Contribution | Core Question |")
    lines.append("|---|---|---|---|---|---|---|")
    for signal in signal_payload["signals"]:
        lines.append(
            "| {video_id} | {hook} | {argument} | {ending} | {boundary} | {contribution} | {question} |".format(
                video_id=signal["video_id"],
                hook=", ".join(signal["hook_type"]).replace("|", "/"),
                argument=", ".join(signal["argument_mode"]).replace("|", "/"),
                ending=", ".join(signal["ending_mode"]).replace("|", "/"),
                boundary="yes" if signal["boundary_or_risk_sample"] else "no",
                contribution=", ".join(signal["contribution_types"]).replace("|", "/"),
                question=signal["core_question_candidate"].replace("|", "/"),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def top_terms_for_text(text: str, limit: int = 30) -> list[tuple[str, int]]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
    stop = {
        "这个",
        "一个",
        "我们",
        "你们",
        "他们",
        "就是",
        "然后",
        "因为",
        "所以",
        "但是",
        "今天",
        "大家",
        "可以",
        "the",
        "and",
        "for",
    }
    counts = Counter(token for token in tokens if token not in stop)
    return counts.most_common(limit)


def common_phrase_candidates(texts: list[str], limit: int = 40) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for text in texts:
        for phrase in re.findall(r"[\u4e00-\u9fff]{4,12}", text):
            if len(set(phrase)) <= 2:
                continue
            counts[phrase] += 1
    return [(phrase, count) for phrase, count in counts.most_common(limit) if count >= 2]


def build_signal_matrix(run_dir: Path, corpus_index: dict) -> str:
    transcript_dir = run_dir / "transcripts"
    records = corpus_index["records"]
    texts = [transcript_text(transcript_dir, record["video_id"]) for record in records if record["transcript_chars"] > 0]
    all_text = "\n".join(texts)
    theme_counts = Counter(theme for record in records for theme in record.get("themes", []))
    opener_terms = top_terms_for_text("\n".join(record["opener"] for record in records), 25)
    ending_terms = top_terms_for_text("\n".join(record["ending"] for record in records), 25)
    corpus_terms = top_terms_for_text(all_text, 40)
    phrase_candidates = common_phrase_candidates(texts, 40)

    lines = [
        "# Transcript Signal Matrix",
        "",
        "该文件由脚本确定性生成，用于帮助宿主 agent 做全量覆盖。它不是最终研究结论，只是研究线索。",
        "",
        "## Coverage",
        "",
        f"- Transcript count: {corpus_index['coverage']['transcript_count']}",
        f"- Total transcript chars: {corpus_index['coverage']['total_transcript_chars']}",
        f"- Long transcripts >= 5000 chars: {corpus_index['coverage']['long_transcripts_over_5000_chars']}",
        f"- Short transcripts < 800 chars: {corpus_index['coverage']['short_transcripts_under_800_chars']}",
        "",
        "## Theme Counts",
        "",
    ]
    for theme, count in theme_counts.most_common():
        lines.append(f"- {theme}: {count}")

    lines.extend(["", "## Corpus Terms", ""])
    for term, count in corpus_terms:
        lines.append(f"- {term}: {count}")

    lines.extend(["", "## Opener Terms", ""])
    for term, count in opener_terms:
        lines.append(f"- {term}: {count}")

    lines.extend(["", "## Ending Terms", ""])
    for term, count in ending_terms:
        lines.append(f"- {term}: {count}")

    lines.extend(["", "## Repeated Phrase Candidates", ""])
    for phrase, count in phrase_candidates:
        lines.append(f"- {phrase}: {count}")

    lines.extend(["", "## Per-Video Signals", ""])
    lines.append("| Video ID | Date | Chars | Sentences | Score | Themes | Title |")
    lines.append("|---|---|---:|---:|---:|---|---|")
    for record in records:
        title = record["title"].replace("|", "/")
        themes = ", ".join(record.get("themes") or [])
        lines.append(
            f"| {record['video_id']} | {str(record['published_at'])[:10]} | {record['transcript_chars']} | "
            f"{record['sentence_like_breaks']} | {record['weighted_score']} | {themes} | {title} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def build_audit_template() -> str:
    return """# Refinement Audit

## 覆盖审计

- [ ] 是否使用 `research/host_refinement/corpus_index.json` 检查了全部样本？
- [ ] 是否使用 `research/host_refinement/transcript_signal_matrix.md` 检查了全量主题、开头、结尾和高频表达？
- [ ] 是否使用 `research/host_refinement/transcript_signals.json` 检查了逐条 ASR 的 hook、论证、结尾、判断和贡献类型？
- [ ] 是否使用 `research/reviews/evidence_coverage.md` 检查了证据覆盖评分？
- [ ] 是否使用 `research/reviews/coverage_gaps.md` 补读高优先级缺口视频？
- [ ] 是否使用 `research/reviews/short_form_coverage.md` 检查了短视频 hook、转折和结尾？
- [ ] 是否使用 `research/reviews/timeline_shift.md` 检查了阶段变化？
- [ ] 是否使用 `research/reviews/asr_entity_review.md` 检查了 ASR 专名风险？
- [ ] 是否至少覆盖 15 个视频锚点？
- [ ] 是否覆盖高互动样本、长转写样本、短视频样本、边界/风险样本？

## 深度审计

- [ ] 是否深读了至少 8 条代表性完整转写？
- [ ] 是否把证据和推断分开？
- [ ] 是否写出跨视频重复模式，而不是单视频印象？
- [ ] 是否记录矛盾、变化和证据缺口？

## 成品审计

- [ ] `persona.md` 是否能指导选题、脚本、改写和批评？
- [ ] `topic_model.md` 是否包含带证据锚点和失败模式的模型？
- [ ] `script_style.md` 是否有分类型模板，而不是通用三段式？
- [ ] `evidence_index.md` 是否能追溯到具体视频 ID？
- [ ] `persona_model.json` 是否结构完整，并与 Markdown 结论、证据锚点一致？
- [ ] `persona_model.json` 是否包含生成协议和评测 case？
- [ ] 是否没有身份冒充、虚假背书、声音/形象克隆风险？
- [ ] 是否没有长篇转写稿倾倒或乱码？
- [ ] 是否完成 `usage_probe.md` 的反向生成测试？
- [ ] 是否完成 `evaluation_suite.md` 的固定评测集？
- [ ] 是否同步填写 `evaluation_suite.json`，并让 scorecard 通过？
- [ ] 是否完成 `reverse_identification.md` 的反向识别测试？
- [ ] 是否同步填写 `reverse_identification.json`，并让 scorecard 通过？
- [ ] 是否完成 `reviewer_findings.md` 的二次审稿并修复关键问题？

## 结论

- 审计人：
- 审计时间：
- 是否建议 `ready_for_use=true`：
- 仍需补强：
"""


def build_usage_probe_template() -> str:
    return """# Usage Probe

## 目的

用生成后的 Creator Skill 反向测试它是否真的能驱动选题、改写、批评和证据解释。模板状态不能作为成品。

执行时必须优先读取 `skill/references/persona_model.json`，再用 `persona.md`、`topic_model.md`、`script_style.md` 和 `evidence_index.md` 校准。每个输出都要标注使用了哪些 topic model、script template、judgment heuristic、expression DNA 和 anti-pattern。

## 测试一：新选题筛选

- 输入候选：
- 选择结果：
- 拒绝结果：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 测试二：普通文稿改写

- 原始文稿：
- 改写结果：
- 保留的表达 DNA：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 测试三：不像样本批评

- 待批评片段：
- 不像的原因：
- 修正建议：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 测试四：完整脚本大纲

- 选题：
- Hook：
- 结构：
- 关键转折：
- 结尾收束：
- 使用的 persona_model 字段：
- 依据的视频锚点：

## 结论

- 是否通过反向生成测试：
- 仍需补强：
"""


def build_evaluation_suite_template() -> str:
    return """# Evaluation Suite

## 目的

用固定评测集检验最终 Creator Skill 是否能稳定驱动真实任务。模板状态不能作为成品。

执行顺序：

1. 先读 `skill/references/persona_model.json`。
2. 为每个 case 选择对应的 topic model、script template、judgment heuristic、expression DNA 和 anti-pattern。
3. 生成结果后，用 `evidence_index.md` 标注视频锚点。
4. 如果证据不足，必须降级置信度，不要补套话。

## Case 1：热点选题筛选

- 输入候选：
- 应用的 topic model：
- 应用的 judgment heuristic：
- 选择：
- 拒绝：
- 证据视频 ID：
- 置信度：

## Case 2：30 秒短视频脚本

- 输入选题：
- 应用的 script template：
- Hook：
- 主体：
- 转折：
- 结尾：
- 证据视频 ID：
- 置信度：

## Case 3：普通文案改写

- 原始文案：
- 应用的 expression DNA：
- 改写结果：
- 避开的 anti-pattern：
- 证据视频 ID：
- 置信度：

## Case 4：不像样本批评

- 待评估文本：
- 不像的地方：
- 命中的 anti-pattern：
- 修正建议：
- 证据视频 ID：
- 置信度：

## Case 5：边界请求处理

- 输入请求：
- 命中的 safety boundary：
- 处理方式：
- 替代性安全输出：
- 证据或规则依据：
- 置信度：

## Case 6：证据解释

- 输入问题：
- 使用的模型字段：
- 输出结论：
- 逐条证据说明：
- 哪些只是推断：
- 置信度：

## Scorecard

- 6 个 case 是否全部完成：否
- 每个 case 是否引用 persona_model 字段：否
- 每个 case 是否引用视频证据或安全规则：否
- 是否发现泛泛 AI 文案：是
- 是否通过评测集：否
- 仍需补强：
"""


def build_evaluation_suite_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Creator Evaluation Suite",
        "type": "object",
        "required": ["status", "cases", "scorecard"],
        "properties": {
            "status": {"type": "string"},
            "cases": {
                "type": "array",
                "minItems": 6,
                "items": {
                    "type": "object",
                    "required": ["name", "task", "input", "applied_persona_model_fields", "output", "evidence_video_ids", "passed"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "task": {"type": "string", "minLength": 1},
                        "input": {"type": "string"},
                        "applied_persona_model_fields": {
                            "type": "array",
                            "minItems": 2,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "output": {"type": "string"},
                        "evidence_video_ids": {
                            "type": "array",
                            "items": {"type": "string", "pattern": "^\\d{16,20}$"},
                        },
                        "safety_rule_ids": {"type": "array", "items": {"type": "string"}},
                        "generic_ai_markers": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "string"},
                        "passed": {"type": "boolean"},
                    },
                },
            },
            "scorecard": {
                "type": "object",
                "required": ["all_cases_completed", "persona_model_fields_cited", "evidence_or_rule_cited", "passed"],
                "properties": {
                    "all_cases_completed": {"type": "boolean"},
                    "persona_model_fields_cited": {"type": "boolean"},
                    "evidence_or_rule_cited": {"type": "boolean"},
                    "generic_ai_markers_reviewed": {"type": "boolean"},
                    "passed": {"type": "boolean"},
                    "remaining_gaps": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


def build_evaluation_suite_json_template() -> dict:
    case_names = [
        ("hot_topic_selection", "热点选题筛选"),
        ("short_script_30s", "30 秒短视频脚本"),
        ("copy_rewrite", "普通文案改写"),
        ("style_critique", "不像样本批评"),
        ("boundary_request", "边界请求处理"),
        ("evidence_explanation", "证据解释"),
    ]
    return {
        "status": "draft_template",
        "cases": [
            {
                "name": name,
                "task": task,
                "input": "",
                "applied_persona_model_fields": [],
                "output": "",
                "evidence_video_ids": [],
                "safety_rule_ids": [],
                "generic_ai_markers": [],
                "confidence": "",
                "passed": False,
            }
            for name, task in case_names
        ],
        "scorecard": {
            "all_cases_completed": False,
            "persona_model_fields_cited": False,
            "evidence_or_rule_cited": False,
            "generic_ai_markers_reviewed": False,
            "passed": False,
            "remaining_gaps": [],
        },
    }


def build_reverse_identification_template() -> str:
    return """# Reverse Identification

## 目的

对 `evaluation_suite.md` 和 `usage_probe.md` 中的生成结果做反向识别：证明哪些地方来自该创作者的稳定模式，哪些只是泛泛 AI 文案。模板状态不能作为成品。

## 识别表

| Output | Creator-specific markers | Generic AI markers | Persona model fields | Evidence video IDs | Verdict |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

## 必答问题

1. 去掉创作者名字后，哪些句子仍然能体现该账号的内容方法？
2. 哪些句子只是通用短视频文案，可以出现在任何账号里？
3. 哪些判断、转折或结尾能回溯到 `persona_model.json`？
4. 哪些证据 ID 支撑这些判断？
5. 哪些输出需要重写或降级置信度？

## Scorecard

- 至少识别 5 个 creator-specific marker：否
- 至少识别 3 个 generic AI marker：否
- 每个高置信 marker 是否能回溯到 persona_model 字段：否
- 每个高置信 marker 是否能回溯到视频 ID：否
- 是否通过反向识别测试：否
- 仍需补强：
"""


def build_reverse_identification_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Creator Reverse Identification",
        "type": "object",
        "required": ["status", "rows", "scorecard"],
        "properties": {
            "status": {"type": "string"},
            "rows": {
                "type": "array",
                "minItems": 5,
                "items": {
                    "type": "object",
                    "required": [
                        "output_id",
                        "creator_specific_markers",
                        "generic_ai_markers",
                        "persona_model_fields",
                        "evidence_video_ids",
                        "verdict",
                    ],
                    "properties": {
                        "output_id": {"type": "string", "minLength": 1},
                        "creator_specific_markers": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "generic_ai_markers": {"type": "array", "items": {"type": "string"}},
                        "persona_model_fields": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "evidence_video_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "pattern": "^\\d{16,20}$"},
                        },
                        "verdict": {"type": "string", "minLength": 1},
                    },
                },
            },
            "scorecard": {
                "type": "object",
                "required": ["creator_specific_marker_count", "generic_ai_marker_count", "fields_traceable", "evidence_traceable", "passed"],
                "properties": {
                    "creator_specific_marker_count": {"type": "integer", "minimum": 0},
                    "generic_ai_marker_count": {"type": "integer", "minimum": 0},
                    "fields_traceable": {"type": "boolean"},
                    "evidence_traceable": {"type": "boolean"},
                    "passed": {"type": "boolean"},
                    "remaining_gaps": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


def build_reverse_identification_json_template() -> dict:
    return {
        "status": "draft_template",
        "rows": [],
        "scorecard": {
            "creator_specific_marker_count": 0,
            "generic_ai_marker_count": 0,
            "fields_traceable": False,
            "evidence_traceable": False,
            "passed": False,
            "remaining_gaps": [],
        },
    }


def build_reviewer_template() -> str:
    return """# Reviewer Findings

## Reviewer 角色

只挑问题，不补正文。重点检查证据不足、过度抽象、模板太泛、身份越界、ASR 专名风险、评测集失败、反向识别失败和无法驱动生成的段落。

## Findings

| Severity | File | Issue | Evidence | Required Fix | Status |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

## 修复确认

- 是否处理全部 high / medium 问题：
- 是否仍有低置信结论：
- 是否建议进入 `ready_for_use=true`：
"""


def build_persona_model_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Creator Persona Model",
        "type": "object",
        "additionalProperties": True,
        "required": [
            "version",
            "core_identity",
            "topic_models",
            "script_templates",
            "judgment_heuristics",
            "expression_dna",
            "anti_patterns",
            "safety_boundaries",
            "evidence_anchors",
            "generation_protocol",
            "evaluation_cases",
        ],
        "properties": {
            "version": {"type": "string"},
            "status": {"type": "string"},
            "creator": {"type": "string"},
            "core_identity": {"type": "string", "minLength": 40},
            "topic_models": {
                "type": "array",
                "minItems": 5,
                "items": {
                    "type": "object",
                    "required": ["name", "definition", "use_cases", "evidence_ids", "failure_modes"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "definition": {"type": "string", "minLength": 1},
                        "use_cases": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                        "evidence_ids": {
                            "type": "array",
                            "minItems": 2,
                            "items": {"type": "string", "pattern": "^\\d{16,20}$"},
                        },
                        "failure_modes": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                    },
                },
            },
            "script_templates": {
                "type": "array",
                "minItems": 4,
                "items": {
                    "type": "object",
                    "required": ["name", "use_cases", "hook", "body", "ending", "failure_modes", "evidence_ids"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "use_cases": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                        "hook": {"type": "string", "minLength": 1},
                        "body": {"type": "string", "minLength": 1},
                        "ending": {"type": "string", "minLength": 1},
                        "failure_modes": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                        "evidence_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "pattern": "^\\d{16,20}$"},
                        },
                    },
                },
            },
            "judgment_heuristics": {"type": "array", "minItems": 6, "items": {"type": "string", "minLength": 1}},
            "expression_dna": {"type": "array", "minItems": 6, "items": {"type": "string", "minLength": 1}},
            "anti_patterns": {"type": "array", "minItems": 5, "items": {"type": "string", "minLength": 1}},
            "safety_boundaries": {"type": "array", "minItems": 4, "items": {"type": "string", "minLength": 1}},
            "evidence_anchors": {
                "type": "array",
                "minItems": 15,
                "items": {
                    "type": "object",
                    "required": ["video_id", "role"],
                    "properties": {
                        "video_id": {"type": "string", "pattern": "^\\d{16,20}$"},
                        "role": {"type": "string", "minLength": 1},
                    },
                },
            },
            "generation_protocol": {
                "type": "object",
                "required": ["field_order", "task_routing", "evidence_policy", "confidence_policy"],
                "properties": {
                    "field_order": {
                        "type": "array",
                        "minItems": 5,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "task_routing": {
                        "type": "array",
                        "minItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["task", "use_fields"],
                            "properties": {
                                "task": {"type": "string", "minLength": 1},
                                "use_fields": {
                                    "type": "array",
                                    "minItems": 2,
                                    "items": {"type": "string", "minLength": 1},
                                },
                            },
                        },
                    },
                    "evidence_policy": {"type": "string", "minLength": 1},
                    "confidence_policy": {"type": "string", "minLength": 1},
                },
            },
            "evaluation_cases": {
                "type": "array",
                "minItems": 6,
                "items": {
                    "type": "object",
                    "required": ["name", "task", "expected_fields", "pass_criteria"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "task": {"type": "string", "minLength": 1},
                        "expected_fields": {
                            "type": "array",
                            "minItems": 2,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "pass_criteria": {
                            "type": "array",
                            "minItems": 2,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    }


def build_persona_model_template(corpus_index: dict) -> dict:
    return {
        "version": "1.0",
        "status": "draft_template",
        "creator": (corpus_index.get("creator_profile") or {}).get("nickname", ""),
        "core_identity": "",
        "topic_models": [
            {
                "name": "",
                "definition": "",
                "use_cases": [],
                "evidence_ids": [],
                "failure_modes": [],
            }
        ],
        "script_templates": [
            {
                "name": "",
                "use_cases": [],
                "hook": "",
                "body": "",
                "ending": "",
                "failure_modes": [],
                "evidence_ids": [],
            }
        ],
        "judgment_heuristics": [],
        "expression_dna": [],
        "anti_patterns": [],
        "safety_boundaries": [
            "不得冒充创作者本人",
            "不得声称创作者认可、批准或背书",
            "不得克隆声音或形象",
        ],
        "evidence_anchors": [],
        "generation_protocol": {
            "field_order": [],
            "task_routing": [],
            "evidence_policy": "",
            "confidence_policy": "",
        },
        "evaluation_cases": [],
    }


def build_brief(run_dir: Path, top_count: int, excerpt_count: int, excerpt_chars: int) -> str:
    selected_path = run_dir / "metadata" / "selected.compact.json"
    selected = read_json(selected_path)
    items = selected.get("items", [])
    creator = selected.get("creator_profile") or {}
    transcript_dir = run_dir / "transcripts"
    skill_dir = run_dir / "skill"

    by_score = sorted(items, key=item_score, reverse=True)
    by_length = []
    for item in items:
        transcript = transcript_dir / f"{item.get('platform_video_id')}.txt"
        if transcript.exists():
            by_length.append((transcript.stat().st_size, item))
    by_length.sort(reverse=True, key=lambda row: row[0])

    representative_ids = []
    for item in by_score[:excerpt_count]:
        representative_ids.append(str(item.get("platform_video_id")))
    for _, item in by_length[:excerpt_count]:
        vid = str(item.get("platform_video_id"))
        if vid not in representative_ids:
            representative_ids.append(vid)
    representative_ids = representative_ids[: max(excerpt_count * 2, excerpt_count)]
    item_by_id = {str(item.get("platform_video_id")): item for item in items}

    lines = [
        "# Host Refinement Brief",
        "",
        "配套文件：",
        "",
        "- `corpus_index.json`：全量样本索引，含互动、转写长度、主题标签、开头和结尾。",
        "- `transcript_signal_matrix.md`：全量语料信号矩阵，含主题分布、高频词、开头/结尾词、重复短语和逐视频指标。",
        "- `transcript_signals.json` / `transcript_signals.md`：逐条 ASR 结构信号，含 hook、核心问题、转折、论证、结尾、价值判断和贡献类型。",
        "- `../reviews/evidence_coverage.md`：证据覆盖评分，检查 evidence index 是否覆盖高互动、长转写、短转写、主题簇和边界样本。",
        "- `../reviews/coverage_gaps.md`：覆盖缺口推荐，列出下一轮最应该补读或补证据的视频。",
        "- `../reviews/short_form_coverage.md`：短视频专项覆盖，检查短转写样本的 hook、结尾和证据强度。",
        "- `../reviews/timeline_shift.md`：阶段变化评分，检查近期热点和长期内核的差异。",
        "- `../reviews/asr_entity_review.md`：ASR 专名校对清单，列出英文模型名、品牌名、公司名和疑似误识别项。",
        "- `../reviews/refinement_audit.md`：宿主 agent 完成深加工后填写的审计清单。",
        "- `../reviews/usage_probe.md`：反向生成测试，验证 skill 是否能驱动选题、改写、批评和脚本大纲。",
        "- `../reviews/evaluation_suite.md` / `evaluation_suite.json`：固定评测集，验证 skill 是否能覆盖选题、脚本、改写、批评、边界处理和证据解释。",
        "- `../reviews/reverse_identification.md` / `reverse_identification.json`：反向识别测试，验证生成稿的 creator-specific markers 是否能回溯到 persona_model 和视频 ID。",
        "- `../reviews/reviewer_findings.md`：二次审稿问题清单，记录证据不足、过度抽象和边界风险。",
        "- `../../skill/references/persona_model.schema.json`：结构化人格模型 schema。",
        "- `../../skill/references/persona_model.json`：宿主 agent 必须填写的机器可读人格模型。",
        "",
        "## Creator",
        "",
        f"- Nickname: {creator.get('nickname', '')}",
        f"- Handle: {creator.get('handle', '')}",
        f"- Author ID: {creator.get('author_id', '')}",
        f"- Sec UID: {creator.get('sec_uid', '')}",
        f"- Requested count: {selected.get('requested_count')}",
        f"- Selected count: {selected.get('selected_count')}",
        f"- Selection strategy: {selected.get('selection_strategy')}",
        "",
        "## Current Skill Footprint",
        "",
    ]

    for relative in [
        "SKILL.md",
        "references/persona.md",
        "references/topic_model.md",
        "references/script_style.md",
        "references/research_summary.md",
        "references/evidence_index.md",
    ]:
        path = skill_dir / relative
        size = path.stat().st_size if path.exists() else 0
        extra = ""
        if relative.endswith("evidence_index.md"):
            extra = f", table_rows={count_table_row(path)}"
        lines.append(f"- `{relative}`: {size} bytes{extra}")

    lines.extend(["", "## Top Videos By Weighted Interaction", ""])
    lines.append("| Rank | Video ID | Date | Score | Stats | Title |")
    lines.append("|---:|---|---|---:|---|---|")
    for rank, item in enumerate(by_score[:top_count], start=1):
        stats = item.get("stats") or {}
        stat_text = f"L{stats.get('like', 0)} F{stats.get('favorite', 0)} S{stats.get('share', 0)} C{stats.get('comment', 0)}"
        title = str(item.get("title", "")).replace("\n", " ")
        lines.append(
            f"| {rank} | {item.get('platform_video_id')} | {str(item.get('published_at', ''))[:10]} | {item_score(item)} | {stat_text} | {title} |"
        )

    lines.extend(["", "## Theme Keyword Matches", ""])
    for theme, keywords in THEME_KEYWORDS.items():
        matched = [
            item
            for item in items
            if any(keyword.lower() in str(item.get("title", "")).lower() for keyword in keywords)
        ]
        lines.append(f"### {theme} ({len(matched)})")
        for item in matched[:10]:
            title = str(item.get("title", "")).replace("\n", " ")
            lines.append(f"- `{item.get('platform_video_id')}` {title}")
        lines.append("")

    lines.extend(["## Full Title Index", ""])
    for index, item in enumerate(items, start=1):
        title = str(item.get("title", "")).replace("\n", " ")
        lines.append(f"{index:03d}. `{item.get('platform_video_id')}` {str(item.get('published_at', ''))[:10]} {title}")

    lines.extend(["", "## Representative Transcript Excerpts", ""])
    for vid in representative_ids:
        item = item_by_id.get(vid)
        if not item:
            continue
        title = str(item.get("title", "")).replace("\n", " ")
        path = transcript_dir / f"{vid}.txt"
        length = path.stat().st_size if path.exists() else 0
        lines.extend(
            [
                f"### `{vid}` {title}",
                "",
                f"- Transcript bytes: {length}",
                "",
                transcript_excerpt(path, excerpt_chars),
                "",
            ]
        )

    lines.extend(
        [
            "## Host Agent Questions",
            "",
            "宿主 agent 精修时必须回答：",
            "",
            "1. 去掉名字后，这个账号最稳定的内容能力是什么？",
            "2. 选题模型有哪些？每个模型至少用 2 个视频锚定。",
            "3. 哪些脚本结构跨主题重复出现？",
            "4. 表达 DNA 是结构性的，还是只是一组口头禅？",
            "5. 哪些判断启发式能指导新选题？",
            "6. 哪些反模式会让生成内容不像或越界？",
            "7. 最近 12-24 个月是否出现阶段变化？",
            "8. 哪些结论证据不足，必须标为推断？",
            "",
            "## Required Refinement Outputs",
            "",
            "- `research/raw/01_topic_and_timeline.md`",
            "- `research/raw/02_structure_and_judgment.md`",
            "- `research/raw/03_expression_and_boundary.md`",
            "- `research/raw/04_contradictions_and_evolution.md`",
            "- `research/raw/05_short_form_patterns.md`",
            "- Rewrite `skill/SKILL.md`",
            "- Rewrite `skill/references/persona.md`",
            "- Rewrite `skill/references/topic_model.md`",
            "- Rewrite `skill/references/script_style.md`",
            "- Rewrite `skill/references/research_summary.md`",
            "- Rewrite `skill/references/evidence_index.md`",
            "- Fill `skill/references/persona_model.json`",
            "- Update `skill/references/meta.json`",
            "- Fill `research/reviews/usage_probe.md`",
            "- Fill `research/reviews/evaluation_suite.md`",
            "- Fill `research/reviews/reverse_identification.md`",
            "- Fill `research/reviews/reviewer_findings.md`",
            "- Fill `research/reviews/refinement_audit.md`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a compact host-agent refinement brief")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--top-count", type=int, default=25)
    parser.add_argument("--excerpt-count", type=int, default=10)
    parser.add_argument("--excerpt-chars", type=int, default=900)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser()
    output_dir = run_dir / "research" / "host_refinement"
    output_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir = run_dir / "research" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    skill_refs_dir = run_dir / "skill" / "references"
    skill_refs_dir.mkdir(parents=True, exist_ok=True)

    corpus_index = build_corpus_index(run_dir)
    signal_payload = build_transcript_signals(run_dir, corpus_index)
    evidence_coverage = build_evidence_coverage(run_dir, corpus_index, signal_payload)
    coverage_gaps = build_coverage_gaps(corpus_index, signal_payload, evidence_coverage)
    short_form_coverage = build_short_form_coverage(corpus_index, signal_payload)
    timeline_shift = build_timeline_shift(corpus_index, signal_payload)
    asr_entity_review = build_asr_entity_review(run_dir, corpus_index)
    corpus_path = output_dir / "corpus_index.json"
    matrix_path = output_dir / "transcript_signal_matrix.md"
    signals_json_path = output_dir / "transcript_signals.json"
    signals_md_path = output_dir / "transcript_signals.md"
    brief_path = output_dir / "brief.md"
    coverage_json_path = reviews_dir / "evidence_coverage.json"
    coverage_md_path = reviews_dir / "evidence_coverage.md"
    coverage_gaps_json_path = reviews_dir / "coverage_gaps.json"
    coverage_gaps_md_path = reviews_dir / "coverage_gaps.md"
    short_form_json_path = reviews_dir / "short_form_coverage.json"
    short_form_md_path = reviews_dir / "short_form_coverage.md"
    timeline_json_path = reviews_dir / "timeline_shift.json"
    timeline_md_path = reviews_dir / "timeline_shift.md"
    entity_json_path = reviews_dir / "asr_entity_review.json"
    entity_md_path = reviews_dir / "asr_entity_review.md"
    audit_path = reviews_dir / "refinement_audit.md"
    usage_probe_path = reviews_dir / "usage_probe.md"
    evaluation_suite_path = reviews_dir / "evaluation_suite.md"
    evaluation_suite_json_path = reviews_dir / "evaluation_suite.json"
    evaluation_suite_schema_path = reviews_dir / "evaluation_suite.schema.json"
    reverse_identification_path = reviews_dir / "reverse_identification.md"
    reverse_identification_json_path = reviews_dir / "reverse_identification.json"
    reverse_identification_schema_path = reviews_dir / "reverse_identification.schema.json"
    reviewer_path = reviews_dir / "reviewer_findings.md"
    persona_schema_path = skill_refs_dir / "persona_model.schema.json"
    persona_model_path = skill_refs_dir / "persona_model.json"

    corpus_path.write_text(json.dumps(corpus_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    matrix_path.write_text(build_signal_matrix(run_dir, corpus_index), encoding="utf-8")
    signals_json_path.write_text(json.dumps(signal_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    signals_md_path.write_text(build_transcript_signals_markdown(signal_payload), encoding="utf-8")
    coverage_json_path.write_text(json.dumps(evidence_coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    coverage_md_path.write_text(build_evidence_coverage_markdown(evidence_coverage), encoding="utf-8")
    coverage_gaps_json_path.write_text(json.dumps(coverage_gaps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    coverage_gaps_md_path.write_text(build_coverage_gaps_markdown(coverage_gaps), encoding="utf-8")
    short_form_json_path.write_text(json.dumps(short_form_coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    short_form_md_path.write_text(build_short_form_coverage_markdown(short_form_coverage), encoding="utf-8")
    timeline_json_path.write_text(json.dumps(timeline_shift, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    timeline_md_path.write_text(build_timeline_shift_markdown(timeline_shift), encoding="utf-8")
    entity_json_path.write_text(json.dumps(asr_entity_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entity_md_path.write_text(build_asr_entity_review_markdown(asr_entity_review), encoding="utf-8")
    persona_schema_path.write_text(json.dumps(build_persona_model_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not persona_model_path.exists() or persona_model_path.stat().st_size < 20:
        persona_model_path.write_text(
            json.dumps(build_persona_model_template(corpus_index), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    brief_path.write_text(build_brief(run_dir, args.top_count, args.excerpt_count, args.excerpt_chars), encoding="utf-8")
    if not audit_path.exists() or audit_path.stat().st_size < 20:
        audit_path.write_text(build_audit_template(), encoding="utf-8")
    if not usage_probe_path.exists() or usage_probe_path.stat().st_size < 20:
        usage_probe_path.write_text(build_usage_probe_template(), encoding="utf-8")
    if not evaluation_suite_path.exists() or evaluation_suite_path.stat().st_size < 20:
        evaluation_suite_path.write_text(build_evaluation_suite_template(), encoding="utf-8")
    evaluation_suite_schema_path.write_text(
        json.dumps(build_evaluation_suite_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not evaluation_suite_json_path.exists() or evaluation_suite_json_path.stat().st_size < 20:
        evaluation_suite_json_path.write_text(
            json.dumps(build_evaluation_suite_json_template(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not reverse_identification_path.exists() or reverse_identification_path.stat().st_size < 20:
        reverse_identification_path.write_text(build_reverse_identification_template(), encoding="utf-8")
    reverse_identification_schema_path.write_text(
        json.dumps(build_reverse_identification_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not reverse_identification_json_path.exists() or reverse_identification_json_path.stat().st_size < 20:
        reverse_identification_json_path.write_text(
            json.dumps(build_reverse_identification_json_template(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not reviewer_path.exists() or reviewer_path.stat().st_size < 20:
        reviewer_path.write_text(build_reviewer_template(), encoding="utf-8")

    print(brief_path)
    print(corpus_path)
    print(matrix_path)
    print(signals_json_path)
    print(signals_md_path)
    print(coverage_json_path)
    print(coverage_md_path)
    print(coverage_gaps_json_path)
    print(coverage_gaps_md_path)
    print(short_form_json_path)
    print(short_form_md_path)
    print(timeline_json_path)
    print(timeline_md_path)
    print(entity_json_path)
    print(entity_md_path)
    print(persona_schema_path)
    print(persona_model_path)
    print(audit_path)
    print(usage_probe_path)
    print(evaluation_suite_path)
    print(evaluation_suite_schema_path)
    print(evaluation_suite_json_path)
    print(reverse_identification_path)
    print(reverse_identification_schema_path)
    print(reverse_identification_json_path)
    print(reviewer_path)


if __name__ == "__main__":
    main()
