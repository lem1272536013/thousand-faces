"""SSRF policy contracts; every test is deterministic and network-free."""

from __future__ import annotations

import json
import ssl
from argparse import Namespace
from http.client import HTTPMessage
from pathlib import Path
from typing import Any

import pytest

import creator_pipeline
import provider_adapters
from network_policy import (
    DOUYIN_SOURCE,
    PROVIDER_ENDPOINT,
    UNTRUSTED_REMOTE,
    NetworkPolicyError,
    PinnedHTTPConnection,
    PinnedHTTPHandler,
    PinnedHTTPSConnection,
    PinnedHTTPSHandler,
    PolicyRedirectHandler,
    validate_redirect_url,
    validate_response_redirect,
    validate_url,
)


PUBLIC_V4 = "8.8.8.8"
PUBLIC_V6 = "2606:4700:4700::1111"


def public_resolver(_host: str, _port: int) -> list[str]:
    return [PUBLIC_V4, PUBLIC_V6]


@pytest.mark.parametrize(
    ("url", "expected_code"),
    [
        ("http://localhost:8080/admin", "HOST_BLOCKED"),
        ("http://127.0.0.1:8080/admin", "ADDRESS_BLOCKED"),
        ("http://2130706433/admin", "ADDRESS_BLOCKED"),
        ("http://0x7f000001/admin", "ADDRESS_BLOCKED"),
        ("http://127.1/admin", "ADDRESS_BLOCKED"),
        ("http://10.12.0.8/private", "ADDRESS_BLOCKED"),
        ("http://172.16.1.2/private", "ADDRESS_BLOCKED"),
        ("http://192.168.10.2/private", "ADDRESS_BLOCKED"),
        ("http://169.254.169.254/latest/meta-data/", "ADDRESS_BLOCKED"),
        ("http://[::1]/internal", "ADDRESS_BLOCKED"),
        ("http://[fc00::1]/internal", "ADDRESS_BLOCKED"),
        ("file:///etc/passwd", "SCHEME_NOT_ALLOWED"),
    ],
)
def test_local_private_metadata_and_non_http_targets_are_rejected(
    url: str,
    expected_code: str,
) -> None:
    with pytest.raises(NetworkPolicyError) as caught:
        validate_url(url, UNTRUSTED_REMOTE, resolver=public_resolver)

    assert caught.value.code == expected_code


def test_malicious_url_fixture_is_enforced_without_external_network(fixture_root: Path) -> None:
    payload = json.loads(
        (fixture_root / "security" / "malicious_urls.json").read_text(encoding="utf-8")
    )

    outcomes: dict[str, str] = {}
    for case in payload["cases"]:
        try:
            validate_url(case["url"], UNTRUSTED_REMOTE, resolver=public_resolver)
        except NetworkPolicyError as exc:
            outcomes[case["case_id"]] = exc.code
        else:
            outcomes[case["case_id"]] = "allowed"

    assert outcomes == {
        "loopback-v4": "ADDRESS_BLOCKED",
        "private-rfc1918": "ADDRESS_BLOCKED",
        "cloud-metadata": "ADDRESS_BLOCKED",
        "file-scheme": "SCHEME_NOT_ALLOWED",
        "loopback-v6": "ADDRESS_BLOCKED",
        "safe-control": "allowed",
    }


def test_douyin_source_uses_an_explicit_suffix_safe_allowlist() -> None:
    accepted = validate_url(
        "https://v.douyin.com/AbCdEf/",
        DOUYIN_SOURCE,
        resolver=public_resolver,
    )

    assert accepted.host == "v.douyin.com"
    with pytest.raises(NetworkPolicyError, match="HOST_NOT_ALLOWED"):
        validate_url(
            "https://douyin.com.attacker.example/profile",
            DOUYIN_SOURCE,
            resolver=public_resolver,
        )


def test_provider_endpoint_allows_arbitrary_public_host_but_forbids_userinfo() -> None:
    accepted = validate_url(
        "https://api.provider.example/v1",
        PROVIDER_ENDPOINT,
        resolver=public_resolver,
    )

    assert accepted.host == "api.provider.example"
    with pytest.raises(NetworkPolicyError) as caught:
        validate_url(
            "https://client:provider-secret@api.provider.example/v1?token=query-secret",
            PROVIDER_ENDPOINT,
            resolver=public_resolver,
        )
    message = str(caught.value)
    assert caught.value.code == "URL_CREDENTIALS_FORBIDDEN"
    assert "provider-secret" not in message
    assert "query-secret" not in message
    assert "/v1" not in message


def test_every_dns_answer_must_be_globally_routable() -> None:
    def mixed_resolver(_host: str, _port: int) -> list[str]:
        return [PUBLIC_V4, "10.0.0.9"]

    with pytest.raises(NetworkPolicyError, match="ADDRESS_BLOCKED"):
        validate_url(
            "https://cdn.public.example/video.mp4",
            UNTRUSTED_REMOTE,
            resolver=mixed_resolver,
        )


