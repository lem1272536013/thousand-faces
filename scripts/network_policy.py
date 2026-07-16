"""Fail-closed URL, DNS, and redirect policy for every external request."""

from __future__ import annotations

import ipaddress
import http.client
import socket
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from http.client import HTTPMessage
from typing import Any, Literal, Protocol, TypeAlias
from urllib.parse import urljoin, urlsplit


UrlPurpose: TypeAlias = Literal["douyin_source", "untrusted_remote", "provider_endpoint"]
DOUYIN_SOURCE: UrlPurpose = "douyin_source"
UNTRUSTED_REMOTE: UrlPurpose = "untrusted_remote"
PROVIDER_ENDPOINT: UrlPurpose = "provider_endpoint"

ALLOWED_SCHEMES = frozenset({"http", "https"})
DOUYIN_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com")
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

AddressResolver: TypeAlias = Callable[[str, int], Sequence[str]]
OriginKey: TypeAlias = tuple[str, str, int]


class RedirectResponse(Protocol):
    status_code: int
    headers: Any


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    """A URL whose syntax, purpose, host, and every DNS result passed policy."""

    url: str
    purpose: UrlPurpose
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


class NetworkPolicyError(ValueError):
    """A stable, sanitized rejection that never includes path/query/userinfo."""

    def __init__(self, code: str, message: str, url: object | None = None) -> None:
        self.code = code
        self.safe_target = safe_url_origin(url)
        suffix = f" target={self.safe_target}" if self.safe_target else ""
        super().__init__(f"{code}: {message}{suffix}")


def safe_url_origin(value: object | None) -> str:
    """Return only scheme/host/port for diagnostics, omitting all credentials and data."""

    if not isinstance(value, str) or not value:
        return ""
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return "<redacted-url>"
    if not scheme or not host:
        return "<redacted-url>"
    normalized_host = host.rstrip(".").lower()
    display_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{scheme}://{display_host}{port_suffix}"


def system_resolver(host: str, port: int) -> list[str]:
    """Resolve every stream address once for validation."""

    records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(record[4][0]) for record in records))


def _normalize_host(host: str) -> str:
    normalized = host.rstrip(".").lower()
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise NetworkPolicyError("HOST_INVALID", "URL hostname is not valid") from exc


def _host_is_allowlisted(host: str, suffixes: Sequence[str]) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    without_scope = value.split("%", 1)[0]
    try:
        return ipaddress.ip_address(without_scope)
    except ValueError as original_error:
        if ":" in without_scope:
            raise
        try:
            return ipaddress.ip_address(socket.inet_aton(without_scope))
        except OSError:
            raise original_error


def _validated_addresses(
    host: str,
    port: int,
    raw_url: str,
    resolver: AddressResolver,
) -> tuple[str, ...]:
    try:
        literal = _parse_ip(host)
    except ValueError:
        literal = None

    if literal is not None:
        resolved = [str(literal)]
    else:
        try:
            resolved = list(resolver(host, port))
        except Exception as exc:  # noqa: BLE001 - DNS backends expose platform-specific errors
            raise NetworkPolicyError(
                "DNS_RESOLUTION_FAILED",
                "hostname could not be resolved safely",
                raw_url,
            ) from exc
    if not resolved:
        raise NetworkPolicyError(
            "DNS_RESOLUTION_FAILED",
            "hostname resolved to no addresses",
            raw_url,
        )

    normalized: list[str] = []
    for value in resolved:
        try:
            address = _parse_ip(str(value))
        except ValueError as exc:
            raise NetworkPolicyError(
                "DNS_RESPONSE_INVALID",
                "resolver returned a non-IP address",
                raw_url,
            ) from exc
        if not address.is_global:
            raise NetworkPolicyError(
                "ADDRESS_BLOCKED",
                "loopback, private, link-local, reserved, and non-global addresses are forbidden",
                raw_url,
            )
        normalized.append(str(address))
    return tuple(dict.fromkeys(normalized))


