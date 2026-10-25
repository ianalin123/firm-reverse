"""Shared access-code gate for public deployments. Inactive unless ACCESS_CODE is set."""

import hmac
import os
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

COOKIE = "fr_access"
UNLOCK_PATH = "/unlock"
COOKIE_MAX_AGE = 7 * 24 * 3600

FORM = b"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Access code</title></head>
<body style="font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0">
<form method="get" action="/unlock"><label>Access code <input name="code" autofocus autocomplete="off"></label> <button>Enter</button></form>
</body></html>"""


def _matches(candidate: str, code: str) -> bool:
    return hmac.compare_digest(candidate.encode(), code.encode())


def _cookie_value(scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            morsel = SimpleCookie(value.decode("latin-1")).get(COOKIE)
            if morsel is not None:
                return morsel.value
    return ""


async def _send(send, status: int, headers: list[tuple[bytes, bytes]], body: bytes = b"") -> None:
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class AccessCodeMiddleware:
    def __init__(self, app, code: str | None = None):
        self.app = app
        self.code = code if code is not None else os.environ.get("ACCESS_CODE", "")

    async def __call__(self, scope, receive, send):
        if not self.code or scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == UNLOCK_PATH:
            return await self._unlock(scope, send)
        if _matches(_cookie_value(scope), self.code):
            return await self.app(scope, receive, send)
        if scope["path"].startswith("/api/"):
            return await _send(send, 401, [(b"content-type", b"application/json")], b'{"detail":"access code required"}')
        return await _send(send, 401, [(b"content-type", b"text/html; charset=utf-8")], FORM)

    async def _unlock(self, scope, send):
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        candidate = (query.get("code") or [""])[0]
        if not _matches(candidate, self.code):
            return await _send(send, 401, [(b"content-type", b"text/html; charset=utf-8")], FORM)
        cookie = f"{COOKIE}={self.code}; Path=/; Max-Age={COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax"
        await _send(send, 303, [(b"location", b"/"), (b"set-cookie", cookie.encode("latin-1"))])
