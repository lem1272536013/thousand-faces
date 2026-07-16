"""Single-source typed settings for every runtime entry point."""

from __future__ import annotations

import math
import os
import re
import urllib.parse
from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

import oss_lifecycle
import redaction


SETTINGS_SCHEMA_VERSION = 2
ASR_BASE64_RAW_INFLIGHT_BYTES_MAX = 128 * 1024 * 1024

RETIRED_SETTING_GUIDANCE = MappingProxyType(
    {
        "ALI_ASR_APP_KEY": "use ALI_ASR_API_KEY or DASHSCOPE_API_KEY for the selected provider",
        "AUTO_RESUME": "resume explicitly with scripts/resume_creator_run.py",
        "MAX_INPUT_TOKENS": "host-agent context budgets are controlled by the host, not this pipeline",
        "MAX_OUTPUT_TOKENS": "host-agent output budgets are controlled by the host, not this pipeline",
    }
)


class SettingsError(ValueError):
    """Raised before runtime work when configuration cannot be normalized."""


class SettingType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"


class SettingGroup(StrEnum):
    TIKHUB = "tikhub"
    ASR = "asr"
    OSS = "oss"
    RECOVERY = "recovery"
    RUNTIME = "runtime"
    QUALITY = "quality"


class SettingTier(StrEnum):
    STANDARD = "standard"
    ADVANCED = "advanced"


class SettingStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class AsrProvider(StrEnum):
    OPENAI_COMPATIBLE = "openai-compatible"
    COMPATIBLE = "compatible"
    QWEN_COMPATIBLE = "qwen-compatible"
    ALIYUN = "aliyun"


def default_asr_model(provider: AsrProvider | str) -> str:
    """Return the central model default for one validated ASR provider."""

    try:
        normalized = provider if isinstance(provider, AsrProvider) else AsrProvider(provider)
    except ValueError as error:
        choices = ", ".join(member.value for member in AsrProvider)
        raise SettingsError(f"ALI_ASR_PROVIDER must be one of: {choices}") from error
    if normalized is AsrProvider.ALIYUN:
        return "fun-asr"
    return "qwen3-asr-flash"


class CompatibleApi(StrEnum):
    CHAT_COMPLETIONS = "chat-completions"
    AUDIO_TRANSCRIPTIONS = "audio-transcriptions"


class AsrWaitMode(StrEnum):
    WAIT = "wait"
    POLL = "poll"


class OssLifecycleMode(StrEnum):
    DELETE_AFTER_ASR = "delete_after_asr"
    RETAIN = "retain"


SettingValue: TypeAlias = str | int | float | bool | StrEnum | None


@dataclass(frozen=True)
class SettingSpec:
    name: str
    value_type: SettingType
    description: str
    default: SettingValue = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    optional: bool = False
    secret: bool = False
    enum_type: type[StrEnum] | None = None
    endpoint_kind: str | None = None
    nonempty: bool = False
    group: SettingGroup = SettingGroup.RUNTIME
    tier: SettingTier = SettingTier.STANDARD
    status: SettingStatus = SettingStatus.ACTIVE
    replacement: str | None = None


def _string(
    name: str,
    description: str,
    default: str | None = None,
    *,
    optional: bool = False,
    secret: bool = False,
    endpoint_kind: str | None = None,
    nonempty: bool = False,
) -> SettingSpec:
    return SettingSpec(
        name,
        SettingType.STRING,
        description,
        default=default,
        optional=optional,
        secret=secret,
        endpoint_kind=endpoint_kind,
        nonempty=nonempty,
    )


def _integer(name: str, description: str, default: int, minimum: int, maximum: int) -> SettingSpec:
    return SettingSpec(
        name,
        SettingType.INTEGER,
        description,
        default=default,
        minimum=minimum,
        maximum=maximum,
    )


def _float(name: str, description: str, default: float, minimum: float, maximum: float) -> SettingSpec:
    return SettingSpec(
        name,
        SettingType.FLOAT,
        description,
        default=default,
        minimum=minimum,
        maximum=maximum,
    )


