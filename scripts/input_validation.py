"""Stable boundary validation for CLI inputs and runtime settings."""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from typing import Mapping

import settings


@dataclass(frozen=True)
class IntRange:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class FloatRange:
    minimum: float
    maximum: float


@dataclass(frozen=True)
class ValidatedRunInputs:
    project_name: str
    project_slug: str
    sample_count: int
    metadata_fetch_limit: int


class InputValidationError(ValueError):
    """Raised when a CLI or environment boundary value is invalid."""


def _int_range(name: str) -> IntRange:
    spec = settings.setting_spec(name)
    if spec.value_type is not settings.SettingType.INTEGER:
        raise RuntimeError(f"{name} is not an integer setting")
    if spec.minimum is None or spec.maximum is None:
        raise RuntimeError(f"{name} is missing integer bounds")
    return IntRange(int(spec.minimum), int(spec.maximum))


def _float_range(name: str) -> FloatRange:
    spec = settings.setting_spec(name)
    if spec.value_type is not settings.SettingType.FLOAT:
        raise RuntimeError(f"{name} is not a float setting")
    if spec.minimum is None or spec.maximum is None:
        raise RuntimeError(f"{name} is missing float bounds")
    return FloatRange(float(spec.minimum), float(spec.maximum))


SAMPLE_COUNT_RANGE = IntRange(1, 1000)
METADATA_FETCH_LIMIT_RANGE = _int_range("TIKHUB_METADATA_FETCH_LIMIT")
DOWNLOAD_CONCURRENCY_RANGE = _int_range("DOWNLOAD_CONCURRENCY")
FFMPEG_CONCURRENCY_RANGE = _int_range("FFMPEG_CONCURRENCY")
ASR_CONCURRENCY_RANGE = _int_range("ALI_ASR_CONCURRENCY")
BASE64_AUDIO_BYTES_RANGE = _int_range("ALI_ASR_MAX_BASE64_AUDIO_BYTES")
RETRY_RANGE = _int_range("PROVIDER_RETRY_MAX_ATTEMPTS")
SECONDS_RANGE = _int_range("HTTP_TIMEOUT_SECONDS")
OSS_SIGNED_URL_SECONDS_RANGE = _int_range("ALI_OSS_SIGNED_URL_EXPIRES")
OSS_FAILURE_RETENTION_SECONDS_RANGE = _int_range("ALI_OSS_FAILURE_RETENTION_SECONDS")
VIDEO_BYTES_RANGE = _int_range("MAX_VIDEO_BYTES")
STAGE_MIN_COUNT_RANGE = _int_range("DRAFT_MIN_STAGE_COUNT")
STAGE_RATIO_RANGE = _float_range("DRAFT_MIN_STAGE_RATIO")
RETRY_DELAY_SECONDS_RANGE = _float_range("PROVIDER_RETRY_BASE_SECONDS")
PROVIDER_DEADLINE_SECONDS_RANGE = _float_range("PROVIDER_REQUEST_DEADLINE_SECONDS")
POLL_INTERVAL_SECONDS_RANGE = _float_range("ALI_ASR_POLL_SECONDS")
POLL_DEADLINE_SECONDS_RANGE = _float_range("ALI_ASR_POLL_DEADLINE_SECONDS")
JITTER_RATIO_RANGE = _float_range("PROVIDER_RETRY_JITTER_RATIO")
PROJECT_SLUG_MAX_LENGTH = 80

DEFAULT_STAGE_THRESHOLD_VALUES = {
    key: settings.DEFAULT_ENV[key]
    for key in (
        "DRAFT_MIN_STAGE_COUNT",
        "DRAFT_MIN_STAGE_RATIO",
        "READY_MIN_STAGE_COUNT",
        "READY_MIN_STAGE_RATIO",
    )
}

