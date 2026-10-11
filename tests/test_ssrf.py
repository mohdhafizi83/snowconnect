"""SSRF guard tests: accept/reject matrix, redirects, size cap, timeout, CLI hygiene.

No real network: hosts use the reserved ``*.test`` TLD (resolver stubbed in
conftest) with the ``responses`` mock, or literal IP literals.
"""
import json
import pytest
import responses

from snowconnect import ConnectorError, HttpSource, SSRFError
from snowconnect.auth import OAuth2ClientCredentials
from snowconnect.cli import main
from snowconnect.ssrf import DEFAULT_MAX_RESPONSE_BYTES, DEFAULT_TIMEOUT_S, validate_url


def _src_spec(base_url, **extra):
    s = {"base_url": base_url, "path": "/x", "max_retries": 0}
    s.update(extra)
    return s


# ---------- resolver policy matrix ----------
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/x",          # loopback
    "http://localhost:8080/x",          # loopback by hostname
    "http://10.0.0.5/x",                # RFC1918
    "http://192.168.1.1/x",             # RFC1918
    "http://172.16.0.9/x",              # RFC1918
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
    "http://0.0.0.0/x",                 # unspecified
    "http://[::1]/x",                   # IPv6 loopback
    "http://[fc00::1]/x",               # IPv6 unique-local
    "http://224.0.0.1/x",               # multicast
    "http://2130706433/x",              # decimal-encoded 127.0.0.1
    "http://user:pass@api.test/x",      # userinfo smuggling
    "file:///etc/passwd",               # non-http scheme
    "gopher://api.test/x",              # non-http scheme
])
def test_ssrf_rejects(url):
    with pytest.raises((SSRFError, ValueError)):
        validate_url(url)


def test_ssrf_rejects_unresolvable_host():
    with pytest.raises(SSRFError, match="cannot resolve"):
        validate_url("http://no-such-host-zzz9999.invalid/x")


def test_ssrf_accepts_public_host():
    assert validate_url("https://api.test/x")  # stubbed to a public IP


def test_httpsource_blocks_loopback_by_default():
    with pytest.raises(SSRFError):
        HttpSource(_src_spec("http://127.0.0.1:9"))


def test_httpsource_blocks_metadata_ip_by_default():
    with pytest.raises(SSRFError):
        HttpSource(_src_spec("http://169.254.169.254"))


def test_httpsource_allow_private_allows_loopback():
    # documented local-testing opt-in (used by the demo's mock API)
    src = HttpSource(_src_spec("http://127.0.0.1:9", allow_private=True))
    assert src.allow_private is True


def test_allow_private_documented_to_allow_metadata_too():
    # allow_private skips ALL address checks — incl. link-local/metadata.
    # This is why it is documented as local-testing-only (see SECURITY.md).
    HttpSource(_src_spec("http://169.254.169.254", allow_private=True))


def test_oauth_token_url_is_guarded():
    with pytest.raises(SSRFError):
        OAuth2ClientCredentials("http://169.254.169.254/token", "c", "s")


def test_error_types_backwards_compatible():
    assert issubclass(SSRFError, ValueError)   # v0.1 raised ValueError
    assert issubclass(ConnectorError, RuntimeError)


# ---------- redirects ----------
@responses.activate
def test_redirect_refused():
    responses.add(responses.GET, "https://api.test/r", status=302,
                  headers={"Location": "http://169.254.169.254/"})
    src = HttpSource(_src_spec("https://api.test", path="/r"))
    with pytest.raises(ConnectorError, match="redirect refused"):
        list(src.stream())


# ---------- response size cap ----------
@responses.activate
def test_size_cap_rejects_declared_content_length():
    responses.add(responses.GET, "https://api.test/big", body="x" * 100,
                  status=200, headers={"Content-Length": "100"})
    src = HttpSource(_src_spec("https://api.test", path="/big", max_response_bytes=50))
    with pytest.raises(ConnectorError, match="too large"):
        list(src.stream())


@responses.activate
def test_size_cap_rejects_undeclared_body():
    # no Content-Length header: cap enforced while reading the body
    responses.add(responses.GET, "https://api.test/big", body="x" * 200, status=200)
    src = HttpSource(_src_spec("https://api.test", path="/big", max_response_bytes=50))
    with pytest.raises(ConnectorError, match="too large"):
        list(src.stream())


@responses.activate
def test_size_cap_allows_under_cap():
    responses.add(responses.GET, "https://api.test/ok",
                  json={"data": [{"id": "1"}]}, status=200)
    src = HttpSource(_src_spec("https://api.test", path="/ok", records_path="data"))
    assert [r["id"] for r in src.stream()] == ["1"]


# ---------- timeout configuration ----------
def test_timeout_defaults_and_spec_override():
    assert HttpSource(_src_spec("https://api.test")).timeout == DEFAULT_TIMEOUT_S == 30
    assert HttpSource(_src_spec("https://api.test", timeout=5)).timeout == 5
    assert HttpSource(_src_spec("https://api.test")).max_response_bytes == DEFAULT_MAX_RESPONSE_BYTES


# ---------- CLI error hygiene ----------
def _bad_spec(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"name": "x", "source": {"base_url": "http://127.0.0.1:9"}}))
    return str(p)


def test_cli_clean_error_no_traceback(tmp_path, capsys):
    rc = main(["run", _bad_spec(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "snowconnect: error:" in captured.err
    assert "Traceback" not in captured.err


def test_cli_verbose_shows_traceback(tmp_path, capsys):
    rc = main(["--verbose", "run", _bad_spec(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Traceback" in captured.err
