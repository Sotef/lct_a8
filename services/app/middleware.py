# -*- coding: utf-8 -*-
"""HTTP-middleware: request-id, контекст пользователя, access-лог API.

Чистый ASGI (без BaseHTTPMiddleware) — не ломает стриминг и не буферизует тело.
Каждый запрос /api/* логируется одной строкой: метод, путь, статус, длительность,
пользователь (из JWT, без обращения к БД), ip. Медленные (> SLOW_REQUEST_MS) —
WARNING, 5xx — ERROR. В ответ добавляется заголовок X-Request-ID.
"""
from __future__ import annotations

import logging
import time
import uuid

from . import config
from .logging_setup import client_ip_var, log_event, request_id_var, user_var

log = logging.getLogger("http")

_SKIP_PATHS = ("/api/v1/admin/logs", "/api/v1/meta/clock", "/api/v1/logs/client")


def _user_from_auth(headers: dict) -> str:
    """sub из JWT (без проверки подписи — только для лога; auth проверяет deps)."""
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return "-"
    try:
        from jose import jwt
        claims = jwt.get_unverified_claims(auth.split(" ", 1)[1])
        return "uid:" + str(claims.get("sub", "?"))
    except Exception:  # noqa: BLE001
        return "invalid-token"


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        rid = headers.get("x-request-id") or uuid.uuid4().hex[:12]
        client = scope.get("client")
        ip = headers.get("x-forwarded-for", "").split(",")[0].strip() or \
            (client[0] if client else "-")
        path = scope.get("path", "")
        t_rid = request_id_var.set(rid)
        t_ip = client_ip_var.set(ip)
        t_user = user_var.set(_user_from_auth(headers))
        status = {"code": 500}
        t0 = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + \
                    [(b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled error %s %s", scope.get("method"), path)
            raise
        finally:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            if path.startswith("/api/"):
                code = status["code"]
                quiet = path.startswith(_SKIP_PATHS) and code < 400
                if code >= 500:
                    level = logging.ERROR
                elif ms > config.SLOW_REQUEST_MS or code in (401, 403, 429):
                    level = logging.WARNING
                else:
                    level = logging.DEBUG if quiet else logging.INFO
                qs = scope.get("query_string", b"").decode("latin-1")
                log_event(log, level,
                          f"{scope.get('method')} {path} -> {code} ({ms} ms)",
                          method=scope.get("method"), path=path, query=qs[:300],
                          status=code, ms=ms)
            request_id_var.reset(t_rid)
            client_ip_var.reset(t_ip)
            user_var.reset(t_user)