def _boolean(name: str, description: str, default: bool) -> SettingSpec:
    return SettingSpec(name, SettingType.BOOLEAN, description, default=default)


def _enum(name: str, description: str, default: StrEnum, enum_type: type[StrEnum]) -> SettingSpec:
    return SettingSpec(
        name,
        SettingType.ENUM,
        description,
        default=default,
        enum_type=enum_type,
    )


_BASE_SETTING_SPECS = (
    _string("TIKHUB_API_KEY", "TikHub API credential.", optional=True, secret=True),
    _string("TIKHUB_API_BASE", "TikHub absolute HTTP API base URL.", optional=True, endpoint_kind="url"),
    _string(
        "TIKHUB_CREATOR_VIDEOS_ENDPOINT",
        "TikHub creator-video relative endpoint path.",
        optional=True,
        endpoint_kind="relative",
    ),
    _string("TIKHUB_AUTH_HEADER", "TikHub authentication header name.", "Authorization", nonempty=True),
    _string("TIKHUB_AUTH_SCHEME", "TikHub authentication scheme.", "Bearer"),
    _integer("TIKHUB_METADATA_FETCH_LIMIT", "Maximum metadata items requested.", 100, 1, 5000),
    _string("TIKHUB_SOURCE_URL_PARAM", "TikHub source URL query parameter.", "url", nonempty=True),
    _boolean("TIKHUB_AUTO_RESOLVE_DOUYIN_URL", "Resolve Douyin share URLs before TikHub calls.", True),
    _string("TIKHUB_LIMIT_PARAM", "TikHub item-limit query parameter.", "limit", nonempty=True),
    _string("TIKHUB_EXTRA_QUERY", "Additional TikHub query string.", optional=True),
    _string("TIKHUB_ITEMS_PATH", "Optional dotted TikHub item-list path.", optional=True),
    _string("TIKHUB_VIDEO_ID_PATH", "Optional dotted TikHub video ID path.", optional=True),
    _string("TIKHUB_VIDEO_TITLE_PATH", "Optional dotted TikHub title path.", optional=True),
    _string("TIKHUB_VIDEO_PUBLISHED_AT_PATH", "Optional dotted TikHub publish-time path.", optional=True),
    _string("TIKHUB_VIDEO_DOWNLOAD_URL_PATH", "Optional dotted TikHub download URL path.", optional=True),
    _string("TIKHUB_VIDEO_SOURCE_URL_PATH", "Optional dotted TikHub source URL path.", optional=True),
    _string("TIKHUB_CURSOR_PARAM", "TikHub pagination cursor field and query parameter.", "max_cursor", nonempty=True),
    _boolean("TIKHUB_ENABLE_PAGINATION", "Enable bounded TikHub cursor pagination.", True),
    _integer("TIKHUB_MAX_PAGES", "Maximum TikHub pages per metadata request.", 20, 1, 1000),
    _enum(
        "ALI_ASR_PROVIDER",
        "ASR provider adapter selection.",
        AsrProvider.OPENAI_COMPATIBLE,
        AsrProvider,
    ),
    _string("ALI_ASR_API_KEY", "ASR provider credential.", optional=True, secret=True),
    _string("ALI_ASR_ENDPOINT", "OpenAI-compatible ASR absolute endpoint.", optional=True, endpoint_kind="url"),
    _string("ALI_ASR_MODEL", "ASR model identifier.", "qwen3-asr-flash", nonempty=True),
    _string("ALI_ASR_LANGUAGE", "ASR language hint.", "zh-CN", nonempty=True),
    _string("ALI_ASR_AUDIO_FORMAT", "Extracted audio container suffix.", "mp3", nonempty=True),
    _string("ALI_ASR_RESPONSE_FORMAT", "Compatible ASR response format.", "json", nonempty=True),
    _string("ALI_ASR_MIME_TYPE", "Compatible ASR audio MIME type.", "audio/mpeg", nonempty=True),
    _enum(
        "ALI_ASR_COMPATIBLE_API",
        "Compatible ASR request style.",
        CompatibleApi.CHAT_COMPLETIONS,
        CompatibleApi,
    ),
    _boolean("ALI_ASR_ENABLE_ITN", "Enable inverse text normalization when supported.", False),
    _integer("ALI_ASR_TIMEOUT_SECONDS", "ASR request timeout in seconds.", 180, 1, 3600),
    _integer("ALI_ASR_CONCURRENCY", "Maximum concurrent ASR video tasks.", 4, 1, 16),
    _integer(
        "ALI_ASR_MAX_BASE64_AUDIO_BYTES",
        "Maximum raw compatible-chat audio bytes per request.",
        8 * 1024 * 1024,
        1,
        32 * 1024 * 1024,
    ),
    _integer("ALI_ASR_RETRY", "Legacy ASR retry attempts.", 3, 1, 20),
    _float("ALI_ASR_POLL_SECONDS", "DashScope polling interval in seconds.", 5.0, 0.1, 3600.0),
    _float("ALI_ASR_POLL_DEADLINE_SECONDS", "DashScope polling deadline in seconds.", 900.0, 1.0, 86400.0),
    _enum("ALI_ASR_WAIT_MODE", "Legacy bounded DashScope waiting mode.", AsrWaitMode.WAIT, AsrWaitMode),
    _string(
        "ALI_ASR_AUDIO_URL_TEMPLATE",
        "Absolute public audio URL template for file-url ASR.",
        optional=True,
        endpoint_kind="url",
    ),
    _string("AUDIO_PUBLIC_URL_BASE", "Absolute public audio base URL.", optional=True, endpoint_kind="url"),
    _integer("ASR_SAMPLE_RATE", "Audio sample rate in hertz.", 16000, 8000, 384000),
    _string("ASR_MP3_BITRATE", "FFmpeg MP3 audio bitrate.", "64k", nonempty=True),
    _integer("ASR_SEGMENT_SECONDS", "Maximum ASR segment duration in seconds.", 120, 1, 3600),
    _string("ALI_OSS_ENDPOINT", "Aliyun OSS endpoint.", optional=True),
    _string("ALI_OSS_BUCKET", "Aliyun OSS bucket name.", optional=True),
    _string("ALI_OSS_ACCESS_KEY_ID", "Aliyun OSS access-key identifier.", optional=True, secret=True),
    _string("ALI_OSS_ACCESS_KEY_SECRET", "Aliyun OSS access-key secret.", optional=True, secret=True),
    _string("ALI_OSS_PREFIX", "Managed OSS object prefix.", "creator-agent-studio/audio", nonempty=True),
    _integer("ALI_OSS_SIGNED_URL_EXPIRES", "OSS signed URL lifetime in seconds.", 3600, 60, 3600),
    _enum(
        "ALI_OSS_LIFECYCLE_POLICY",
        "Temporary OSS audio lifecycle mode.",
        OssLifecycleMode.DELETE_AFTER_ASR,
        OssLifecycleMode,
    ),
    _integer(
        "ALI_OSS_FAILURE_RETENTION_SECONDS",
        "Failed ASR OSS retention window in seconds.",
        86400,
        60,
        30 * 24 * 60 * 60,
    ),
    _string("DASHSCOPE_API_KEY", "DashScope API credential.", optional=True, secret=True),
    _string(
        "DASHSCOPE_BASE_HTTP_API_URL",
        "DashScope-compatible absolute HTTP API base URL.",
        optional=True,
        endpoint_kind="url",
    ),
    _string("RUN_ROOT", "Default root directory for new runs.", "runs", nonempty=True),
    _integer("DOWNLOAD_CONCURRENCY", "Maximum concurrent video downloads.", 6, 1, 32),
    _integer("DOWNLOAD_RETRY", "Video download retry attempts.", 3, 1, 20),
    _integer("MAX_VIDEO_BYTES", "Maximum bytes per downloaded video.", 512 * 1024 * 1024, 1, 50 * 1024**3),
    _integer("DOWNLOAD_HEADER_TIMEOUT_SECONDS", "Download response-header timeout.", 30, 1, 3600),
    _integer("DOWNLOAD_DEADLINE_SECONDS", "Total video download deadline.", 300, 1, 3600),
    _integer("MEDIA_PROBE_TIMEOUT_SECONDS", "ffprobe media-validation timeout.", 30, 1, 3600),
    _integer("HTTP_TIMEOUT_SECONDS", "Default provider request timeout.", 60, 1, 3600),
    _integer("PROVIDER_RETRY_MAX_ATTEMPTS", "Unified provider maximum attempts.", 3, 1, 20),
    _float("PROVIDER_RETRY_BASE_SECONDS", "Unified provider base backoff.", 1.0, 0.0, 3600.0),
    _float("PROVIDER_RETRY_MAX_SECONDS", "Unified provider maximum backoff.", 10.0, 0.0, 3600.0),
    _float("PROVIDER_RETRY_JITTER_RATIO", "Unified provider retry jitter ratio.", 0.2, 0.0, 1.0),
    _float("PROVIDER_REQUEST_DEADLINE_SECONDS", "Unified logical request deadline.", 300.0, 0.1, 3600.0),
    _string("FFMPEG_BIN", "FFmpeg executable name or path.", "ffmpeg", nonempty=True),
    _integer("FFMPEG_CONCURRENCY", "Maximum concurrent FFmpeg processes.", 2, 1, 8),
    _string("FFPROBE_BIN", "ffprobe executable name or path.", "ffprobe", nonempty=True),
    _integer("DRAFT_MIN_STAGE_COUNT", "Minimum draft stage count.", 2, 1, 1000),
    _float("DRAFT_MIN_STAGE_RATIO", "Minimum draft stage ratio.", 0.80, 0.01, 1.0),
    _integer("READY_MIN_STAGE_COUNT", "Minimum ready stage count.", 5, 1, 1000),
    _float("READY_MIN_STAGE_RATIO", "Minimum ready stage ratio.", 0.95, 0.01, 1.0),
)

