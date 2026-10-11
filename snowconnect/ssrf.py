"""SSRF guard for spec-provided URLs.

Every URL a connector fetches comes from a spec file. In multi-tenant or
pipeline-of-pipelines deployments a spec may be authored by someone other
than the operator, so source URLs are treated as untrusted:

* scheme must be ``http``/``https``; no ``user:pass@`` userinfo;
* the host is resolved with ``socket.getaddrinfo`` and **every** resolved
  address must be public — private, loopback, link-local (incl. the cloud
  metadata IP 169.254.169.254), multicast, reserved and unspecified ranges
  are rejected via ``ipaddress`` flags (this also catches decimal/hex IP
  tricks, since the resolver normalises them);
* redirects are refused outright by the HTTP source (a redirect is a second
  URL that was never validated);
* requests time out (default 30 s, spec field ``timeout``) and responses are
  size-capped (default 50 MB, spec field ``max_response_bytes``).

Set ``"allow_private": true`` in a source spec to skip the address checks —
**local testing only** (e.g. the built-in demo's localhost mock API). It
allows loopback *and* link-local/metadata ranges, so never ship it in a
production spec.

Known limitation (see SECURITY.md): validation and the actual connection are
separate DNS lookups, so a hostile DNS server could rebind between the two
(TOCTOU). Run connectors in a network namespace that cannot reach internal
ranges for defence in depth.
"""
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlparse

from .errors import SSRFError

DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RESPONSE_BYTES = 50 * 1024 * 1024


def is_blocked_ip(ip_str: str) -> bool:
    """True if an address must never be fetched (public-internet policy)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable -> refuse
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 etc.
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def validate_url(url: str, allow_private: bool = False) -> list[str]:
    """Validate a spec-provided URL; return the resolved addresses.

    Raises ``SSRFError`` on policy violations and ``ValueError`` on
    malformed URLs (v0.1 contract).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"scheme not allowed: {parsed.scheme or '(none)'} (use http/https)")
    if parsed.username or parsed.password:
        raise SSRFError("userinfo in URL is not allowed")
    host = parsed.hostname
    if not host:
        raise SSRFError(f"URL has no host: {url!r}")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise SSRFError(f"invalid port in URL: {url!r}") from exc
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError(f"cannot resolve host {host!r}") from exc
    ips = sorted({str(info[4][0]) for info in infos})
    if not ips:
        raise SSRFError(f"no addresses for host {host!r}")
    if not allow_private:
        for ip_str in ips:
            if is_blocked_ip(ip_str):
                raise SSRFError(
                    f"host {host!r} resolves to blocked address {ip_str} "
                    "(private/loopback/link-local/multicast/reserved; set "
                    "\"allow_private\": true in the source spec for local testing only)")
    return ips