def validate_url(
    value: object,
    purpose: UrlPurpose,
    *,
    resolver: AddressResolver | None = None,
) -> ValidatedUrl:
    """Validate a URL at the trust boundary and fail closed on every ambiguity."""

    if purpose not in {DOUYIN_SOURCE, UNTRUSTED_REMOTE, PROVIDER_ENDPOINT}:
        raise NetworkPolicyError("PURPOSE_INVALID", "unknown network URL purpose")
    if not isinstance(value, str) or not value.strip():
        raise NetworkPolicyError("URL_INVALID", "URL must be a non-empty string")
    raw_url = value.strip()
    try:
        parsed = urlsplit(raw_url)
        scheme = parsed.scheme.lower()
        host_value = parsed.hostname
        port = parsed.port
        has_userinfo = parsed.username is not None or parsed.password is not None
    except (TypeError, ValueError) as exc:
        raise NetworkPolicyError("URL_INVALID", "URL syntax is invalid", raw_url) from exc

    if scheme not in ALLOWED_SCHEMES:
        raise NetworkPolicyError(
            "SCHEME_NOT_ALLOWED",
            "only HTTP and HTTPS URLs are allowed",
            raw_url,
        )
    if has_userinfo:
        raise NetworkPolicyError(
            "URL_CREDENTIALS_FORBIDDEN",
            "embedded URL credentials are forbidden",
            raw_url,
        )
    if not host_value:
        raise NetworkPolicyError("HOST_INVALID", "URL hostname is required", raw_url)
    host = _normalize_host(host_value)
    if host in BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        raise NetworkPolicyError(
            "HOST_BLOCKED",
            "local hostnames are forbidden",
            raw_url,
        )
    if purpose == DOUYIN_SOURCE and not _host_is_allowlisted(host, DOUYIN_HOST_SUFFIXES):
        raise NetworkPolicyError(
            "HOST_NOT_ALLOWED",
            "source URL hostname is not in the Douyin allowlist",
            raw_url,
        )

    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    if not 1 <= effective_port <= 65535:
        raise NetworkPolicyError("PORT_INVALID", "URL port is outside the allowed range", raw_url)
    addresses = _validated_addresses(host, effective_port, raw_url, resolver or system_resolver)
    return ValidatedUrl(
        url=raw_url,
        purpose=purpose,
        scheme=scheme,
        host=host,
        port=effective_port,
        addresses=addresses,
    )


def validate_redirect_url(
    current_url: str,
    location: str,
    purpose: UrlPurpose,
    *,
    resolver: AddressResolver | None = None,
) -> ValidatedUrl:
    """Resolve a Location header and re-run the complete policy before following it."""

    if not isinstance(location, str) or not location.strip():
        raise NetworkPolicyError(
            "REDIRECT_LOCATION_INVALID",
            "redirect response has no usable Location header",
            current_url,
        )
    return validate_url(urljoin(current_url, location.strip()), purpose, resolver=resolver)


def validate_response_redirect(
    response: RedirectResponse,
    current_url: str,
    purpose: UrlPurpose,
    *,
    resolver: AddressResolver | None = None,
) -> ValidatedUrl | None:
    """Return a validated redirect target for requests-like responses, if present."""

    if int(response.status_code) not in REDIRECT_STATUS_CODES:
        return None
    location = response.headers.get("Location") or response.headers.get("location")
    return validate_redirect_url(current_url, location or "", purpose, resolver=resolver)


def _origin_key(validated: ValidatedUrl) -> OriginKey:
    return validated.scheme, validated.host, validated.port


def _origin_key_from_url(value: str) -> OriginKey:
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    host = _normalize_host(parsed.hostname or "")
    port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
    return scheme, host, port


def _connect_to_pinned_addresses(
    addresses: Sequence[str],
    port: int,
    timeout: object,
    source_address: tuple[str, int] | None,
) -> socket.socket:
    last_error: OSError | None = None
    for address in addresses:
        try:
            return socket.create_connection(
                (address, port),
                timeout,  # type: ignore[arg-type]
                source_address,
            )
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError("no validated network address is available")


class PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that never resolves the hostname a second time."""

    def __init__(
        self,
        host: str,
        *args: Any,
        pinned_addresses: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(host, *args, **kwargs)
        self._pinned_addresses = tuple(pinned_addresses)
        self._create_connection = self._create_pinned_connection

    def _create_pinned_connection(
        self,
        address: tuple[str, int],
        timeout: object,
        source_address: tuple[str, int] | None,
    ) -> socket.socket:
        return _connect_to_pinned_addresses(
            self._pinned_addresses,
            address[1],
            timeout,
            source_address,
        )


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to validated IPs while preserving host SNI/cert checks."""

    def __init__(
        self,
        host: str,
        *args: Any,
        pinned_addresses: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(host, *args, **kwargs)
        self._pinned_addresses = tuple(pinned_addresses)
        self._create_connection = self._create_pinned_connection

    def _create_pinned_connection(
        self,
        address: tuple[str, int],
        timeout: object,
        source_address: tuple[str, int] | None,
    ) -> socket.socket:
        return _connect_to_pinned_addresses(
            self._pinned_addresses,
            address[1],
            timeout,
            source_address,
        )


class _PinnedHandlerMixin:
    purpose: UrlPurpose
    resolver: AddressResolver
    address_book: dict[OriginKey, tuple[str, ...]]

    def _addresses_for(self, url: str) -> tuple[str, ...]:
        key = _origin_key_from_url(url)
        addresses = self.address_book.get(key)
        if addresses is not None:
            return addresses
        validated = validate_url(url, self.purpose, resolver=self.resolver)
        self.address_book[_origin_key(validated)] = validated.addresses
        return validated.addresses


class PinnedHTTPHandler(_PinnedHandlerMixin, urllib.request.HTTPHandler):
    """urllib HTTP handler backed by validated, pinned addresses."""

    def __init__(
        self,
        purpose: UrlPurpose,
        resolver: AddressResolver,
        address_book: dict[OriginKey, tuple[str, ...]],
    ) -> None:
        super().__init__()
        self.purpose = purpose
        self.resolver = resolver
        self.address_book = address_book

    def http_open(self, req: urllib.request.Request) -> Any:
        addresses = self._addresses_for(req.full_url)

        def connection_factory(host: str, **kwargs: Any) -> PinnedHTTPConnection:
            return PinnedHTTPConnection(host, pinned_addresses=addresses, **kwargs)

        return self.do_open(connection_factory, req)


class PinnedHTTPSHandler(_PinnedHandlerMixin, urllib.request.HTTPSHandler):
    """urllib HTTPS handler backed by pinned IPs and normal TLS verification."""

    _context: Any
    _check_hostname: Any

    def __init__(
        self,
        purpose: UrlPurpose,
        resolver: AddressResolver,
        address_book: dict[OriginKey, tuple[str, ...]],
    ) -> None:
        super().__init__()
        self.purpose = purpose
        self.resolver = resolver
        self.address_book = address_book

    def https_open(self, req: urllib.request.Request) -> Any:
        addresses = self._addresses_for(req.full_url)

        def connection_factory(host: str, **kwargs: Any) -> PinnedHTTPSConnection:
            return PinnedHTTPSConnection(host, pinned_addresses=addresses, **kwargs)

        return self.do_open(
            connection_factory,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


class PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib redirect handler that validates every target before a follow-up request."""

    def __init__(
        self,
        purpose: UrlPurpose,
        resolver: AddressResolver,
        *,
        allow_redirects: bool,
        address_book: dict[OriginKey, tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__()
        self.purpose = purpose
        self.resolver = resolver
        self.allow_redirects = allow_redirects
        self.address_book = address_book if address_book is not None else {}

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        target = validate_redirect_url(
            req.full_url,
            newurl,
            self.purpose,
            resolver=self.resolver,
        )
        self.address_book[_origin_key(target)] = target.addresses
        if not self.allow_redirects:
            raise NetworkPolicyError(
                "REDIRECT_NOT_ALLOWED",
                "redirects are forbidden for credentialed provider requests",
                target.url,
            )
        return super().redirect_request(req, fp, code, msg, headers, target.url)


def open_url(
    request_or_url: urllib.request.Request | str,
    *,
    purpose: UrlPurpose,
    timeout: int,
    resolver: AddressResolver | None = None,
    allow_redirects: bool = True,
) -> Any:
    """Validate an initial urllib request and every redirect target before I/O."""

    raw_url = (
        request_or_url.full_url
        if isinstance(request_or_url, urllib.request.Request)
        else request_or_url
    )
    active_resolver = resolver or system_resolver
    validated = validate_url(raw_url, purpose, resolver=active_resolver)
    address_book = {_origin_key(validated): validated.addresses}
    handler = PolicyRedirectHandler(
        purpose,
        active_resolver,
        allow_redirects=allow_redirects,
        address_book=address_book,
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        handler,
        PinnedHTTPHandler(purpose, active_resolver, address_book),
        PinnedHTTPSHandler(purpose, active_resolver, address_book),
    )
    return opener.open(request_or_url, timeout=timeout)


def reject_requests_redirect(
    response: RedirectResponse,
    current_url: str,
    purpose: UrlPurpose,
    *,
    resolver: AddressResolver | None = None,
) -> None:
    """Validate then reject requests-library redirects to avoid credential replay."""

    target = validate_response_redirect(
        response,
        current_url,
        purpose,
        resolver=resolver,
    )
    if target is not None:
        raise NetworkPolicyError(
            "REDIRECT_NOT_ALLOWED",
            "redirects are forbidden for credentialed provider requests",
            target.url,
        )