_ADVANCED_SETTING_NAMES = frozenset(
    {
        "TIKHUB_AUTH_HEADER",
        "TIKHUB_AUTH_SCHEME",
        "TIKHUB_EXTRA_QUERY",
        "TIKHUB_ITEMS_PATH",
        "TIKHUB_VIDEO_ID_PATH",
        "TIKHUB_VIDEO_TITLE_PATH",
        "TIKHUB_VIDEO_PUBLISHED_AT_PATH",
        "TIKHUB_VIDEO_DOWNLOAD_URL_PATH",
        "TIKHUB_VIDEO_SOURCE_URL_PATH",
        "ALI_ASR_AUDIO_FORMAT",
        "ALI_ASR_RESPONSE_FORMAT",
        "ALI_ASR_MIME_TYPE",
        "ALI_ASR_COMPATIBLE_API",
        "ALI_ASR_ENABLE_ITN",
        "ALI_ASR_TIMEOUT_SECONDS",
        "ALI_ASR_MAX_BASE64_AUDIO_BYTES",
        "ALI_ASR_RETRY",
        "ALI_ASR_POLL_SECONDS",
        "ALI_ASR_POLL_DEADLINE_SECONDS",
        "ALI_ASR_WAIT_MODE",
        "ALI_ASR_AUDIO_URL_TEMPLATE",
        "AUDIO_PUBLIC_URL_BASE",
        "ASR_SAMPLE_RATE",
        "ASR_MP3_BITRATE",
        "ASR_SEGMENT_SECONDS",
        "ALI_OSS_ENDPOINT",
        "ALI_OSS_BUCKET",
        "ALI_OSS_ACCESS_KEY_ID",
        "ALI_OSS_ACCESS_KEY_SECRET",
        "ALI_OSS_PREFIX",
        "ALI_OSS_SIGNED_URL_EXPIRES",
        "ALI_OSS_LIFECYCLE_POLICY",
        "ALI_OSS_FAILURE_RETENTION_SECONDS",
        "DOWNLOAD_HEADER_TIMEOUT_SECONDS",
        "DOWNLOAD_DEADLINE_SECONDS",
        "MEDIA_PROBE_TIMEOUT_SECONDS",
        "HTTP_TIMEOUT_SECONDS",
        "PROVIDER_RETRY_MAX_ATTEMPTS",
        "PROVIDER_RETRY_BASE_SECONDS",
        "PROVIDER_RETRY_MAX_SECONDS",
        "PROVIDER_RETRY_JITTER_RATIO",
        "PROVIDER_REQUEST_DEADLINE_SECONDS",
        "FFMPEG_BIN",
        "FFPROBE_BIN",
        "DRAFT_MIN_STAGE_COUNT",
        "DRAFT_MIN_STAGE_RATIO",
        "READY_MIN_STAGE_COUNT",
        "READY_MIN_STAGE_RATIO",
    }
)
_DEPRECATED_SETTINGS = MappingProxyType(
    {
        "ALI_ASR_RETRY": "PROVIDER_RETRY_MAX_ATTEMPTS",
    }
)


