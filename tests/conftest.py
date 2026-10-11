"""Shared fixtures.

The SSRF guard resolves hosts via ``socket.getaddrinfo``. Tests use the
reserved ``*.test`` TLD with the ``responses`` HTTP mock (which intercepts
at the adapter level, never real DNS), so we stub the resolver to return a
public IP for ``*.test`` hosts. Everything else uses the real resolver.
"""
import socket
import pytest

_PUBLIC_IP = "93.184.216.34"  # example.com's v4 address; any public IP works


@pytest.fixture(autouse=True)
def resolve_test_hosts(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port=None, *args, **kwargs):
        if isinstance(host, str) and host.endswith(".test"):
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                     "", (_PUBLIC_IP, port or 0))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