def test_dns_failure_is_closed_and_does_not_echo_query() -> None:
    def failing_resolver(_host: str, _port: int) -> list[str]:
        raise OSError("synthetic DNS failure")

    with pytest.raises(NetworkPolicyError) as caught:
        validate_url(
            "https://unresolved.example/media?signature=do-not-echo",
            UNTRUSTED_REMOTE,
            resolver=failing_resolver,
        )

    assert caught.value.code == "DNS_RESOLUTION_FAILED"
    assert "do-not-echo" not in str(caught.value)


def test_redirect_target_is_revalidated_before_following() -> None:
    with pytest.raises(NetworkPolicyError) as caught:
        validate_redirect_url(
            "https://media.public.example/start?signature=origin-secret",
            "http://169.254.169.254/latest/meta-data/?token=redirect-secret",
            UNTRUSTED_REMOTE,
            resolver=public_resolver,
        )

    assert caught.value.code == "ADDRESS_BLOCKED"
    assert "origin-secret" not in str(caught.value)
    assert "redirect-secret" not in str(caught.value)


def test_relative_public_redirect_remains_allowed() -> None:
    target = validate_redirect_url(
        "https://media.public.example/old/path",
        "/new/video.mp4?signature=kept-for-request",
        UNTRUSTED_REMOTE,
        resolver=public_resolver,
    )

    assert target.url == "https://media.public.example/new/video.mp4?signature=kept-for-request"


def test_requests_redirect_response_exposes_only_a_validated_target() -> None:
    class FakeResponse:
        status_code = 302
        headers = {"Location": "http://10.0.0.7/private?token=hidden"}

    with pytest.raises(NetworkPolicyError) as caught:
        validate_response_redirect(
            FakeResponse(),
            "https://api.provider.example/v1",
            PROVIDER_ENDPOINT,
            resolver=public_resolver,
        )

    assert caught.value.code == "ADDRESS_BLOCKED"
    assert "hidden" not in str(caught.value)


def test_urllib_redirect_handler_rechecks_target_before_following() -> None:
    handler = PolicyRedirectHandler(
        UNTRUSTED_REMOTE,
        public_resolver,
        allow_redirects=True,
    )
    request = provider_adapters.urllib.request.Request("https://media.public.example/start")

    with pytest.raises(NetworkPolicyError, match="ADDRESS_BLOCKED"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            HTTPMessage(),
            "http://127.0.0.1/internal?token=redirect-secret",
        )


def test_credentialed_urllib_request_validates_then_rejects_public_redirect() -> None:
    handler = PolicyRedirectHandler(
        PROVIDER_ENDPOINT,
        public_resolver,
        allow_redirects=False,
    )
    request = provider_adapters.urllib.request.Request("https://api.provider.example/v1")

    with pytest.raises(NetworkPolicyError) as caught:
        handler.redirect_request(
            request,
            None,
            307,
            "Temporary Redirect",
            HTTPMessage(),
            "https://api2.provider.example/v1?token=hidden",
        )

    assert caught.value.code == "REDIRECT_NOT_ALLOWED"
    assert "hidden" not in str(caught.value)


def test_public_douyin_short_link_can_resolve_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://www.douyin.com/user/sec-public-control"

    class FakeOpener:
        def open(self, request: Any, *, timeout: int) -> FakeResponse:
            assert request.full_url == "https://v.douyin.com/PublicControl/"
            assert timeout == 5
            return FakeResponse()

    monkeypatch.setattr("network_policy.system_resolver", public_resolver)
    monkeypatch.setattr(
        "network_policy.urllib.request.build_opener",
        lambda *handlers: FakeOpener()
        if any(isinstance(handler, PolicyRedirectHandler) for handler in handlers)
        and any(isinstance(handler, PinnedHTTPHandler) for handler in handlers)
        and any(isinstance(handler, PinnedHTTPSHandler) for handler in handlers)
        else pytest.fail("policy redirect handler was not installed"),
    )

    resolved = provider_adapters.resolve_douyin_url(
        "https://v.douyin.com/PublicControl/",
        timeout=5,
    )

    assert resolved == "sec-public-control"


def test_http_connection_uses_validated_ip_without_second_dns_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSocket:
        def setsockopt(self, *_args: object) -> None:
            return None

    destinations: list[tuple[str, int]] = []

    def fake_create_connection(
        address: tuple[str, int],
        _timeout: object,
        _source_address: tuple[str, int] | None,
    ) -> FakeSocket:
        destinations.append(address)
        return FakeSocket()

    monkeypatch.setattr("network_policy.socket.create_connection", fake_create_connection)
    connection = PinnedHTTPConnection(
        "media.public.example",
        port=80,
        pinned_addresses=(PUBLIC_V4,),
    )

    connection.connect()

    assert destinations == [(PUBLIC_V4, 80)]