def _setting_group(name: str) -> SettingGroup:
    if name.startswith("TIKHUB_"):
        return SettingGroup.TIKHUB
    if name.startswith("ALI_OSS_"):
        return SettingGroup.OSS
    if name.startswith(("ALI_ASR_", "DASHSCOPE_", "ASR_")) or name == "AUDIO_PUBLIC_URL_BASE":
        return SettingGroup.ASR
    if name.startswith("PROVIDER_RETRY_") or name == "PROVIDER_REQUEST_DEADLINE_SECONDS":
        return SettingGroup.RECOVERY
    if name.startswith(("DRAFT_MIN_", "READY_MIN_")):
        return SettingGroup.QUALITY
    return SettingGroup.RUNTIME


def _annotate_setting(spec: SettingSpec) -> SettingSpec:
    status = SettingStatus.ACTIVE
    replacement_name = _DEPRECATED_SETTINGS.get(spec.name)
    if replacement_name is not None:
        status = SettingStatus.DEPRECATED
    return replace(
        spec,
        group=_setting_group(spec.name),
        tier=(
            SettingTier.ADVANCED
            if spec.name in _ADVANCED_SETTING_NAMES
            else SettingTier.STANDARD
        ),
        status=status,
        replacement=replacement_name,
    )


SETTING_SPECS = tuple(_annotate_setting(spec) for spec in _BASE_SETTING_SPECS)

