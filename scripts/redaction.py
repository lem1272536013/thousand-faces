"""Central redaction policy for snapshots, diagnostics, and host-facing data."""

from __future__ import annotations

import os
import re
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REDACTED = "<redacted>"
REDACTED_PATH = "<redacted-path>"
REDACTED_URL = "<redacted-url>"

_SECRET_MARKERS = (
    "APIKEY",
    "APPKEY",
    "PRIVATEKEY",
    "ACCESSKEY",
    "ACCESSTOKEN",
    "REFRESHTOKEN",
    "AUTHORIZATION",
    "CREDENTIAL",
    "PASSWORD",
    "SIGNATURE",
    "SECRET",
    "COOKIE",
    "SESSION",
)
_SENSITIVE_QUERY_ALIASES = {
    "auth",
    "authorization",
    "code",
    "jwt",
    "key",
    "policy",
    "sig",
    "signed",
}
_EMBEDDED_URL = re.compile(r"https?://[^\s<>\"';,)\]}]+", re.IGNORECASE)
_AUTHORIZATION = re.compile(
    r"\bAuthorization\b(?:[\"']?\s*[:=]\s*[\"']?|\s+)(?:Bearer\s+)?(?:<redacted>|[^\s,;}\]>'\"]+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+(?:<redacted>|[^\s,;}\]>'\"]+)", re.IGNORECASE)
_SENSITIVE_LABEL = (
    r"(?:[A-Za-z0-9_-]*(?:api[_-]?key|app[_-]?key|access[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|token|password|secret|signature|credential|cookie|session)"
    r"[A-Za-z0-9_-]*)"
)
_QUOTED_SECRET = re.compile(
    rf"(?P<prefix>[\"']?{_SENSITIVE_LABEL}[\"']?\s*[:=]\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)
_PLAIN_SECRET = re.compile(
    rf"(?P<prefix>\b{_SENSITIVE_LABEL}\b\s*[:=]\s*)(?P<value>[^&\s,;}}\]]+)",
    re.IGNORECASE,
)
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/])[^;\r\n,\"'<>]+",
    re.IGNORECASE,
)
_POSIX_PRIVATE_PATH = re.compile(
    r"(?<![A-Za-z0-9])/(?:home|Users|root|private|var|tmp|mnt)/[^;\s,\"'<>]+",
    re.IGNORECASE,
)


def is_secret_key(key: object) -> bool:
    """Return whether a field name denotes credential material."""

    raw = str(key).strip().upper()
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    normalized = re.sub(r"[^A-Z0-9]+", "_", raw).strip("_")
    return (
        any(marker in compact for marker in _SECRET_MARKERS)
        or normalized == "TOKEN"
        or normalized.endswith("_TOKEN")
        or compact.endswith("TOKEN")
    )


def redact_secret(value: object) -> str:
    """Replace a configured secret without retaining length, prefix, or suffix."""

    return "" if value in (None, "") else REDACTED


def is_sensitive_query_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
    return is_secret_key(key) or normalized in _SENSITIVE_QUERY_ALIASES


def _safe_netloc(parsed: urllib.parse.SplitResult) -> str:
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL hostname is missing")
    display_host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    port = parsed.port
    return f"{display_host}:{port}" if port is not None else display_host


def redact_url(value: object) -> str:
    """Remove URL credentials, sensitive query parameters, and fragments."""

    raw = str(value).strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"}:
            return REDACTED_URL
        netloc = _safe_netloc(parsed)
    except (TypeError, ValueError):
        return REDACTED_URL

    safe_query = urllib.parse.urlencode(
        [
            (key, item_value)
            for key, item_value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if not is_sensitive_query_key(key)
        ],
        doseq=True,
    )
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path, safe_query, "")
    )


def configured_secrets(environment: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return configured credential values for exact-value scrubbing."""

    source = os.environ if environment is None else environment
    values = {
        str(value)
        for key, value in source.items()
        if is_secret_key(key) and value not in (None, "", REDACTED)
    }
    return tuple(sorted(values, key=len, reverse=True))


def scrub_text(
    value: object,
    *,
    known_secrets: Sequence[str] = (),
    limit: int | None = None,
) -> str:
    """Scrub credential patterns, signed URLs, and private absolute paths."""

    text = str(value)
    text = _EMBEDDED_URL.sub(lambda match: redact_url(match.group(0)), text)
    all_secrets = {
        secret
        for secret in (*configured_secrets(), *known_secrets)
        if secret and secret != REDACTED
    }
    for secret in sorted(all_secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _AUTHORIZATION.sub(f"Authorization: {REDACTED}", text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _QUOTED_SECRET.sub(
        lambda match: f"{match.group('prefix')}{match.group('quote')}{REDACTED}{match.group('quote')}",
        text,
    )
    text = _PLAIN_SECRET.sub(lambda match: f"{match.group('prefix')}{REDACTED}", text)
    text = _WINDOWS_ABSOLUTE_PATH.sub(REDACTED_PATH, text)
    text = _POSIX_PRIVATE_PATH.sub(REDACTED_PATH, text)
    return text[:limit] if limit is not None else text


def scrub_data(value: Any, *, known_secrets: Sequence[str] = ()) -> Any:
    """Recursively scrub an untrusted diagnostic payload."""

    if isinstance(value, Mapping):
        return {
            str(key): (
                redact_secret(item)
                if is_secret_key(key)
                else scrub_data(item, known_secrets=known_secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_data(item, known_secrets=known_secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_data(item, known_secrets=known_secrets) for item in value)
    if isinstance(value, str):
        return scrub_text(value, known_secrets=known_secrets)
    return value


def scrub_diagnostic_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Scrub only diagnostic fields while preserving operational path fields."""

    sanitized = dict(record)
    for key in ("error", "message", "note", "reason", "cleanup_issue"):
        value = sanitized.get(key)
        if isinstance(value, str):
            sanitized[key] = scrub_text(value, limit=2000)
    return sanitized


def redact_config(config: Mapping[str, str]) -> dict[str, str]:
    """Return a stable config snapshot with no recoverable credential fragments."""

    secrets = tuple(
        value
        for key, value in config.items()
        if is_secret_key(key) and value not in (None, "")
    )
    return {
        key: (
            redact_secret(value)
            if is_secret_key(key)
            else scrub_text(value, known_secrets=secrets)
        )
        for key, value in sorted(config.items())
    }


def safe_relative_path(path: Path, base: Path) -> str:
    """Render an operational path without exposing its absolute local prefix."""

    try:
        return str(path.resolve(strict=False).relative_to(base.resolve(strict=False)))
    except ValueError:
        return REDACTED_PATH
