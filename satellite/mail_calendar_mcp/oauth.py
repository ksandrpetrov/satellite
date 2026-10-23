"""OAuth 2.1 for a personal calendar: browser login, PKCE and rotating tokens."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .settings import McpSettings

SCOPE = "calendar"
CODE_TTL = 300
LOGIN_TTL = 3600
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400


class OAuthState:
    """Small encrypted durable registry; pop is atomic even across workers."""

    def __init__(self, path: Path, encryption_key: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        path.chmod(0o600)
        self._cipher = Fernet(encryption_key.encode())
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS state (kind TEXT, key TEXT, expires REAL, data BLOB, PRIMARY KEY(kind,key))"
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def put(self, kind: str, key: str, data: dict[str, Any], ttl: int) -> None:
        encrypted = self._cipher.encrypt(json.dumps(data).encode())
        with self._lock, self._db:
            self._db.execute("DELETE FROM state WHERE expires < ?", (time.time(),))
            count = self._db.execute(
                "SELECT COUNT(*) FROM state WHERE kind = ?", (kind,)
            ).fetchone()[0]
            if count >= 2000:
                raise ValueError("Too many authorization requests")
            self._db.execute(
                "INSERT OR REPLACE INTO state VALUES (?,?,?,?)",
                (kind, self._key(key), time.time() + ttl, encrypted),
            )

    def get(self, kind: str, key: str, *, consume: bool = False) -> dict[str, Any] | None:
        with self._lock, self._db:
            # BEGIN IMMEDIATE makes one-time consumption safe across processes.
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(
                "SELECT expires,data FROM state WHERE kind=? AND key=?", (kind, self._key(key))
            ).fetchone()
            if row is None:
                return None
            if consume or row[0] <= time.time():
                self._db.execute("DELETE FROM state WHERE kind=? AND key=?", (kind, self._key(key)))
            if row[0] <= time.time():
                return None
            data = json.loads(self._cipher.decrypt(row[1]))
            if not isinstance(data, dict):
                raise ValueError("Invalid authorization state")
            return data

    def revoke_grant(self, grant: str) -> None:
        with self._lock, self._db:
            rows = self._db.execute(
                "SELECT kind,key,data FROM state WHERE kind IN ('access','refresh')"
            ).fetchall()
            for kind, key, payload in rows:
                if json.loads(self._cipher.decrypt(payload)).get("grant") == grant:
                    self._db.execute("DELETE FROM state WHERE kind=? AND key=?", (kind, key))


class MailOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, settings: McpSettings, state: OAuthState) -> None:
        self.settings = settings
        self.state = state

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self.state.get("client", client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id or not client_info.redirect_uris:
            raise RegistrationError("invalid_client_metadata")
        for uri in client_info.redirect_uris:
            url = urlsplit(str(uri))
            allowed = (
                url.scheme == "https"
                and url.hostname in {"chatgpt.com", "chat.openai.com", "platform.openai.com"}
                and url.port in {None, 443}
            )
            local = (
                url.scheme == "http"
                and url.hostname in {"localhost", "127.0.0.1", "::1"}
                and self.settings.base_url.startswith("http://")
            )
            if not (allowed or local) or url.username or url.password or url.fragment:
                raise RegistrationError("invalid_redirect_uri")
        self.state.put(
            "client", client_info.client_id, client_info.model_dump(mode="json"), 365 * 86400
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if params.resource not in {None, self.settings.resource_url}:
            raise AuthorizeError("invalid_request", "Resource does not match this MCP server")
        ticket = secrets.token_urlsafe(32)
        self.state.put(
            "pending",
            ticket,
            {
                "client_id": client.client_id,
                "params": params.model_dump(mode="json"),
                "attempts": 0,
            },
            LOGIN_TTL,
        )
        return self.settings.base_url + "/connect?ticket=" + ticket

    def prepare_form(self, ticket: str, csrf: str) -> None:
        pending = self.state.get("pending", ticket)
        if pending is None:
            raise ValueError("Authorization request expired")
        pending["csrf"] = hashlib.sha256(csrf.encode()).hexdigest()
        self.state.put("pending", ticket, pending, LOGIN_TTL)

    def check_form(self, ticket: str, csrf: str, cookie: str) -> dict[str, Any]:
        pending = self.state.get("pending", ticket, consume=True)
        if (
            pending is None
            or not csrf
            or not cookie
            or not hmac.compare_digest(csrf, cookie)
            or not hmac.compare_digest(
                hashlib.sha256(csrf.encode()).hexdigest(), pending.get("csrf", "")
            )
            or pending["attempts"] >= 5
        ):
            raise ValueError("Invalid authorization request")
        pending["attempts"] += 1
        return pending

    def complete_login(self, pending: dict[str, Any], account_id: int) -> str:
        params = AuthorizationParams.model_validate(pending["params"])
        code = AuthorizationCode(
            code=secrets.token_urlsafe(32),
            client_id=pending["client_id"],
            scopes=params.scopes or [SCOPE],
            expires_at=time.time() + CODE_TTL,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self.settings.resource_url,
            subject=str(account_id),
        )
        self.state.put("code", code.code, code.model_dump(mode="json"), CODE_TTL)
        return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        data = self.state.get("code", authorization_code)
        if not data or data["client_id"] != client.client_id:
            return None
        return AuthorizationCode.model_validate(data)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        data = self.state.get("code", authorization_code.code, consume=True)
        if not data or data["client_id"] != client.client_id or not data.get("subject"):
            raise TokenError("invalid_grant")
        return self._issue(client.client_id or "", data["subject"], data["scopes"])

    def _issue(
        self, client_id: str, subject: str, scopes: list[str], *, grant: str | None = None
    ) -> OAuthToken:
        grant = grant or secrets.token_urlsafe(32)
        access = AccessToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + ACCESS_TTL,
            resource=self.settings.resource_url,
            subject=subject,
        )
        refresh = RefreshToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + REFRESH_TTL,
            resource=self.settings.resource_url,
            subject=subject,
        )
        self.state.put(
            "access", access.token, {**access.model_dump(mode="json"), "grant": grant}, ACCESS_TTL
        )
        self.state.put(
            "refresh",
            refresh.token,
            {**refresh.model_dump(mode="json"), "grant": grant},
            REFRESH_TTL,
        )
        return OAuthToken(
            access_token=access.token,
            refresh_token=refresh.token,
            token_type="Bearer",
            expires_in=ACCESS_TTL,
            scope=" ".join(scopes),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        data = self.state.get("refresh", refresh_token)
        if not data or data["client_id"] != client.client_id:
            return None
        return RefreshToken.model_validate(data)

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        data = self.state.get("refresh", refresh_token.token, consume=True)
        if (
            not data
            or data["client_id"] != client.client_id
            or not set(scopes) <= set(data["scopes"])
        ):
            raise TokenError("invalid_grant")
        self.state.revoke_grant(data["grant"])
        return self._issue(data["client_id"], data["subject"], scopes, grant=data["grant"])

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = self.state.get("access", token)
        return AccessToken.model_validate(data) if data else None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        kind = "access" if isinstance(token, AccessToken) else "refresh"
        data = self.state.get(kind, token.token)
        if data:
            self.state.revoke_grant(data["grant"])
