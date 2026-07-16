#!/usr/bin/env python3
"""Strict Draft 2020-12 validation with compact, report-safe diagnostics."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


SCHEMA_DRAFT_URI = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_VERSION = "1.1.0"
VALIDATION_ERROR_LIMIT = 50
VALIDATION_MESSAGE_LIMIT = 240


def schema_metadata(artifact: str) -> dict[str, str]:
    """Return the versioned identity shared by every generated schema."""

    return {
        "$schema": SCHEMA_DRAFT_URI,
        "$id": f"https://schemas.qianrenqianmian.local/{artifact}/{SCHEMA_VERSION}",
        "x-schema-version": SCHEMA_VERSION,
    }


def _short_message(value: object) -> str:
    message = re.sub(r"\s+", " ", str(value)).strip()
    if len(message) <= VALIDATION_MESSAGE_LIMIT:
        return message
    return message[: VALIDATION_MESSAGE_LIMIT - 1].rstrip() + "…"


def _validation_message(error: ValidationError) -> str:
    """Describe a validation failure without echoing the document value."""

    keyword = str(error.validator or "validation")
    if keyword == "type":
        expected = error.validator_value
        if isinstance(expected, list):
            expected_text = ", ".join(str(item) for item in expected)
        else:
            expected_text = str(expected)
        return f"expected JSON type: {expected_text}"

    messages = {
        "required": "required property is missing",
        "additionalProperties": "additional property is not allowed",
        "const": "value does not match the required constant",
        "enum": "value is not one of the allowed values",
        "minItems": f"array must contain at least {error.validator_value} items",
        "maxItems": f"array must contain at most {error.validator_value} items",
        "minLength": f"string must contain at least {error.validator_value} characters",
        "maxLength": f"string must contain at most {error.validator_value} characters",
        "minimum": f"number must be at least {error.validator_value}",
        "maximum": f"number must be at most {error.validator_value}",
        "pattern": "string does not match the required pattern",
        "uniqueItems": "array items must be unique",
    }
    return messages.get(keyword, f"failed JSON Schema keyword: {keyword}")


def _json_pointer(parts: Iterable[object]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "" if not encoded else "/" + "/".join(encoded)


def _leaf_errors(error: ValidationError) -> Iterable[ValidationError]:
    if not error.context:
        yield error
        return
    for child in error.context:
        yield from _leaf_errors(child)


def _error_pointer(error: ValidationError) -> str:
    parts = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, Mapping):
        match = re.match(r"^'(.+)' is a required property$", error.message)
        if match:
            parts.append(match.group(1))
    elif error.validator == "additionalProperties" and isinstance(error.instance, Mapping):
        properties = error.schema.get("properties", {}) if isinstance(error.schema, Mapping) else {}
        extras = sorted(str(key) for key in error.instance if key not in properties)
        if extras:
            parts.append(extras[0])
    return _json_pointer(parts)


def _validation_errors(
    document: object,
    schema: Mapping[str, Any],
) -> list[dict[str, str]]:
    status = document.get("status") if isinstance(document, Mapping) else None
    raw_errors: list[ValidationError] = []
    for error in Draft202012Validator(schema).iter_errors(document):
        raw_errors.extend(_leaf_errors(error))

    diagnostics: dict[tuple[str, str, str], dict[str, str]] = {}
    for error in raw_errors:
        if (
            error.validator == "const"
            and status in {"draft_template", "completed"}
            and error.validator_value in {"draft_template", "completed"}
            and error.validator_value != status
        ):
            continue
        pointer = _error_pointer(error)
        keyword = str(error.validator or "validation")
        message = _short_message(_validation_message(error))
        diagnostics[(pointer, keyword, message)] = {
            "pointer": pointer,
            "keyword": keyword,
            "message": message,
        }
    return sorted(
        diagnostics.values(),
        key=lambda item: (item["pointer"], item["keyword"], item["message"]),
    )[:VALIDATION_ERROR_LIMIT]


def _schema_contract_errors(schema: Mapping[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if schema.get("$schema") != SCHEMA_DRAFT_URI:
        errors.append(
            {
                "pointer": "/$schema",
                "keyword": "schema_draft",
                "message": f"schema draft must be {SCHEMA_DRAFT_URI}",
            }
        )
    if schema.get("x-schema-version") != SCHEMA_VERSION:
        errors.append(
            {
                "pointer": "/x-schema-version",
                "keyword": "schema_version",
                "message": f"schema version must be {SCHEMA_VERSION}",
            }
        )
    if not isinstance(schema.get("$id"), str) or not schema.get("$id"):
        errors.append(
            {
                "pointer": "/$id",
                "keyword": "schema_id",
                "message": "schema must declare a non-empty $id",
            }
        )
    return errors


def validate_document(
    document: object,
    schema: Mapping[str, Any],
    *,
    artifact: str,
) -> dict[str, Any]:
    """Validate an in-memory JSON value and return serializable diagnostics."""

    contract_errors = _schema_contract_errors(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        contract_errors.append(
            {
                "pointer": _json_pointer(exc.absolute_schema_path),
                "keyword": "invalid_schema",
                "message": _short_message(exc.message),
            }
        )
    if contract_errors:
        return {
            "artifact": artifact,
            "valid": False,
            "schema_valid": False,
            "validator": "Draft202012Validator",
            "schema_version": schema.get("x-schema-version"),
            "status": document.get("status") if isinstance(document, Mapping) else None,
            "errors": contract_errors[:VALIDATION_ERROR_LIMIT],
        }

    errors = _validation_errors(document, schema)
    return {
        "artifact": artifact,
        "valid": not errors,
        "schema_valid": True,
        "validator": "Draft202012Validator",
        "schema_version": schema.get("x-schema-version"),
        "status": document.get("status") if isinstance(document, Mapping) else None,
        "errors": errors,
    }


def _file_error(
    artifact: str,
    *,
    schema_valid: bool,
    keyword: str,
    message: str,
    schema_version: object = None,
) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "valid": False,
        "schema_valid": schema_valid,
        "validator": "Draft202012Validator",
        "schema_version": schema_version,
        "status": None,
        "errors": [{"pointer": "", "keyword": keyword, "message": _short_message(message)}],
    }


def validate_json_file(
    document_path: Path,
    schema_path: Path,
    *,
    artifact: str,
) -> dict[str, Any]:
    """Validate JSON files without leaking absolute paths or document contents."""

    if not schema_path.is_file():
        return _file_error(
            artifact,
            schema_valid=False,
            keyword="schema_file_missing",
            message="schema file is missing",
        )
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _file_error(
            artifact,
            schema_valid=False,
            keyword="schema_file_invalid",
            message=f"schema file is not valid JSON: {type(exc).__name__}",
        )
    if not isinstance(schema, dict):
        return _file_error(
            artifact,
            schema_valid=False,
            keyword="schema_root_type",
            message="schema root must be a JSON object",
        )

    contract_errors = _schema_contract_errors(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        contract_errors.append(
            {
                "pointer": _json_pointer(exc.absolute_schema_path),
                "keyword": "invalid_schema",
                "message": _short_message(exc.message),
            }
        )
    if contract_errors:
        return {
            "artifact": artifact,
            "valid": False,
            "schema_valid": False,
            "validator": "Draft202012Validator",
            "schema_version": schema.get("x-schema-version"),
            "status": None,
            "errors": contract_errors[:VALIDATION_ERROR_LIMIT],
        }

    if not document_path.is_file():
        return _file_error(
            artifact,
            schema_valid=True,
            keyword="document_file_missing",
            message="document file is missing",
            schema_version=schema.get("x-schema-version"),
        )
    try:
        document = json.loads(document_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _file_error(
            artifact,
            schema_valid=True,
            keyword="document_file_invalid",
            message=f"document file is not valid JSON: {type(exc).__name__}",
            schema_version=schema.get("x-schema-version"),
        )
    return validate_document(document, schema, artifact=artifact)
