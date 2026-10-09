"""Authentication strategies for HTTP sources."""
from __future__ import annotations
import base64, time
import requests


class NoAuth:
    """No authentication."""
    name = "none"

    def apply(self, session: requests.Session) -> None:
        return None

    def token_info(self) -> dict:
        return {}


class APIKeyAuth:
    """Static API key sent as a header or query parameter."""

    name = "api_key"

    def __init__(self, key: str, header: str | None = None, query_param: str | None = None):
        if not header and not query_param:
            raise ValueError("APIKeyAuth needs header or query_param")
        self.key = key
        self.header = header
        self.query_param = query_param

    def apply(self, session: requests.Session) -> None:
        if self.header:
            session.headers[self.header] = self.key

    def extra_params(self) -> dict:
        return {self.query_param: self.key} if self.query_param else {}

    def token_info(self) -> dict:
        return {"type": "api_key", "via": self.header or f"query:{self.query_param}"}


class BearerAuth:
    """Static bearer token."""

    name = "bearer"

    def __init__(self, token: str):
        self.token = token

    def apply(self, session: requests.Session) -> None:
        session.headers["Authorization"] = f"Bearer {self.token}"

    def token_info(self) -> dict:
        return {"type": "bearer"}


class OAuth2ClientCredentials:
    """OAuth2 client_credentials flow with automatic refresh before expiry."""

    name = "oauth2_client_credentials"

    def __init__(self, token_url: str, client_id: str, client_secret: str,
                 scopes: list[str] | None = None, refresh_margin_s: int = 60):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes or []
        self.refresh_margin_s = refresh_margin_s
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _fetch_token(self) -> None:
        resp = requests.post(
            self.token_url,
            data={"grant_type": "client_credentials",
                  "client_id": self.client_id,
                  "client_secret": self.client_secret,
                  "scope": " ".join(self.scopes)},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 3600))

    @property
    def token(self) -> str:
        if self._token is None or time.time() >= self._expires_at - self.refresh_margin_s:
            self._fetch_token()
        return self._token  # type: ignore[return-value]

    def apply(self, session: requests.Session) -> None:
        session.headers["Authorization"] = f"Bearer {self.token}"

    def token_info(self) -> dict:
        return {"type": "oauth2_client_credentials", "expires_at": self._expires_at}


def build_auth(spec: dict | None):
    """Factory: {'type': 'oauth2', ...} -> auth instance."""
    if not spec or spec.get("type", "none") == "none":
        return NoAuth()
    t = spec["type"]
    if t == "api_key":
        return APIKeyAuth(spec["key"], header=spec.get("header"), query_param=spec.get("query_param"))
    if t == "bearer":
        return BearerAuth(spec["token"])
    if t == "oauth2":
        return OAuth2ClientCredentials(
            token_url=spec["token_url"], client_id=spec["client_id"],
            client_secret=spec["client_secret"], scopes=spec.get("scopes"))
    raise ValueError(f"unknown auth type: {t}")
