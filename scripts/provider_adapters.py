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
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def load_env_file(path: Path | None) -> None:
    if not path:
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_url(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> object:
    request_headers = {"User-Agent": "Mozilla/5.0"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise SystemExit(f"HTTP {exc.code} from provider: {body}") from exc
    return json.loads(payload)


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


def resolve_douyin_url(value: str, timeout: int) -> str:
    """Resolve a Douyin short/profile URL and return the discovered sec_user_id."""
    direct = extract_douyin_sec_user_id(value)
    if direct:
        return direct

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return value
    if os.environ.get("TIKHUB_AUTO_RESOLVE_DOUYIN_URL", "true").lower() not in {"1", "true", "yes"}:
        return value

    try:
        import requests
    except ImportError:
        return value

    response = requests.get(
        value,
        allow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resolved = extract_douyin_sec_user_id(response.url)
    return resolved or value


def resolve_tikhub_source_value(value: str, source_param: str, timeout: int) -> str:
    if source_param not in {"sec_user_id", "sec_uid"}:
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
    auth_header = os.environ.get("TIKHUB_AUTH_HEADER", "Authorization")
    auth_scheme = os.environ.get("TIKHUB_AUTH_SCHEME", "Bearer")
    if not api_key:
        raise SystemExit("missing TIKHUB_API_KEY")
    return {auth_header: f"{auth_scheme} {api_key}".strip()}


def fetch_tikhub_creator_videos(args: argparse.Namespace) -> None:
    base = os.environ.get("TIKHUB_API_BASE")
    endpoint = os.environ.get("TIKHUB_CREATOR_VIDEOS_ENDPOINT")
    if not base or not endpoint:
        raise SystemExit("missing TIKHUB_API_BASE or TIKHUB_CREATOR_VIDEOS_ENDPOINT")

    source_param = os.environ.get("TIKHUB_SOURCE_URL_PARAM", "url")
    limit_param = os.environ.get("TIKHUB_LIMIT_PARAM", "limit")
    source_value = resolve_tikhub_source_value(args.source_url, source_param, args.timeout)
    params = {
        source_param: source_value,
        limit_param: str(args.limit),
    }

    extra_params = os.environ.get("TIKHUB_EXTRA_QUERY", "")
    if extra_params:
        params.update(dict(urllib.parse.parse_qsl(extra_params)))

    headers = tikhub_headers()
    cursor_param = os.environ.get("TIKHUB_CURSOR_PARAM", "max_cursor")
    pagination_enabled = os.environ.get("TIKHUB_ENABLE_PAGINATION", "true").lower() in {"1", "true", "yes"}
    max_pages = max(1, int(os.environ.get("TIKHUB_MAX_PAGES", "20")))

    pages = []
    previous_cursors: set[str] = set()
    while True:
        url = build_url(base, endpoint, params)
        payload = read_json_url(url, headers=headers, timeout=args.timeout)
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
        dashscope.base_http_api_url = base_url


def transcribe_aliyun_file_url(args: argparse.Namespace) -> None:
    try:
        from dashscope.audio.asr import Transcription
    except ImportError as exc:
        raise SystemExit("dashscope is required: pip install dashscope") from exc

    set_dashscope_config()

    model = os.environ.get("ALI_ASR_MODEL", "fun-asr")
    language = os.environ.get("ALI_ASR_LANGUAGE", "zh-CN")
    poll_seconds = int(os.environ.get("ALI_ASR_POLL_SECONDS", "5"))
    wait_mode = os.environ.get("ALI_ASR_WAIT_MODE", "wait")

    language_hints = [part.strip() for part in language.replace("zh-CN", "zh").split(",") if part.strip()]
    kwargs = {"model": model, "file_urls": [args.file_url]}
    if language_hints:
        kwargs["language_hints"] = language_hints
    task_response = Transcription.async_call(**kwargs)
    task_id = task_response.output.task_id

    if wait_mode == "poll":
        while True:
            response = Transcription.fetch(task=task_id)
            status = getattr(response.output, "task_status", "")
            if status in {"SUCCEEDED", "FAILED"}:
                break
            time.sleep(poll_seconds)
    else:
        response = Transcription.wait(task=task_id)

    output = json.loads(json.dumps(response.output, default=lambda value: getattr(value, "__dict__", str(value)), ensure_ascii=False))
    write_json(Path(args.output), output)

    transcription_url = None
    for item in output.get("results", []) or []:
        transcription_url = item.get("transcription_url") or transcription_url
    if transcription_url and args.result_json:
        result = read_json_url(transcription_url, timeout=args.timeout)
        write_json(Path(args.result_json), result)

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


def transcribe_compatible_audio_chat(args: argparse.Namespace) -> None:
    """Transcribe local audio through Qwen-ASR OpenAI-compatible chat completions."""
    try:
        import requests
    except ImportError as exc:
        raise SystemExit("requests is required: pip install requests") from exc

    api_key = os.environ.get("ALI_ASR_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    endpoint = os.environ.get("ALI_ASR_ENDPOINT") or os.environ.get("DASHSCOPE_BASE_HTTP_API_URL")
    model = os.environ.get("ALI_ASR_MODEL", "qwen-asr-flash")
    language = os.environ.get("ALI_ASR_LANGUAGE", "zh-CN")
    if not api_key:
        raise SystemExit("missing ALI_ASR_API_KEY or DASHSCOPE_API_KEY")
    if not endpoint:
        raise SystemExit("missing ALI_ASR_ENDPOINT or DASHSCOPE_BASE_HTTP_API_URL")

    audio_path = Path(args.input)
    if not audio_path.exists():
        raise SystemExit(f"audio file not found: {audio_path}")

    mime_type = os.environ.get("ALI_ASR_MIME_TYPE", "audio/mpeg")
    data_uri = f"data:{mime_type};base64,{base64.b64encode(audio_path.read_bytes()).decode('ascii')}"
    asr_options = {"enable_itn": os.environ.get("ALI_ASR_ENABLE_ITN", "false").lower() in {"1", "true", "yes"}}
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

    response_payload = {}
    response_status = 0
    retry_count = max(1, int(os.environ.get("ALI_ASR_RETRY", "3")))
    for attempt in range(1, retry_count + 1):
        response = requests.post(
            compatible_chat_completions_url(endpoint),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=int(os.environ.get("ALI_ASR_TIMEOUT_SECONDS", os.environ.get("HTTP_TIMEOUT_SECONDS", "180"))),
        )
        response_status = response.status_code
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"text": response.text}
        if response_status < 500 or attempt == retry_count:
            break
        time.sleep(min(attempt * 2, 10))
    if response_status >= 400:
        raise SystemExit(f"compatible ASR failed: {response_status} {json.dumps(response_payload, ensure_ascii=False)[:1000]}")

    write_json(Path(args.output), response_payload)
    print(args.output)


def transcribe_compatible_audio_transcriptions(args: argparse.Namespace) -> None:
    """Transcribe a local audio file with a multipart /audio/transcriptions endpoint."""
    try:
        import requests
    except ImportError as exc:
        raise SystemExit("requests is required: pip install requests") from exc

    api_key = os.environ.get("ALI_ASR_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    endpoint = os.environ.get("ALI_ASR_ENDPOINT") or os.environ.get("DASHSCOPE_BASE_HTTP_API_URL")
    model = os.environ.get("ALI_ASR_MODEL", "qwen-asr-flash")
    language = os.environ.get("ALI_ASR_LANGUAGE", "zh-CN")
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
    response_format = os.environ.get("ALI_ASR_RESPONSE_FORMAT", "json")
    if response_format:
        data["response_format"] = response_format

    with open(audio_path, "rb") as handle:
        response = requests.post(
            compatible_transcription_url(endpoint),
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files={"file": (audio_path.name, handle, os.environ.get("ALI_ASR_MIME_TYPE", "application/octet-stream"))},
            timeout=int(os.environ.get("HTTP_TIMEOUT_SECONDS", "60")),
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    if response.status_code >= 400:
        raise SystemExit(f"compatible ASR failed: {response.status_code} {json.dumps(payload, ensure_ascii=False)[:1000]}")

    write_json(Path(args.output), payload)
    print(args.output)


def transcribe_compatible_audio_file(args: argparse.Namespace) -> None:
    api_mode = os.environ.get("ALI_ASR_COMPATIBLE_API", "chat-completions").lower()
    if api_mode in {"audio-transcriptions", "transcriptions", "multipart"}:
        transcribe_compatible_audio_transcriptions(args)
    else:
        transcribe_compatible_audio_chat(args)


def oss_configured() -> bool:
    required = (
        "ALI_OSS_ENDPOINT",
        "ALI_OSS_BUCKET",
        "ALI_OSS_ACCESS_KEY_ID",
        "ALI_OSS_ACCESS_KEY_SECRET",
    )
    return all(os.environ.get(key) for key in required)


def upload_file_to_oss(file_path: Path, key: str | None = None) -> str:
    """Upload a local file to Aliyun OSS and return a signed GET URL."""
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
    bucket_name = os.environ["ALI_OSS_BUCKET"]
    access_key_id = os.environ["ALI_OSS_ACCESS_KEY_ID"]
    access_key_secret = os.environ["ALI_OSS_ACCESS_KEY_SECRET"]
    prefix = os.environ.get("ALI_OSS_PREFIX", "creator-agent-studio/audio").strip("/")
    expires = int(os.environ.get("ALI_OSS_SIGNED_URL_EXPIRES", "3600"))

    object_key = key or f"{prefix}/{file_path.name}"
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    bucket.put_object_from_file(object_key, str(file_path))
    return bucket.sign_url("GET", object_key, expires)


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
    oss.add_argument("--key", help="Optional OSS object key")

    args = parser.parse_args()
    load_env_file(Path(args.env).expanduser() if args.env else None)

    if args.command == "tikhub-creator-videos":
        fetch_tikhub_creator_videos(args)
    elif args.command == "aliyun-asr-url":
        transcribe_aliyun_file_url(args)
    elif args.command == "compatible-asr-file":
        transcribe_compatible_audio_file(args)
    elif args.command == "oss-upload":
        print(upload_file_to_oss(Path(args.input), args.key))


if __name__ == "__main__":
    main()