TIKHUB_APP_V3_PRESET = MappingProxyType(
    {
        "TIKHUB_API_BASE": "https://api.tikhub.io",
        "TIKHUB_CREATOR_VIDEOS_ENDPOINT": "/api/v1/douyin/app/v3/fetch_user_post_videos",
        "TIKHUB_SOURCE_URL_PARAM": "sec_user_id",
        "TIKHUB_LIMIT_PARAM": "count",
        "TIKHUB_EXTRA_QUERY": "max_cursor=0&sort_type=0",
    }
)

_SPECS_BY_NAME = MappingProxyType({spec.name: spec for spec in SETTING_SPECS})
CONFIG_KEYS = tuple(spec.name for spec in SETTING_SPECS)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _canonical_text(value: SettingValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, float):
        return format(value, ".15g")
    if value is None:
        return ""
    return str(value)


DEFAULT_ENV = MappingProxyType(
    {
        spec.name: _canonical_text(spec.default)
        for spec in SETTING_SPECS
        if spec.default is not None
    }
)


def setting_spec(name: str) -> SettingSpec:
    try:
        return _SPECS_BY_NAME[name]
    except KeyError as error:
        raise KeyError(f"unknown setting: {name}") from error


def _validate_url(name: str, value: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise SettingsError(f"{name} must be a valid absolute HTTP(S) endpoint") from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None and not 1 <= port <= 65535
        or parsed.fragment
    ):
        raise SettingsError(f"{name} must be an absolute HTTP(S) endpoint without credentials or fragments")


