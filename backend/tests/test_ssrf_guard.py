"""SSRF guard for user-supplied URLs (POST /knowledge/documents/url).

These test the validation logic (_reject_if_unsafe) directly against
IP-literal hostnames — socket.getaddrinfo on an IP literal is a local,
offline operation (no real DNS/network call), so these run without
network access and without mocking.
"""
import pytest

from app.core.ssrf_guard import UnsafeURLError, _reject_if_unsafe


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",  # loopback
        "http://localhost/",  # loopback via DNS-less resolution on most systems
        "http://10.0.0.5/",  # RFC1918 private
        "http://172.16.0.1/",  # RFC1918 private
        "http://192.168.1.1/",  # RFC1918 private
        "http://169.254.169.254/latest/meta-data/",  # link-local — the classic cloud-metadata SSRF target
        "http://0.0.0.0/",  # unspecified
        "http://224.0.0.1/",  # multicast
    ],
)
def test_rejects_non_public_addresses(url):
    with pytest.raises(UnsafeURLError):
        _reject_if_unsafe(url)


def test_rejects_disallowed_scheme():
    with pytest.raises(UnsafeURLError):
        _reject_if_unsafe("file:///etc/passwd")


def test_rejects_ftp_scheme():
    with pytest.raises(UnsafeURLError):
        _reject_if_unsafe("ftp://example.com/file")


def test_allows_public_ip_literal():
    # 8.8.8.8 is a real public address (Google DNS) — getaddrinfo on an
    # IP literal doesn't touch the network, so this is a safe, offline
    # assertion that public addresses are NOT rejected.
    _reject_if_unsafe("http://8.8.8.8/")  # should not raise
