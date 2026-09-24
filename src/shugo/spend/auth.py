"""Optional login for the spend proxy, for when it's reachable from the internet.

Set as environment variables (e.g. Fly.io secrets), never in spend.yaml:

  SHUGO_DASHBOARD_PASSWORD  people: the dashboard, STOP/RESUME, export and
                            status need this password (HTTP Basic auth, any
                            username). Only safe over HTTPS.
  SHUGO_AGENT_TOKEN         agents: calls to /v1/* must send it in an
                            `x-shugo-token` header, so strangers can't route
                            their own traffic through your proxy.

Unset means open, which is fine on 127.0.0.1.
"""
from __future__ import annotations

import base64
import binascii
import os
import secrets
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

PASSWORD_ENV = "SHUGO_DASHBOARD_PASSWORD"
AGENT_TOKEN_ENV = "SHUGO_AGENT_TOKEN"
AGENT_TOKEN_HEADER = "x-shugo-token"
OPEN_PATHS = {"/healthz"}


def _same(given: str, expected: str) -> bool:
    return secrets.compare_digest(given.encode(), expected.encode())


def _basic_password(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    return decoded.partition(":")[2]


def protection() -> tuple[str | None, str | None]:
    return os.environ.get(PASSWORD_ENV) or None, os.environ.get(AGENT_TOKEN_ENV) or None


def install(app: FastAPI) -> None:
    password, agent_token = protection()
    if not password and not agent_token:
        return

    @app.middleware("http")
    async def require_login(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path in OPEN_PATHS:
            return await call_next(request)
        if path.startswith("/v1/"):
            if agent_token and not _same(request.headers.get(AGENT_TOKEN_HEADER, ""), agent_token):
                return JSONResponse(status_code=401, content={"type": "error", "error": {
                    "type": "authentication_error",
                    "message": f"missing or wrong {AGENT_TOKEN_HEADER} header for this spend proxy"}})
            return await call_next(request)
        if password:
            given = _basic_password(request)
            if given is None or not _same(given, password):
                return Response("Login required.", status_code=401,
                                headers={"www-authenticate": 'Basic realm="Agent Audit Proxy", charset="UTF-8"'})
        return await call_next(request)