def test_https_pinning_preserves_original_hostname_for_tls_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSocket:
        def setsockopt(self, *_args: object) -> None:
            return None

    class FakeTlsContext:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True

        def wrap_socket(self, sock: FakeSocket, *, server_hostname: str) -> FakeSocket:
            tls_hostnames.append(server_hostname)
            return sock

    destinations: list[tuple[str, int]] = []
    tls_hostnames: list[str] = []

    def fake_create_connection(
        address: tuple[str, int],
        _timeout: object,
        _source_address: tuple[str, int] | None,
    ) -> FakeSocket:
        destinations.append(address)
        return FakeSocket()

    monkeypatch.setattr("network_policy.socket.create_connection", fake_create_connection)
    connection = PinnedHTTPSConnection(
        "api.provider.example",
        port=443,
        context=FakeTlsContext(),
        pinned_addresses=(PUBLIC_V4,),
    )

    connection.connect()

    assert destinations == [(PUBLIC_V4, 443)]
    assert tls_hostnames == ["api.provider.example"]


def test_compatible_asr_private_endpoint_is_rejected_before_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests

    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"synthetic audio")
    output = tmp_path / "response.json"
    monkeypatch.setenv("ALI_ASR_API_KEY", "synthetic-key")
    monkeypatch.setenv(
        "ALI_ASR_ENDPOINT",
        "http://169.254.169.254/latest?token=endpoint-secret",
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *_args, **_kwargs: pytest.fail("private endpoint reached requests.post"),
    )

    with pytest.raises(NetworkPolicyError) as caught:
        provider_adapters.transcribe_compatible_audio_chat(
            Namespace(input=str(audio), output=str(output))
        )

    assert caught.value.code == "ADDRESS_BLOCKED"
    assert "endpoint-secret" not in str(caught.value)
    assert not output.exists()


def test_compatible_asr_rejects_redirect_without_replaying_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests

    class FakeRedirectResponse:
        status_code = 307
        headers = {"Location": "https://api2.provider.example/v1?token=redirect-secret"}
        text = ""

        def json(self) -> dict[str, object]:
            return {}

    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"synthetic audio")
    output = tmp_path / "response.json"
    monkeypatch.setenv("ALI_ASR_API_KEY", "synthetic-key")
    monkeypatch.setenv("ALI_ASR_ENDPOINT", "https://api.provider.example/v1")
    monkeypatch.setattr("network_policy.system_resolver", public_resolver)

    calls = 0

    def fake_post(*_args: object, **kwargs: object) -> FakeRedirectResponse:
        nonlocal calls
        calls += 1
        assert kwargs["allow_redirects"] is False
        return FakeRedirectResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(NetworkPolicyError) as caught:
        provider_adapters.transcribe_compatible_audio_chat(
            Namespace(input=str(audio), output=str(output))
        )

    assert calls == 1
    assert caught.value.code == "REDIRECT_NOT_ALLOWED"
    assert "redirect-secret" not in str(caught.value)
    assert not output.exists()


def test_download_rejects_private_url_before_opening_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_opener_is_built(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("unsafe URL reached the network opener")

    monkeypatch.setattr("network_policy.urllib.request.build_opener", fail_if_opener_is_built)
    monkeypatch.setattr(
        creator_pipeline.time,
        "sleep",
        lambda *_args: pytest.fail("policy rejection must not be retried"),
    )
    row = creator_pipeline.download_one(
        {
            "platform_video_id": "blocked-video",
            "download_url": "http://127.0.0.1/private?token=download-secret",
        },
        tmp_path,
        timeout=5,
        retries=3,
    )

    assert row["status"] == "failed"
    assert "ADDRESS_BLOCKED" in row["error"]
    assert "download-secret" not in row["error"]


def test_provider_json_fetch_rejects_private_url_before_opening_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_opener_is_built(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("unsafe URL reached the network opener")

    monkeypatch.setattr("network_policy.urllib.request.build_opener", fail_if_opener_is_built)
    with pytest.raises(NetworkPolicyError, match="ADDRESS_BLOCKED"):
        provider_adapters.read_json_url(
            "http://[::1]/provider?api_key=provider-secret",
            timeout=5,
        )


def test_tikhub_source_url_is_allowlisted_even_when_provider_accepts_urls() -> None:
    with pytest.raises(NetworkPolicyError, match="HOST_NOT_ALLOWED"):
        provider_adapters.resolve_tikhub_source_value(
            "https://attacker.example/user/forged-sec-uid",
            "url",
            timeout=5,
        )


def test_tikhub_source_rejects_non_http_url_but_allows_direct_sec_uid() -> None:
    with pytest.raises(NetworkPolicyError, match="SCHEME_NOT_ALLOWED"):
        provider_adapters.resolve_tikhub_source_value(
            "file:///user/secret-from-path",
            "sec_uid",
            timeout=5,
        )
    with pytest.raises(NetworkPolicyError, match="SCHEME_NOT_ALLOWED"):
        provider_adapters.resolve_tikhub_source_value(
            "v.douyin.com/MissingScheme/",
            "url",
            timeout=5,
        )

    assert (
        provider_adapters.resolve_tikhub_source_value(
            "MS4wLjABAAAA-synthetic-sec-uid",
            "sec_uid",
            timeout=5,
        )
        == "MS4wLjABAAAA-synthetic-sec-uid"
    )
