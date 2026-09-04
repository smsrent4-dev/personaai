"""SSRF (server-side request forgery) protection for outbound fetches
of a URL a user supplied.

The vulnerability this closes: POST /knowledge/documents/url let any
authenticated user (not just a platform admin — any registered
business account) hand the backend an arbitrary URL, which the server
then fetched with redirects followed automatically and no restriction
on the target host. That's a classic SSRF: a user could point it at
cloud metadata endpoints (http://169.254.169.254/latest/meta-data/...
on AWS/GCP/Azure — often how cloud credentials get stolen), at
internal-only services on the backend's own network (an admin panel,
a database, another microservice with no auth because it "isn't
internet-facing"), or use response timing to port-scan the internal
network — and then, because the fetched content becomes a searchable
knowledge-base document, read the result back out through their own
agent's chat replies.

fetch_url_safely() is the fix: validates scheme, resolves the hostname
and rejects private/loopback/link-local/reserved/multicast addresses
(so DNS rebinding to an internal IP doesn't help either — the check is
against the resolved address actually being connected to, not just the
hostname string), and manually follows redirects one hop at a time,
re-validating the destination after every single one (redirects are
exactly how a naive "check the URL, then let the HTTP client follow
redirects itself" guard gets bypassed — the client doesn't re-run your
check).
"""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 5


class UnsafeURLError(Exception):
    """Raised when a URL (or a redirect target) resolves to something
    we refuse to fetch. The message is safe to show to the user —
    deliberately vague about *why* a given internal address is
    rejected, just that it is."""


def _reject_if_unsafe(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme '{parsed.scheme}' is not allowed — only http/https.")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname.")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve hostname '{parsed.hostname}'.") from exc

    for family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeURLError(
                f"'{parsed.hostname}' resolves to a non-public address and can't be fetched."
            )

    return url


async def fetch_url_safely(url: str, *, timeout: float = 20.0, user_agent: str = "PersonaAI-KnowledgeBot/1.0") -> httpx.Response:
    """Validates `url`, fetches it, and — critically — re-validates
    every redirect hop before following it (up to _MAX_REDIRECTS),
    rather than trusting httpx's own follow_redirects. Raises
    UnsafeURLError for a rejected URL/redirect, or httpx.HTTPError for
    an ordinary network/HTTP failure — callers already handle the
    latter for the un-guarded fetch, so only the former is new.
    """
    current_url = _reject_if_unsafe(url)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            resp = await client.get(current_url, headers={"User-Agent": user_agent})
            if resp.is_redirect:
                next_url = str(resp.next_request.url) if resp.next_request else resp.headers.get("location")
                if not next_url:
                    resp.raise_for_status()
                    return resp
                current_url = _reject_if_unsafe(next_url)
                continue
            resp.raise_for_status()
            return resp

    raise UnsafeURLError("Too many redirects.")
