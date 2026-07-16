#!/usr/bin/env python3
"""Provider adapters for TikHub and Aliyun ASR.

The adapters are deliberately thin. Endpoint paths, auth headers, models, and
response paths stay configurable so provider changes do not affect the research
or skill-generation stages.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import network_policy
import oss_lifecycle
import redaction
import retry_policy
import run_diagnostics
import settings
from input_validation import (
    InputValidationError,
    validate_asr_memory_budget,
)
from dashscope_polling import (
    DashScopePollingError,
    await_dashscope_task,
    poll_dashscope_task,
    safe_response_summary as _dashscope_safe_summary,
    validate_poll_timing as _validate_poll_timing,
)
from io_utils import atomic_write_json as write_json


__all__ = (
    "DashScopePollingError",
    "await_dashscope_task",
    "poll_dashscope_task",
)


def read_json_url(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    *,
    purpose: network_policy.UrlPurpose = network_policy.UNTRUSTED_REMOTE,
    allow_redirects: bool = True,
    retry: retry_policy.RetryPolicy | None = None,
) -> object:
    request_headers = {"User-Agent": "Mozilla/5.0"}
    request_headers.update(headers or {})

    def fetch(attempt_timeout: float) -> bytes:
        request = urllib.request.Request(url, headers=request_headers)
        with network_policy.open_url(
            request,
            purpose=purpose,
            timeout=attempt_timeout,  # type: ignore[arg-type]
            allow_redirects=allow_redirects,
        ) as response:
            return response.read()

    try:
        payload = retry_policy.execute_http(
            fetch,
            retry or provider_retry_policy(timeout),
            known_secrets=tuple((headers or {}).values()),
        ).decode("utf-8")
    except retry_policy.RetryError as exc:
        raise SystemExit(str(exc)) from None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise SystemExit(
            f"HTTP {exc.code} from provider: {redaction.scrub_text(body, limit=1000)}"
        ) from None
    return json.loads(payload)


def provider_retry_policy(timeout: int | float) -> retry_policy.RetryPolicy:
    """Build one validated policy while keeping provider entry points additive."""

    try:
        return retry_policy.policy_from_mapping(
            os.environ,
            request_timeout_seconds=float(timeout),
        )
    except ValueError as error:
        raise SystemExit(f"invalid provider retry configuration: {error}") from None


def build_url(base: str, endpoint: str, params: dict[str, str]) -> str:
    base = base.rstrip("/")
    endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value != ""})
    return f"{base}{endpoint}?{query}" if query else f"{base}{endpoint}"


def tikhub_data(payload: object) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return {}


def tikhub_item_list(data: dict) -> tuple[str, list]:
    for key in ("aweme_list", "videos", "items", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return key, value
    return "", []


def tikhub_has_more(data: dict) -> bool:
    value = data.get("has_more")
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def tikhub_item_id(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("aweme_id", "video_id", "item_id", "id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def merge_tikhub_pages(pages: list[object], cursor_param: str) -> object:
    if not pages:
        return {}

    merged = copy.deepcopy(pages[0])
    merged_data = tikhub_data(merged)
    first_key, _ = tikhub_item_list(merged_data)
    if not first_key:
        return merged

    seen: set[str] = set()
    merged_items = []
    page_summaries = []

    for index, page in enumerate(pages, start=1):
        data = tikhub_data(page)
        key, items = tikhub_item_list(data)
        if not key:
            continue
        page_summaries.append(
            {
                "page": index,
                "count": len(items),
                "has_more": data.get("has_more"),
                "max_cursor": data.get("max_cursor"),
                "min_cursor": data.get("min_cursor"),
            }
        )
        for item in items:
            item_id = tikhub_item_id(item)
            dedupe_key = item_id or json.dumps(item, ensure_ascii=False, sort_keys=True)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged_items.append(item)

    merged_data[first_key] = merged_items
    last_data = tikhub_data(pages[-1])
    for key in ("has_more", "max_cursor", "min_cursor", "request_item_cursor"):
        if key in last_data:
            merged_data[key] = last_data[key]
    if isinstance(merged, dict):
        merged["_pagination"] = {
            "enabled": True,
            "cursor_param": cursor_param,
            "pages": page_summaries,
            "merged_count": len(merged_items),
        }
    return merged


def extract_douyin_sec_user_id(value: str) -> str:
    """Extract sec_user_id/sec_uid from a Douyin profile URL if present."""
    parsed = urllib.parse.urlparse(value)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("sec_user_id", "sec_uid"):
        candidate = (query.get(key) or [""])[0]
        if candidate:
            return candidate

    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    for marker in ("share", "user"):
        if marker in parts:
            index = parts.index(marker)
            if marker == "share" and index + 2 < len(parts) and parts[index + 1] == "user":
                return parts[index + 2]
            if marker == "user" and index + 1 < len(parts):
                return parts[index + 1]
    return ""


def resolve_douyin_url(
    value: str,
    timeout: int,
    *,
    retry: retry_policy.RetryPolicy | None = None,
) -> str:
    """Resolve a Douyin short/profile URL and return the discovered sec_user_id."""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"", "http", "https"} or (parsed.netloc and not parsed.scheme):
        network_policy.validate_url(value, network_policy.DOUYIN_SOURCE)
    direct = extract_douyin_sec_user_id(value)
    if direct:
        network_policy.validate_url(value, network_policy.DOUYIN_SOURCE)
        return direct

    if parsed.scheme not in {"http", "https"}:
        return value
    if os.environ.get(
        "TIKHUB_AUTO_RESOLVE_DOUYIN_URL", settings.DEFAULT_ENV["TIKHUB_AUTO_RESOLVE_DOUYIN_URL"]
    ).lower() not in {"1", "true", "yes"}:
        network_policy.validate_url(value, network_policy.DOUYIN_SOURCE)
        return value

    def fetch(attempt_timeout: float) -> str:
        request = urllib.request.Request(value, headers={"User-Agent": "Mozilla/5.0"})
        with network_policy.open_url(
            request,
            purpose=network_policy.DOUYIN_SOURCE,
            timeout=attempt_timeout,  # type: ignore[arg-type]
        ) as response:
            return response.geturl()

    try:
        resolved_url = retry_policy.execute_http(
            fetch,
            retry or provider_retry_policy(timeout),
        )
    except retry_policy.RetryError as error:
        raise SystemExit(str(error)) from None
    resolved = extract_douyin_sec_user_id(resolved_url)
    return resolved or value


def resolve_tikhub_source_value(value: str, source_param: str, timeout: int) -> str:
    if source_param not in {"sec_user_id", "sec_uid"}:
        parsed = urllib.parse.urlparse(value)
        if source_param in {"url", "source_url"} or parsed.scheme or parsed.netloc:
            network_policy.validate_url(value, network_policy.DOUYIN_SOURCE)
        return value
    resolved = resolve_douyin_url(value, timeout)
    if resolved == value and urllib.parse.urlparse(value).scheme in {"http", "https"}:
        raise SystemExit(
            "could not resolve Douyin URL to sec_user_id; provide a sec_user_id directly "
            "or set TIKHUB_SOURCE_URL_PARAM to an endpoint parameter that accepts URLs"
        )
    return resolved


def tikhub_headers() -> dict[str, str]:
    api_key = os.environ.get("TIKHUB_API_KEY", "")
    auth_header = os.environ.get("TIKHUB_AUTH_HEADER", settings.DEFAULT_ENV["TIKHUB_AUTH_HEADER"])
    auth_scheme = os.environ.get("TIKHUB_AUTH_SCHEME", settings.DEFAULT_ENV["TIKHUB_AUTH_SCHEME"])
    if not api_key:
        raise SystemExit("missing TIKHUB_API_KEY")
    return {auth_header: f"{auth_scheme} {api_key}".strip()}


def fetch_tikhub_creator_videos(args: argparse.Namespace) -> None:
    base = os.environ.get("TIKHUB_API_BASE")
    endpoint = os.environ.get("TIKHUB_CREATOR_VIDEOS_ENDPOINT")
    if not base or not endpoint:
        raise SystemExit("missing TIKHUB_API_BASE or TIKHUB_CREATOR_VIDEOS_ENDPOINT")

    source_param = os.environ.get("TIKHUB_SOURCE_URL_PARAM", settings.DEFAULT_ENV["TIKHUB_SOURCE_URL_PARAM"])
    limit_param = os.environ.get("TIKHUB_LIMIT_PARAM", settings.DEFAULT_ENV["TIKHUB_LIMIT_PARAM"])
    source_value = resolve_tikhub_source_value(args.source_url, source_param, args.timeout)
    params = {
        source_param: source_value,
        limit_param: str(args.limit),
    }

    extra_params = os.environ.get("TIKHUB_EXTRA_QUERY", "")
    if extra_params:
        params.update(dict(urllib.parse.parse_qsl(extra_params)))

    headers = tikhub_headers()
    cursor_param = os.environ.get("TIKHUB_CURSOR_PARAM", settings.DEFAULT_ENV["TIKHUB_CURSOR_PARAM"])
    pagination_enabled = os.environ.get(
        "TIKHUB_ENABLE_PAGINATION", settings.DEFAULT_ENV["TIKHUB_ENABLE_PAGINATION"]
    ).lower() in {"1", "true", "yes"}
    max_pages = int(os.environ.get("TIKHUB_MAX_PAGES", settings.DEFAULT_ENV["TIKHUB_MAX_PAGES"]))

    pages = []
    previous_cursors: set[str] = set()
    while True:
        url = build_url(base, endpoint, params)
        payload = read_json_url(
            url,
            headers=headers,
            timeout=args.timeout,
            purpose=network_policy.PROVIDER_ENDPOINT,
            allow_redirects=False,
        )
        pages.append(payload)

        data = tikhub_data(payload)
        _, items = tikhub_item_list(data)
        merged_count = len(tikhub_item_list(tikhub_data(merge_tikhub_pages(pages, cursor_param)))[1])
        next_cursor = data.get(cursor_param) or data.get("max_cursor")
        next_cursor_text = "" if next_cursor in (None, "") else str(next_cursor)

        if not pagination_enabled:
            break
        if merged_count >= args.limit:
            break
        if not tikhub_has_more(data):
            break
        if not items:
            break
        if not next_cursor_text or next_cursor_text in previous_cursors:
            break
        if len(pages) >= max_pages:
            break

        previous_cursors.add(next_cursor_text)
        params[cursor_param] = next_cursor_text

    payload = merge_tikhub_pages(pages, cursor_param) if len(pages) > 1 else pages[0]
    write_json(Path(args.output), payload)
    print(args.output)


def set_dashscope_config() -> None:
    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("ALI_ASR_API_KEY")
    if not api_key:
        raise SystemExit("missing DASHSCOPE_API_KEY or ALI_ASR_API_KEY")

    import dashscope

    dashscope.api_key = api_key
    base_url = os.environ.get("DASHSCOPE_BASE_HTTP_API_URL") or os.environ.get("ALI_ASR_ENDPOINT")
    if base_url:
        network_policy.validate_url(base_url, network_policy.PROVIDER_ENDPOINT)
        dashscope.base_http_api_url = base_url


def transcribe_aliyun_file_url(args: argparse.Namespace) -> None:
    try:
        from dashscope.audio.asr import Transcription
    except ImportError as exc:
        raise SystemExit("dashscope is required: pip install dashscope") from exc

    network_policy.validate_url(args.file_url, network_policy.UNTRUSTED_REMOTE)
    set_dashscope_config()

    model = os.environ.get("ALI_ASR_MODEL", settings.default_asr_model(settings.AsrProvider.ALIYUN))
    language = os.environ.get("ALI_ASR_LANGUAGE", settings.DEFAULT_ENV["ALI_ASR_LANGUAGE"])
    try:
        poll_seconds = float(os.environ.get("ALI_ASR_POLL_SECONDS", settings.DEFAULT_ENV["ALI_ASR_POLL_SECONDS"]))
        poll_deadline = float(
            os.environ.get("ALI_ASR_POLL_DEADLINE_SECONDS", settings.DEFAULT_ENV["ALI_ASR_POLL_DEADLINE_SECONDS"])
        )
        _validate_poll_timing(poll_seconds, poll_deadline)
    except ValueError as error:
        raise SystemExit(f"invalid DashScope polling configuration: {error}") from None
    wait_mode = os.environ.get("ALI_ASR_WAIT_MODE", settings.DEFAULT_ENV["ALI_ASR_WAIT_MODE"])

    language_hints = [part.strip() for part in language.replace("zh-CN", "zh").split(",") if part.strip()]
    kwargs = {"model": model, "file_urls": [args.file_url]}
    if language_hints:
        kwargs["language_hints"] = language_hints
    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("ALI_ASR_API_KEY", "")
    request_policy = provider_retry_policy(args.timeout)
    known_secrets = (api_key, args.file_url)
    try:
        task_response = retry_policy.execute_http(
            lambda request_timeout: Transcription.async_call(
                **kwargs,
                request_timeout=request_timeout,
            ),
            request_policy,
            known_secrets=known_secrets,
        )
    except retry_policy.RetryError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        safe_error = redaction.scrub_text(
            error,
            known_secrets=known_secrets,
            limit=1000,
        )
        raise SystemExit(f"DashScope task submission failed: {safe_error}") from None

    task_output = getattr(task_response, "output", None)
    task_id = (
        task_output.get("task_id", "")
        if isinstance(task_output, dict)
        else getattr(task_output, "task_id", "")
    )
    if not str(task_id).strip():
        safe_summary = _dashscope_safe_summary(task_response, known_secrets)
        suffix = f": {safe_summary}" if safe_summary else ""
        raise SystemExit(f"DashScope task submission did not return a task_id{suffix}")

    def fetch_with_timeout(active_task_id: str, remaining: float) -> object:
        bounded_policy = replace(
            request_policy,
            request_timeout_seconds=min(request_policy.request_timeout_seconds, remaining),
            deadline_seconds=min(request_policy.deadline_seconds, remaining),
        )
        return retry_policy.execute_http(
            lambda request_timeout: Transcription.fetch(
                task=active_task_id,
                request_timeout=request_timeout,
            ),
            bounded_policy,
            known_secrets=known_secrets,
        )

    try:
        response = await_dashscope_task(
            Transcription,
            task_id=str(task_id),
            wait_mode=wait_mode,
            poll_seconds=poll_seconds,
            deadline_seconds=poll_deadline,
            known_secrets=known_secrets,
            fetch_with_timeout=fetch_with_timeout,
        )
    except (DashScopePollingError, retry_policy.RetryError, ValueError) as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        safe_error = redaction.scrub_text(
            error,
            known_secrets=known_secrets,
            limit=1000,
        )
        raise SystemExit(f"DashScope polling request failed: {safe_error}") from None

    response_output = getattr(response, "output", {})
    output = json.loads(json.dumps(response_output, default=lambda value: getattr(value, "__dict__", str(value)), ensure_ascii=False))

    transcription_url = None
    for item in output.get("results", []) or []:
        transcription_url = item.get("transcription_url") or transcription_url
    safe_output = redaction.scrub_data(output, known_secrets=(args.file_url,))
    write_json(Path(args.output), safe_output)
    if transcription_url and args.result_json:
        result = read_json_url(
            transcription_url,
            timeout=args.timeout,
            purpose=network_policy.UNTRUSTED_REMOTE,
        )
        safe_result = redaction.scrub_data(
            result,
            known_secrets=(args.file_url, transcription_url),
        )
        write_json(Path(args.result_json), safe_result)

    print(args.output)


def compatible_transcription_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/audio/transcriptions"):
        return endpoint
    return f"{endpoint}/audio/transcriptions"


def compatible_chat_completions_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/chat/completions"):
        return endpoint
    return f"{endpoint}/chat/completions"


def normalize_asr_language(language: str) -> str:
    mapping = {
        "zh-cn": "zh",
        "zh_cn": "zh",
        "cn": "zh",
    }
    lowered = language.strip().lower()
    return mapping.get(lowered, lowered)


def read_bounded_audio_for_base64(audio_path: Path) -> bytes:
    """Read at most one validated compatible-chat chunk before Base64 expansion."""

    try:
        _concurrency, max_bytes = validate_asr_memory_budget(os.environ)
    except InputValidationError as error:
        raise SystemExit(str(error)) from error
    try:
        with audio_path.open("rb") as stream:
            declared_size = os.fstat(stream.fileno()).st_size
            if declared_size > max_bytes:
                raise SystemExit(
                    "[ASR_AUDIO_TOO_LARGE] audio chunk "
                    f"{audio_path.name!r} is {declared_size} bytes; limit is "
                    f"{max_bytes}. Lower ASR_SEGMENT_SECONDS or use file-url ASR."
                )
            content = stream.read(max_bytes + 1)
    except OSError as error:
        raise SystemExit(
            f"[ASR_AUDIO_READ_ERROR] could not read audio chunk {audio_path.name!r}"
        ) from error
    if len(content) > max_bytes:
        raise SystemExit(
            "[ASR_AUDIO_TOO_LARGE] audio chunk grew beyond "
            f"{max_bytes} bytes while being read. Lower ASR_SEGMENT_SECONDS and retry."
        )
    if len(content) != declared_size:
        raise SystemExit(
            f"[ASR_AUDIO_CHANGED] audio chunk {audio_path.name!r} changed while being read"
        )
    return content


def transcribe_compatible_audio_chat(
    args: argparse.Namespace,
    *,
    retry: retry_policy.RetryPolicy | None = None,
) -> None:
    """Transcribe local audio through Qwen-ASR OpenAI-compatible chat completions."""
    try:
        import requests
    except ImportError as exc:
        raise SystemExit("requests is required: pip install requests") from exc

    api_key = os.environ.get("ALI_ASR_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    endpoint = os.environ.get("ALI_ASR_ENDPOINT") or os.environ.get("DASHSCOPE_BASE_HTTP_API_URL")
    model = os.environ.get(
        "ALI_ASR_MODEL",
        settings.default_asr_model(settings.AsrProvider.OPENAI_COMPATIBLE),
    )
    language = os.environ.get("ALI_ASR_LANGUAGE", settings.DEFAULT_ENV["ALI_ASR_LANGUAGE"])
    if not api_key:
        raise SystemExit("missing ALI_ASR_API_KEY or DASHSCOPE_API_KEY")
    if not endpoint:
        raise SystemExit("missing ALI_ASR_ENDPOINT or DASHSCOPE_BASE_HTTP_API_URL")

    audio_path = Path(args.input)
    if not audio_path.exists():
        raise SystemExit(f"audio file not found: {audio_path}")

    mime_type = os.environ.get("ALI_ASR_MIME_TYPE", settings.DEFAULT_ENV["ALI_ASR_MIME_TYPE"])
    audio_content = read_bounded_audio_for_base64(audio_path)
    data_uri = f"data:{mime_type};base64,{base64.b64encode(audio_content).decode('ascii')}"
    asr_options: dict[str, bool | str] = {
        "enable_itn": os.environ.get("ALI_ASR_ENABLE_ITN", settings.DEFAULT_ENV["ALI_ASR_ENABLE_ITN"]).lower()
        in {"1", "true", "yes"}
    }
    normalized_language = normalize_asr_language(language)
    if normalized_language and normalized_language not in {"auto", "none", "detect"}:
        asr_options["language"] = normalized_language
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            }
        ],
        "stream": False,
        "asr_options": asr_options,
    }

    request_url = compatible_chat_completions_url(endpoint)
    network_policy.validate_url(request_url, network_policy.PROVIDER_ENDPOINT)
    request_timeout = int(
        os.environ.get(
            "ALI_ASR_TIMEOUT_SECONDS",
            os.environ.get("HTTP_TIMEOUT_SECONDS", settings.DEFAULT_ENV["HTTP_TIMEOUT_SECONDS"]),
        )
    )

    def post(attempt_timeout: float) -> Any:
        response = requests.post(
            request_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=attempt_timeout,
            allow_redirects=False,
        )
        network_policy.reject_requests_redirect(
            response,
            request_url,
            network_policy.PROVIDER_ENDPOINT,
        )
        return response

    try:
        response = retry_policy.execute_http(
            post,
            retry or provider_retry_policy(request_timeout),
            known_secrets=(api_key,),
        )
    except retry_policy.RetryError as error:
        raise SystemExit(str(error)) from None
    response_status = response.status_code
    try:
        response_payload = response.json()
    except ValueError:
        response_payload = {"text": response.text}
    if response_status >= 400:
        safe_payload = redaction.scrub_data(response_payload, known_secrets=(api_key,))
        rendered = json.dumps(safe_payload, ensure_ascii=False)[:1000]
        raise SystemExit(f"compatible ASR failed: {response_status} {rendered}")

    write_json(Path(args.output), response_payload)
    print(args.output)


def transcribe_compatible_audio_transcriptions(
    args: argparse.Namespace,
    *,
    retry: retry_policy.RetryPolicy | None = None,
) -> None:
    """Transcribe a local audio file with a multipart /audio/transcriptions endpoint."""
    try:
        import requests
    except ImportError as exc:
        raise SystemExit("requests is required: pip install requests") from exc

    api_key = os.environ.get("ALI_ASR_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    endpoint = os.environ.get("ALI_ASR_ENDPOINT") or os.environ.get("DASHSCOPE_BASE_HTTP_API_URL")
    model = os.environ.get(
        "ALI_ASR_MODEL",
        settings.default_asr_model(settings.AsrProvider.OPENAI_COMPATIBLE),
    )
    language = os.environ.get("ALI_ASR_LANGUAGE", settings.DEFAULT_ENV["ALI_ASR_LANGUAGE"])
    if not api_key:
        raise SystemExit("missing ALI_ASR_API_KEY or DASHSCOPE_API_KEY")
    if not endpoint:
        raise SystemExit("missing ALI_ASR_ENDPOINT or DASHSCOPE_BASE_HTTP_API_URL")

    audio_path = Path(args.input)
    if not audio_path.exists():
        raise SystemExit(f"audio file not found: {audio_path}")

    data = {"model": model}
    if language:
        data["language"] = language
    response_format = os.environ.get("ALI_ASR_RESPONSE_FORMAT", settings.DEFAULT_ENV["ALI_ASR_RESPONSE_FORMAT"])
    if response_format:
        data["response_format"] = response_format

    request_url = compatible_transcription_url(endpoint)
    network_policy.validate_url(request_url, network_policy.PROVIDER_ENDPOINT)
    request_timeout = int(os.environ.get("HTTP_TIMEOUT_SECONDS", settings.DEFAULT_ENV["HTTP_TIMEOUT_SECONDS"]))

    def post(attempt_timeout: float) -> Any:
        with open(audio_path, "rb") as handle:
            response = requests.post(
                request_url,
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files={
                    "file": (
                        audio_path.name,
                        handle,
                        os.environ.get("ALI_ASR_MIME_TYPE", settings.DEFAULT_ENV["ALI_ASR_MIME_TYPE"]),
                    )
                },
                timeout=attempt_timeout,
                allow_redirects=False,
            )
        network_policy.reject_requests_redirect(
            response,
            request_url,
            network_policy.PROVIDER_ENDPOINT,
        )
        return response

    try:
        response = retry_policy.execute_http(
            post,
            retry or provider_retry_policy(request_timeout),
            known_secrets=(api_key,),
        )
    except retry_policy.RetryError as error:
        raise SystemExit(str(error)) from None
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    if response.status_code >= 400:
        safe_payload = redaction.scrub_data(payload, known_secrets=(api_key,))
        rendered = json.dumps(safe_payload, ensure_ascii=False)[:1000]
        raise SystemExit(f"compatible ASR failed: {response.status_code} {rendered}")

    write_json(Path(args.output), payload)
    print(args.output)


def transcribe_compatible_audio_file(
    args: argparse.Namespace,
    *,
    retry: retry_policy.RetryPolicy | None = None,
) -> None:
    api_mode = os.environ.get(
        "ALI_ASR_COMPATIBLE_API", settings.DEFAULT_ENV["ALI_ASR_COMPATIBLE_API"]
    ).lower()
    if api_mode in {"audio-transcriptions", "transcriptions", "multipart"}:
        transcribe_compatible_audio_transcriptions(args, retry=retry)
    else:
        transcribe_compatible_audio_chat(args, retry=retry)


def oss_configured() -> bool:
    required = (
        "ALI_OSS_ENDPOINT",
        "ALI_OSS_BUCKET",
        "ALI_OSS_ACCESS_KEY_ID",
        "ALI_OSS_ACCESS_KEY_SECRET",
    )
    return all(os.environ.get(key) for key in required)


def _oss_bucket() -> tuple[Any, str]:
    """Build a configured OSS bucket without exposing credentials to callers."""
    try:
        import oss2
    except ImportError as exc:
        raise SystemExit("oss2 is required for OSS upload: pip install oss2") from exc

    if not oss_configured():
        raise SystemExit(
            "missing OSS config: ALI_OSS_ENDPOINT, ALI_OSS_BUCKET, "
            "ALI_OSS_ACCESS_KEY_ID, ALI_OSS_ACCESS_KEY_SECRET"
        )

    endpoint = os.environ["ALI_OSS_ENDPOINT"]
    network_policy.validate_url(endpoint, network_policy.PROVIDER_ENDPOINT)
    bucket_name = os.environ["ALI_OSS_BUCKET"]
    access_key_id = os.environ["ALI_OSS_ACCESS_KEY_ID"]
    access_key_secret = os.environ["ALI_OSS_ACCESS_KEY_SECRET"]
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    return bucket, bucket_name


def upload_file_to_oss(
    file_path: Path,
    *,
    context: oss_lifecycle.OSSObjectContext,
    retry: retry_policy.RetryPolicy | None = None,
) -> oss_lifecycle.OSSUpload:
    """Upload a content-addressed audio object and return its in-memory handle."""
    source = Path(file_path)
    object_key, digest = oss_lifecycle.object_key_for_file(source, context=context)
    raw_expires = os.environ.get("ALI_OSS_SIGNED_URL_EXPIRES", settings.DEFAULT_ENV["ALI_OSS_SIGNED_URL_EXPIRES"])
    try:
        expires = int(raw_expires)
    except ValueError as error:
        raise oss_lifecycle.OSSLifecycleError(
            "ALI_OSS_SIGNED_URL_EXPIRES must be an integer"
        ) from error
    if not 60 <= expires <= 3600:
        raise oss_lifecycle.OSSLifecycleError(
            "ALI_OSS_SIGNED_URL_EXPIRES must be between 60 and 3600"
        )
    bucket, bucket_name = _oss_bucket()
    active_retry = retry or provider_retry_policy(
        int(os.environ.get("HTTP_TIMEOUT_SECONDS", settings.DEFAULT_ENV["HTTP_TIMEOUT_SECONDS"]))
    )
    _execute_oss_call(
        lambda attempt_timeout: _oss_operation_with_timeout(
            bucket,
            attempt_timeout,
            lambda: bucket.put_object_from_file(object_key, str(source)),
        ),
        action="upload",
        retry=active_retry,
    )
    try:
        signed_url = bucket.sign_url("GET", object_key, expires)
    except Exception as signing_error:
        try:
            _execute_oss_call(
                lambda attempt_timeout: _oss_operation_with_timeout(
                    bucket,
                    attempt_timeout,
                    lambda: bucket.delete_object(object_key),
                ),
                action="rollback cleanup",
                retry=active_retry,
            )
        except Exception as cleanup_error:
            safe_error = redaction.scrub_text(cleanup_error, limit=1000)
            raise RuntimeError(
                f"OSS URL signing failed and rollback cleanup failed: {safe_error}"
            ) from None
        safe_error = redaction.scrub_text(signing_error, limit=1000)
        raise RuntimeError(f"OSS URL signing failed: {safe_error}") from None
    upload = oss_lifecycle.build_upload(
        source,
        context=context,
        bucket_name=bucket_name,
        signed_url=signed_url,
    )
    if upload.source_sha256 != digest or upload.object_key != object_key:
        try:
            _execute_oss_call(
                lambda attempt_timeout: _oss_operation_with_timeout(
                    bucket,
                    attempt_timeout,
                    lambda: bucket.delete_object(object_key),
                ),
                action="rollback cleanup",
                retry=active_retry,
            )
        except Exception as cleanup_error:
            safe_error = redaction.scrub_text(cleanup_error, limit=1000)
            raise RuntimeError(
                "OSS upload identity changed and rollback cleanup failed: "
                f"{safe_error}"
            ) from None
        raise RuntimeError("OSS upload identity changed while the object was being published")
    return upload


def _execute_oss_call(
    operation: Callable[[float], object],
    *,
    action: str,
    retry: retry_policy.RetryPolicy,
) -> object:
    known_secrets = (
        os.environ.get("ALI_OSS_ACCESS_KEY_ID", ""),
        os.environ.get("ALI_OSS_ACCESS_KEY_SECRET", ""),
    )
    try:
        result = retry_policy.execute_http(
            operation,
            retry,
            known_secrets=known_secrets,
        )
    except retry_policy.RetryError as error:
        raise RuntimeError(f"OSS {action} failed: {error}") from None
    except Exception as error:
        safe_error = redaction.scrub_text(
            error,
            known_secrets=known_secrets,
            limit=1000,
        )
        raise RuntimeError(f"OSS {action} failed: {safe_error}") from None
    status = int(getattr(result, "status", 0))
    if status < 200 or status >= 300:
        raise RuntimeError(f"OSS {action} failed with HTTP status {status}")
    return result


def _oss_operation_with_timeout(
    bucket: Any,
    attempt_timeout: float,
    operation: Callable[[], object],
) -> object:
    bucket.timeout = attempt_timeout
    return operation()


def delete_oss_object(
    object_key: str,
    *,
    retry: retry_policy.RetryPolicy | None = None,
) -> None:
    """Delete only objects inside the configured managed OSS prefix."""
    oss_lifecycle.assert_managed_object_key(object_key)
    bucket, _bucket_name = _oss_bucket()
    active_retry = retry or provider_retry_policy(
        int(os.environ.get("HTTP_TIMEOUT_SECONDS", settings.DEFAULT_ENV["HTTP_TIMEOUT_SECONDS"]))
    )
    _execute_oss_call(
        lambda attempt_timeout: _oss_operation_with_timeout(
            bucket,
            attempt_timeout,
            lambda: bucket.delete_object(object_key),
        ),
        action="deletion",
        retry=active_retry,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run provider-specific adapter calls")
    parser.add_argument("--env", help="Path to .env file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tikhub = subparsers.add_parser("tikhub-creator-videos")
    tikhub.add_argument("--source-url", required=True)
    tikhub.add_argument("--limit", type=int, default=100)
    tikhub.add_argument("--output", required=True)
    tikhub.add_argument("--timeout", type=int, default=60)

    asr = subparsers.add_parser("aliyun-asr-url")
    asr.add_argument("--file-url", required=True, help="Publicly accessible audio URL")
    asr.add_argument("--output", required=True, help="Task response JSON path")
    asr.add_argument("--result-json", help="Downloaded transcription result JSON path")
    asr.add_argument("--timeout", type=int, default=60)

    compatible_asr = subparsers.add_parser("compatible-asr-file")
    compatible_asr.add_argument("--input", required=True, help="Local audio file")
    compatible_asr.add_argument("--output", required=True, help="Transcription response JSON path")

    oss = subparsers.add_parser("oss-upload")
    oss.add_argument("--input", required=True, help="Local file to upload")
    oss.add_argument("--run-dir", required=True, help="Owning pipeline run directory")
    oss.add_argument("--video-id", required=True, help="Validated local video artifact ID")
    oss.add_argument("--chunk-id", default="full", help="Validated audio chunk ID")

    oss_cleanup = subparsers.add_parser("oss-cleanup")
    oss_cleanup.add_argument("--run-dir", required=True, help="Pipeline run directory to sweep")

    args = parser.parse_args()
    try:
        settings.load_settings(
            Path(args.env).expanduser() if args.env else None,
            install=True,
        )
    except settings.SettingsError as error:
        parser.error(str(error))
    if args.command in {"oss-upload", "oss-cleanup"}:
        try:
            run_diagnostics.require_current_run(Path(args.run_dir))
        except run_diagnostics.RunFormatError as error:
            parser.error(str(error))

    if args.command == "tikhub-creator-videos":
        fetch_tikhub_creator_videos(args)
    elif args.command == "aliyun-asr-url":
        transcribe_aliyun_file_url(args)
    elif args.command == "compatible-asr-file":
        transcribe_compatible_audio_file(args)
    elif args.command == "oss-upload":
        run_dir = Path(args.run_dir)
        context = oss_lifecycle.OSSObjectContext.from_run_dir(
            run_dir,
            video_id=args.video_id,
            chunk_id=args.chunk_id,
        )
        upload = upload_file_to_oss(Path(args.input), context=context)
        oss_lifecycle.register_upload(run_dir, upload)
        print(
            json.dumps(
                {
                    "bucket": upload.bucket_name,
                    "object_key": upload.object_key,
                    "source_sha256": upload.source_sha256,
                    "cleanup_status": "pending",
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "oss-cleanup":
        outcomes = oss_lifecycle.cleanup_expired_uploads(
            Path(args.run_dir),
            delete_callback=delete_oss_object,
        )
        print(
            json.dumps(
                {
                    "processed": len(outcomes),
                    "statuses": [outcome.cleanup_status for outcome in outcomes],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