CONFIG_INT_RANGES = {
    "TIKHUB_METADATA_FETCH_LIMIT": METADATA_FETCH_LIMIT_RANGE,
    "TIKHUB_MAX_PAGES": _int_range("TIKHUB_MAX_PAGES"),
    "DOWNLOAD_CONCURRENCY": DOWNLOAD_CONCURRENCY_RANGE,
    "FFMPEG_CONCURRENCY": FFMPEG_CONCURRENCY_RANGE,
    "ALI_ASR_CONCURRENCY": ASR_CONCURRENCY_RANGE,
    "ALI_ASR_MAX_BASE64_AUDIO_BYTES": BASE64_AUDIO_BYTES_RANGE,
    "DOWNLOAD_RETRY": RETRY_RANGE,
    "ALI_ASR_RETRY": RETRY_RANGE,
    "PROVIDER_RETRY_MAX_ATTEMPTS": RETRY_RANGE,
    "HTTP_TIMEOUT_SECONDS": SECONDS_RANGE,
    "MAX_VIDEO_BYTES": VIDEO_BYTES_RANGE,
    "DOWNLOAD_HEADER_TIMEOUT_SECONDS": SECONDS_RANGE,
    "DOWNLOAD_DEADLINE_SECONDS": SECONDS_RANGE,
    "MEDIA_PROBE_TIMEOUT_SECONDS": SECONDS_RANGE,
    "ALI_ASR_TIMEOUT_SECONDS": SECONDS_RANGE,
    "ASR_SEGMENT_SECONDS": SECONDS_RANGE,
    "ALI_OSS_SIGNED_URL_EXPIRES": OSS_SIGNED_URL_SECONDS_RANGE,
    "ALI_OSS_FAILURE_RETENTION_SECONDS": OSS_FAILURE_RETENTION_SECONDS_RANGE,
    "DRAFT_MIN_STAGE_COUNT": STAGE_MIN_COUNT_RANGE,
    "READY_MIN_STAGE_COUNT": STAGE_MIN_COUNT_RANGE,
}

CONFIG_FLOAT_RANGES = {
    "DRAFT_MIN_STAGE_RATIO": STAGE_RATIO_RANGE,
    "READY_MIN_STAGE_RATIO": STAGE_RATIO_RANGE,
}

RUNTIME_CONFIG_FLOAT_RANGES = {
    "PROVIDER_RETRY_BASE_SECONDS": RETRY_DELAY_SECONDS_RANGE,
    "PROVIDER_RETRY_MAX_SECONDS": RETRY_DELAY_SECONDS_RANGE,
    "PROVIDER_RETRY_JITTER_RATIO": JITTER_RATIO_RANGE,
    "PROVIDER_REQUEST_DEADLINE_SECONDS": PROVIDER_DEADLINE_SECONDS_RANGE,
    "ALI_ASR_POLL_SECONDS": POLL_INTERVAL_SECONDS_RANGE,
    "ALI_ASR_POLL_DEADLINE_SECONDS": POLL_DEADLINE_SECONDS_RANGE,
}


def validate_bounded_int(name: str, value: object, allowed: IntRange) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise InputValidationError(
            f"{name} must be an integer between {allowed.minimum} and {allowed.maximum}; got {value!r}"
        )
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        raise InputValidationError(
            f"{name} must be an integer between {allowed.minimum} and {allowed.maximum}; got {value!r}"
        )
    parsed = int(text)
    if not allowed.minimum <= parsed <= allowed.maximum:
        raise InputValidationError(
            f"{name} must be between {allowed.minimum} and {allowed.maximum}; got {parsed}"
        )
    return parsed