def _validate_relative_endpoint(name: str, value: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    if (
        parsed.scheme
        or parsed.netloc
        or value.startswith("//")
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or any(segment in {".", ".."} for segment in path_segments)
        or any(ord(character) < 32 for character in value)
    ):
        raise SettingsError(f"{name} must be a relative endpoint path without query or fragment")


def _parse_value(spec: SettingSpec, raw: object) -> SettingValue:
    if raw is None or isinstance(raw, str) and not raw.strip():
        if spec.optional:
            return None
        raise SettingsError(f"{spec.name} must not be empty")

    if spec.value_type is SettingType.STRING:
        if not isinstance(raw, (str, Path)):
            raise SettingsError(f"{spec.name} must be a string")
        value: SettingValue = str(raw).strip()
        if spec.nonempty and not value:
            raise SettingsError(f"{spec.name} must not be empty")
    elif spec.value_type is SettingType.BOOLEAN:
        if isinstance(raw, bool):
            value = raw
        elif isinstance(raw, str) and raw.strip().lower() in _TRUE_VALUES | _FALSE_VALUES:
            value = raw.strip().lower() in _TRUE_VALUES
        else:
            raise SettingsError(
                f"{spec.name} must be a boolean: true/false, yes/no, on/off, or 1/0"
            )
    elif spec.value_type is SettingType.INTEGER:
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise SettingsError(f"{spec.name} must be an integer")
        text = str(raw).strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            raise SettingsError(f"{spec.name} must be an integer")
        value = int(text)
    elif spec.value_type is SettingType.FLOAT:
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise SettingsError(f"{spec.name} must be a finite number")
        try:
            value = float(str(raw).strip())
        except ValueError as error:
            raise SettingsError(f"{spec.name} must be a finite number") from error
        if not math.isfinite(value):
            raise SettingsError(f"{spec.name} must be a finite number")
    elif spec.value_type is SettingType.ENUM:
        if spec.enum_type is None:
            raise RuntimeError(f"{spec.name} enum metadata is incomplete")
        try:
            value = raw if isinstance(raw, spec.enum_type) else spec.enum_type(str(raw).strip().lower())
        except ValueError as error:
            choices = ", ".join(member.value for member in spec.enum_type)
            raise SettingsError(f"{spec.name} must be one of: {choices}") from error
    else:  # pragma: no cover - guarded by the closed enum
        raise RuntimeError(f"unsupported setting type for {spec.name}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if spec.minimum is not None and value < spec.minimum or spec.maximum is not None and value > spec.maximum:
            raise SettingsError(f"{spec.name} must be between {spec.minimum} and {spec.maximum}; got {value}")
    if isinstance(value, str) and spec.endpoint_kind == "url":
        _validate_url(spec.name, value)
    if isinstance(value, str) and spec.endpoint_kind == "relative":
        _validate_relative_endpoint(spec.name, value)
    return value


def _json_value(value: SettingValue) -> str | int | float | bool | None:
    return value.value if isinstance(value, StrEnum) else value


@dataclass(frozen=True, repr=False)
class Settings(Mapping[str, SettingValue]):
    _values: Mapping[str, SettingValue]
    _sources: Mapping[str, str]

    @classmethod
    def from_mapping(cls, values: Mapping[str, object], *, source: str = "mapping") -> "Settings":
        return cls._from_layers(((source, values),))

    @classmethod
    def _from_layers(
        cls,
        layers: tuple[tuple[str, Mapping[str, object]], ...],
    ) -> "Settings":
        parsed: dict[str, SettingValue] = {}
        sources: dict[str, str] = {}
        for spec in SETTING_SPECS:
            if spec.default is not None:
                parsed[spec.name] = _parse_value(spec, spec.default)
                sources[spec.name] = "default"
            elif spec.optional:
                parsed[spec.name] = None
                sources[spec.name] = "default"
        for label, layer in layers:
            for name, raw in layer.items():
                retirement = RETIRED_SETTING_GUIDANCE.get(name)
                if retirement is not None and label != "environment":
                    raise SettingsError(f"{name} was removed; {retirement}")
                layer_spec = _SPECS_BY_NAME.get(name)
                if layer_spec is None:
                    continue
                parsed[name] = _parse_value(layer_spec, raw)
                sources[name] = label
        if (
            sources.get("ALI_ASR_RETRY") != "default"
            and sources.get("PROVIDER_RETRY_MAX_ATTEMPTS") == "default"
        ):
            parsed["PROVIDER_RETRY_MAX_ATTEMPTS"] = parsed["ALI_ASR_RETRY"]
            sources["PROVIDER_RETRY_MAX_ATTEMPTS"] = "ALI_ASR_RETRY compatibility"
        if sources.get("ALI_ASR_MODEL") == "default":
            provider = parsed["ALI_ASR_PROVIDER"]
            if not isinstance(provider, AsrProvider):  # pragma: no cover - enum parser invariant
                raise RuntimeError("ALI_ASR_PROVIDER did not parse as AsrProvider")
            parsed["ALI_ASR_MODEL"] = default_asr_model(provider)
        instance = cls(MappingProxyType(parsed), MappingProxyType(sources))
        instance._validate_relationships()
        return instance

    def __getitem__(self, name: str) -> SettingValue:
        try:
            return self._values[name]
        except KeyError as error:
            raise KeyError(f"unknown setting: {name}") from error

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        configured_count = sum(source != "default" for source in self._sources.values())
        return f"Settings(schema_version={SETTINGS_SCHEMA_VERSION}, configured_fields={configured_count})"

    def source_for(self, name: str) -> str:
        try:
            return self._sources[name]
        except KeyError as error:
            raise KeyError(f"unknown setting: {name}") from error

    def integer(self, name: str) -> int:
        value = self[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} is not an integer setting")
        return value

    def number(self, name: str) -> float:
        value = self[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} is not a numeric setting")
        return float(value)

    def as_env(self) -> dict[str, str]:
        return {
            name: _canonical_text(value)
            for name, value in self._values.items()
            if value is not None
        }

    def to_dict(self) -> dict[str, str | int | float | bool | None]:
        values = {
            spec.name: _json_value(self._values[spec.name])
            for spec in SETTING_SPECS
            if not spec.secret and self._values.get(spec.name) is not None
        }
        scrubbed = redaction.scrub_data(values, known_secrets=self.secret_values())
        if not isinstance(scrubbed, dict):  # pragma: no cover - scrub_data preserves mappings
            raise RuntimeError("settings serialization did not produce an object")
        return scrubbed

    def snapshot(self) -> dict[str, object]:
        safe_values = redaction.scrub_data(
            self.to_dict(),
            known_secrets=self.secret_values(),
        )
        return {"settings_schema_version": SETTINGS_SCHEMA_VERSION, **safe_values}

    def diagnostic_dict(self) -> dict[str, str | int | float | bool | None]:
        """Serialize every field for diagnostics without recoverable secret material."""

        values: dict[str, str | int | float | bool | None] = {}
        for spec in SETTING_SPECS:
            value = self._values.get(spec.name)
            if spec.secret:
                values[spec.name] = redaction.redact_secret(value)
            else:
                values[spec.name] = _json_value(value)
        scrubbed = redaction.scrub_data(values, known_secrets=self.secret_values())
        if not isinstance(scrubbed, dict):  # pragma: no cover - scrub_data preserves mappings
            raise RuntimeError("settings diagnostics did not produce an object")
        return scrubbed

    def secret_values(self) -> tuple[str, ...]:
        return tuple(
            str(value)
            for spec in SETTING_SPECS
            if spec.secret
            for value in (self._values.get(spec.name),)
            if value not in (None, "")
        )

    def install(self, environment: MutableMapping[str, str] | None = None) -> None:
        target = os.environ if environment is None else environment
        for spec in SETTING_SPECS:
            value = self._values.get(spec.name)
            if value is None:
                target.pop(spec.name, None)
            else:
                target[spec.name] = _canonical_text(value)

    def _validate_relationships(self) -> None:
        if self.integer("DOWNLOAD_DEADLINE_SECONDS") < self.integer("DOWNLOAD_HEADER_TIMEOUT_SECONDS"):
            raise SettingsError(
                "DOWNLOAD_DEADLINE_SECONDS must be greater than or equal to DOWNLOAD_HEADER_TIMEOUT_SECONDS"
            )
        if self.number("PROVIDER_RETRY_MAX_SECONDS") < self.number("PROVIDER_RETRY_BASE_SECONDS"):
            raise SettingsError(
                "PROVIDER_RETRY_MAX_SECONDS must be greater than or equal to PROVIDER_RETRY_BASE_SECONDS"
            )
        if self.integer("READY_MIN_STAGE_COUNT") < self.integer("DRAFT_MIN_STAGE_COUNT"):
            raise SettingsError("READY_MIN_STAGE_COUNT must be greater than or equal to DRAFT_MIN_STAGE_COUNT")
        if self.number("READY_MIN_STAGE_RATIO") < self.number("DRAFT_MIN_STAGE_RATIO"):
            raise SettingsError("READY_MIN_STAGE_RATIO must be greater than or equal to DRAFT_MIN_STAGE_RATIO")
        provider = self["ALI_ASR_PROVIDER"]
        if provider in {
            AsrProvider.OPENAI_COMPATIBLE,
            AsrProvider.COMPATIBLE,
            AsrProvider.QWEN_COMPATIBLE,
        }:
            in_flight = self.integer("ALI_ASR_CONCURRENCY") * self.integer("ALI_ASR_MAX_BASE64_AUDIO_BYTES")
            if in_flight > ASR_BASE64_RAW_INFLIGHT_BYTES_MAX:
                raise SettingsError(
                    "ALI_ASR_CONCURRENCY * ALI_ASR_MAX_BASE64_AUDIO_BYTES exceeds "
                    f"the {ASR_BASE64_RAW_INFLIGHT_BYTES_MAX}-byte raw in-flight memory budget"
                )
        try:
            environment = self.as_env()
            oss_lifecycle.load_policy(environment)
            oss_lifecycle.configured_prefix(environment)
        except oss_lifecycle.OSSLifecycleError as error:
            raise SettingsError(str(error)) from error


def read_env_file(path: Path) -> dict[str, str]:
    source = Path(path)
    if not source.is_file():
        raise SettingsError(f"env file not found: {source}")
    values: dict[str, str] = {}
    try:
        lines = source.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as error:
        raise SettingsError(f"cannot read env file: {source.name}") from error
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SettingsError(f"invalid env assignment at line {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY.fullmatch(key):
            raise SettingsError(f"invalid env key at line {line_number}")
        values[key] = value.strip().strip('"').strip("'")
    return values


def load_env_file(
    path: Path | None,
    environment: MutableMapping[str, str] | None = None,
) -> None:
    """Compatibility shim that uses the canonical parser and preserves setdefault semantics."""

    if path is None:
        return
    target = os.environ if environment is None else environment
    for key, value in read_env_file(path).items():
        target.setdefault(key, value)


def load_settings(
    env_file: Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    overrides: Mapping[str, object] | None = None,
    install: bool = False,
) -> Settings:
    """Load defaults < .env < process environment < explicit CLI overrides."""

    file_values: Mapping[str, object] = read_env_file(env_file) if env_file is not None else {}
    process_values: Mapping[str, object] = os.environ if environment is None else environment
    retired_overrides = sorted(set(overrides or ()) & set(RETIRED_SETTING_GUIDANCE))
    if retired_overrides:
        name = retired_overrides[0]
        raise SettingsError(f"{name} was removed; {RETIRED_SETTING_GUIDANCE[name]}")
    unknown_overrides = sorted(set(overrides or ()) - set(CONFIG_KEYS))
    if unknown_overrides:
        raise SettingsError("unknown CLI setting override(s): " + ", ".join(unknown_overrides))
    cli_values = {key: value for key, value in (overrides or {}).items() if value is not None}
    loaded = Settings._from_layers(
        (
            (".env", file_values),
            ("environment", process_values),
            ("cli", cli_values),
        )
    )
    if install:
        loaded.install()
    return loaded
