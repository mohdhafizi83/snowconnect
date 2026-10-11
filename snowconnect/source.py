"""HTTP source with pagination, incremental watermarks, and retries."""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Iterator
import requests

from .auth import build_auth
from .errors import ConnectorError
from .ssrf import DEFAULT_MAX_RESPONSE_BYTES, DEFAULT_TIMEOUT_S, validate_url


class Watermark:
    """Persistent incremental-load state (last seen timestamp/id per stream)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def get(self, stream: str, default=None):
        return self._data.get(stream, default)

    def set(self, stream: str, value) -> None:
        self._data[stream] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=1))


class HttpSource:
    """Fetch records from a paginated JSON API.

    Supports page-number and cursor pagination, ISO-timestamp watermarking,
    nested record paths ('data.items'), and bounded retries with backoff.

    Security: the spec-provided ``base_url`` is validated through the SSRF
    guard (``snowconnect.ssrf``) at construction; redirects are refused and
    responses are size-capped (``max_response_bytes``, default 50 MB).
    """

    def __init__(self, spec: dict, state_path: str | Path = ".snowconnect/state.json",
                 session: requests.Session | None = None):
        self.allow_private = bool(spec.get("allow_private", False))
        validate_url(spec["base_url"], allow_private=self.allow_private)
        self.base_url = spec["base_url"].rstrip("/")
        self.path = spec.get("path", "/")
        self.method = spec.get("method", "GET").upper()
        self.headers = spec.get("headers", {})
        self.params = spec.get("params", {})
        self.records_path = spec.get("records_path")  # e.g. "data.items"
        self.pagination = spec.get("pagination", {"type": "none"})
        self.watermark_field = spec.get("watermark_field")  # field in record
        self.auth = build_auth(spec.get("auth"), allow_private=self.allow_private)
        self.max_retries = spec.get("max_retries", 3)
        self.timeout = spec.get("timeout", DEFAULT_TIMEOUT_S)
        self.max_response_bytes = int(spec.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES))
        self.state = Watermark(state_path)
        self.session = session or requests.Session()
        self.auth.apply(self.session)
        for k, v in self.headers.items():
            self.session.headers.setdefault(k, v)

    # ---- record extraction -------------------------------------------------
    def _dig(self, obj, dotted: str | None):
        if not dotted:
            return obj
        cur = obj
        for part in dotted.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list):
                try:
                    cur = cur[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return cur

    # ---- pagination --------------------------------------------------------
    def _pages(self, params: dict) -> Iterator[dict]:
        ptype = self.pagination.get("type", "none")
        page = 1
        cursor = None
        while True:
            p = dict(params)
            if ptype == "page":
                p[self.pagination.get("page_param", "page")] = page
            elif ptype == "cursor" and cursor:
                p[self.pagination.get("cursor_param", "cursor")] = cursor
            resp = self._request(p)
            payload = resp.json()
            yield payload
            if ptype == "page":
                page += 1
                if page > self.pagination.get("max_pages", 100):
                    return
                if not self._dig(payload, self.records_path):
                    return
            elif ptype == "cursor":
                cursor = self._dig(payload, self.pagination.get("cursor_path", "next_cursor"))
                if not cursor:
                    return
            else:
                return

    def _request(self, params: dict) -> requests.Response:
        extra = getattr(self.auth, "extra_params", lambda: {})()
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(
                    self.method, self.base_url + self.path,
                    params={**params, **self.params, **extra}, timeout=self.timeout,
                    allow_redirects=False)
                if resp.is_redirect or 300 <= resp.status_code < 400:
                    raise ConnectorError(
                        f"redirect refused from {self.base_url + self.path} "
                        f"(status {resp.status_code}); the redirect target is not "
                        "validated, so redirects are not followed")
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"retryable {resp.status_code}", response=resp)
                resp.raise_for_status()
                self._check_size(resp)
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as err:
                last_err = err
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 15))
        raise ConnectorError(f"source request failed after retries: {last_err}")

    def _check_size(self, resp: requests.Response) -> None:
        """Enforce max_response_bytes via Content-Length and streamed reads."""
        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > self.max_response_bytes:
            resp.close()
            raise ConnectorError(
                f"response too large: {declared} bytes exceeds cap of "
                f"{self.max_response_bytes} (spec field 'max_response_bytes')")
        if resp._content_consumed:
            if len(resp.content) > self.max_response_bytes:
                raise ConnectorError(
                    f"response too large: {len(resp.content)} bytes exceeds cap of "
                    f"{self.max_response_bytes} (spec field 'max_response_bytes')")
            return
        # not preloaded: read in chunks and abort as soon as the cap is passed
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=65536):
            buf.extend(chunk)
            if len(buf) > self.max_response_bytes:
                resp.close()
                raise ConnectorError(
                    f"response exceeds cap of {self.max_response_bytes} bytes "
                    "(spec field 'max_response_bytes')")
        resp._content = bytes(buf)

    # ---- public API ---------------------------------------------------------
    def stream(self, stream: str = "main") -> Iterator[dict]:
        """Yield raw records, stopping at the watermark (incremental load)."""
        wm_key = f"{self.base_url}{self.path}:{stream}"
        last_wm = self.state.get(wm_key)
        max_wm = last_wm
        params = {}
        if last_wm and self.pagination.get("watermark_param"):
            params[self.pagination["watermark_param"]] = last_wm
        for payload in self._pages(params):
            records = self._dig(payload, self.records_path) or []
            for rec in records:
                if self.watermark_field and last_wm is not None:
                    if str(rec.get(self.watermark_field, "")) <= str(last_wm):
                        continue
                yield rec
                if self.watermark_field:
                    v = str(rec.get(self.watermark_field, ""))
                    if v > str(max_wm or ""):
                        max_wm = v
        if self.watermark_field and max_wm is not None:
            self.state.set(wm_key, max_wm)