def validate_bounded_float(name: str, value: object, allowed: FloatRange) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InputValidationError(
            f"{name} must be a number between {allowed.minimum} and {allowed.maximum}; got {value!r}"
        )
    try:
        parsed = float(str(value).strip())
    except ValueError as exc:
        raise InputValidationError(
            f"{name} must be a number between {allowed.minimum} and {allowed.maximum}; got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or not allowed.minimum <= parsed <= allowed.maximum:
        raise InputValidationError(
            f"{name} must be between {allowed.minimum} and {allowed.maximum}; got {value!r}"
        )
    return parsed


def _load_settings(config: Mapping[str, object]) -> settings.Settings:
    try:
        return settings.Settings.from_mapping(config)
    except settings.SettingsError as error:
        raise InputValidationError(str(error)) from error


def _selected_settings(
    config: Mapping[str, object],
    names: tuple[str, ...],
) -> settings.Settings:
    return _load_settings({name: config[name] for name in names if name in config})


def validate_asr_concurrency(config: Mapping[str, object]) -> int:
    return _selected_settings(config, ("ALI_ASR_CONCURRENCY",)).integer("ALI_ASR_CONCURRENCY")


def validate_asr_memory_budget(config: Mapping[str, object]) -> tuple[int, int]:
    loaded = _selected_settings(
        config,
        (
            "ALI_ASR_PROVIDER",
            "ALI_ASR_CONCURRENCY",
            "ALI_ASR_MAX_BASE64_AUDIO_BYTES",
        ),
    )
    return (
        loaded.integer("ALI_ASR_CONCURRENCY"),
        loaded.integer("ALI_ASR_MAX_BASE64_AUDIO_BYTES"),
    )


def normalize_project_slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value.strip())
    return re.sub(r"-+", "-", normalized).strip("-_").lower()


def validate_project_name(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError("--project-name must not be empty")
    project_name = value.strip()
    project_slug = normalize_project_slug(project_name)
    if not project_slug:
        raise InputValidationError("--project-name must contain a letter, number, underscore, hyphen, or Chinese character")
    if len(project_slug) > PROJECT_SLUG_MAX_LENGTH:
        raise InputValidationError(
            f"--project-name normalized slug must be at most {PROJECT_SLUG_MAX_LENGTH} characters; "
            f"got {len(project_slug)}"
        )
    return project_name, project_slug


def validate_runtime_config(config: Mapping[str, object]) -> dict[str, int]:
    loaded = _load_settings(config)
    return {key: loaded.integer(key) for key in CONFIG_INT_RANGES}


def validate_stage_threshold_config(config: Mapping[str, object]) -> dict[str, dict[str, int | float]]:
    loaded = _selected_settings(
        config,
        (
            "DRAFT_MIN_STAGE_COUNT",
            "DRAFT_MIN_STAGE_RATIO",
            "READY_MIN_STAGE_COUNT",
            "READY_MIN_STAGE_RATIO",
        ),
    )
    draft_count = loaded.integer("DRAFT_MIN_STAGE_COUNT")
    ready_count = loaded.integer("READY_MIN_STAGE_COUNT")
    draft_ratio = loaded.number("DRAFT_MIN_STAGE_RATIO")
    ready_ratio = loaded.number("READY_MIN_STAGE_RATIO")
    return {
        "draft": {"min_count": draft_count, "min_ratio": draft_ratio},
        "ready": {"min_count": ready_count, "min_ratio": ready_ratio},
    }


def validate_run_inputs(
    project_name: object,
    sample_count: object,
    metadata_fetch_limit: object | None,
    config: Mapping[str, str],
) -> ValidatedRunInputs:
    normalized_name, project_slug = validate_project_name(project_name)
    validated_sample_count = validate_bounded_int("--sample-count", sample_count, SAMPLE_COUNT_RANGE)
    runtime_values = validate_runtime_config(config)
    validate_stage_threshold_config(config)
    if metadata_fetch_limit is None:
        validated_fetch_limit = runtime_values["TIKHUB_METADATA_FETCH_LIMIT"]
    else:
        validated_fetch_limit = validate_bounded_int(
            "--metadata-fetch-limit",
            metadata_fetch_limit,
            METADATA_FETCH_LIMIT_RANGE,
        )
    return ValidatedRunInputs(
        project_name=normalized_name,
        project_slug=project_slug,
        sample_count=validated_sample_count,
        metadata_fetch_limit=validated_fetch_limit,
    )


def sample_count_argument(value: str) -> int:
    try:
        return validate_bounded_int("--sample-count", value, SAMPLE_COUNT_RANGE)
    except InputValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def metadata_fetch_limit_argument(value: str) -> int:
    try:
        return validate_bounded_int("--metadata-fetch-limit", value, METADATA_FETCH_LIMIT_RANGE)
    except InputValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def project_name_argument(value: str) -> str:
    try:
        project_name, _ = validate_project_name(value)
        return project_name
    except InputValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
