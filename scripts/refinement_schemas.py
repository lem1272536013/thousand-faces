"""Versioned evaluator and persona JSON Schema/template builders."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import schema_validation


def _strict_schema_objects(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            node["additionalProperties"] = False
        for value in node.values():
            _strict_schema_objects(value)
    elif isinstance(node, list):
        for value in node:
            _strict_schema_objects(value)


def _relax_template_constraints(node: object) -> None:
    if isinstance(node, dict):
        for keyword in ("const", "enum", "minItems", "minLength", "minimum", "pattern"):
            node.pop(keyword, None)
        for value in node.values():
            _relax_template_constraints(value)
    elif isinstance(node, list):
        for value in node:
            _relax_template_constraints(value)


def _status_document_schema(
    artifact: str,
    title: str,
    completed_schema: dict[str, Any],
) -> dict[str, Any]:
    completed = deepcopy(completed_schema)
    for metadata_key in ("$schema", "$id", "x-schema-version", "title"):
        completed.pop(metadata_key, None)
    required = list(completed.get("required") or [])
    if "status" not in required:
        required.insert(0, "status")
    completed["required"] = required
    completed.setdefault("properties", {})["status"] = {
        "type": "string",
        "const": "completed",
    }
    _strict_schema_objects(completed)

    template = deepcopy(completed)
    _relax_template_constraints(template)
    template["properties"]["status"] = {
        "type": "string",
        "const": "draft_template",
    }
    _strict_schema_objects(template)
    return {
        **schema_validation.schema_metadata(artifact),
        "title": title,
        "oneOf": [
            {"$ref": "#/$defs/draft_template"},
            {"$ref": "#/$defs/completed"},
        ],
        "$defs": {
            "draft_template": template,
            "completed": completed,
        },
    }


def build_evaluation_suite_schema() -> dict:
    completed: dict[str, Any] = {
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
    scorecard = completed["properties"]["scorecard"]
    scorecard["required"].append("generic_ai_markers_reviewed")
    return _status_document_schema(
        "evaluation_suite",
        "Creator Evaluation Suite",
        completed,
    )


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



def build_reverse_identification_schema() -> dict:
    completed: dict[str, Any] = {
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
    return _status_document_schema(
        "reverse_identification",
        "Creator Reverse Identification",
        completed,
    )


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



def build_persona_model_schema() -> dict:
    completed: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Creator Persona Model",
        "type": "object",
        "additionalProperties": False,
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
    return _status_document_schema(
        "persona_model",
        "Creator Persona Model",
        completed,
    )


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
