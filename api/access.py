"""Access gate and spend limits for the public deployment (ADR-021).

Anyone who can reach the app could otherwise wake the paid GPU. The gate is a shared access code (env `ACCESS_CODE`, kept in the
Modal secret); with the variable unset (local dev, tests) everything is open. After a correct code the browser gets an HttpOnly
cookie holding an HMAC of the code, so changing the code signs everyone out. On top of the gate, in-memory limits (one container
only, so one process) cap questions and uploads per visitor and questions per day overall, and slow down guessing of the code.

Every `/api` route except `/api/login` and `/api/session` depends on `require_access`. That includes `/api/health`, because
the health check calls the model service, and that call wakes the GPU.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

COOKIE = "docai_session"
COOKIE_MAX_AGE = 7 * 24 * 3600

ASK_PER_HOUR = int(os.environ.get("ASK_PER_HOUR", "30"))  # questions per visitor per hour
ASK_PER_DAY_TOTAL = int(os.environ.get("ASK_PER_DAY_TOTAL", "300"))  # questions per day, everyone together
UPLOAD_PER_HOUR = int(os.environ.get("UPLOAD_PER_HOUR", "10"))  # uploaded files per visitor per hour
LOGIN_FAILS_PER_10MIN = 8
UPLOAD_MAX_BYTES = 15 * 1024 * 1024

router = APIRouter(prefix="/api")


def access_code() -> str:
    """Read at request time so tests (and a restarted container with a new secret) see the current value."""
    return os.environ.get("ACCESS_CODE", "").strip()


def session_token(code: str) -> str:
    return hmac.new(code.encode(), b"docai-session-v1", hashlib.sha256).hexdigest()


def is_authorised(request: Request) -> bool:
    code = access_code()
    if not code:
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), session_token(code))


def require_access(request: Request) -> None:
    if not is_authorised(request):
        raise HTTPException(401, "An access code is needed to use this app.")


class Limiter:
    """Sliding-window counter per key. Thread-safe; state lives in this process only."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float, cost: int = 1, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) + cost > limit:
                return False
            q.extend([now] * cost)
            return True

    def count(self, key: str, window_s: float, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            return len(q)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = Limiter()


TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))  # proxies in front of the app that append to X-Forwarded-For


def visitor(request: Request) -> str:
    """The caller's address. Each proxy appends the peer it saw to X-Forwarded-For, so the entries a client writes
    itself are on the LEFT and cannot be trusted: take the entry TRUSTED_PROXY_HOPS from the right. Without the
    header (local dev) the socket address is used."""
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if parts and TRUSTED_PROXY_HOPS > 0:
        return parts[max(len(parts) - TRUSTED_PROXY_HOPS, 0)]
    return request.client.host if request.client else "unknown"


def limit_ask(request: Request) -> None:
    if not access_code():
        return  # open mode (local development)
    if not limiter.allow(f"ask:{visitor(request)}", ASK_PER_HOUR, 3600):
        raise HTTPException(429, f"You have reached the limit of {ASK_PER_HOUR} questions per hour. Please try again later.")
    if not limiter.allow("ask:all", ASK_PER_DAY_TOTAL, 86400):
        raise HTTPException(429, "The demo has reached its daily question limit. Please try again tomorrow.")


def limit_upload(request: Request, n_files: int) -> None:
    if access_code() and not limiter.allow(f"upload:{visitor(request)}", UPLOAD_PER_HOUR, 3600, cost=max(n_files, 1)):
        raise HTTPException(429, f"You have reached the limit of {UPLOAD_PER_HOUR} uploaded files per hour. Please try again later.")


class Login(BaseModel):
    code: str


@router.get("/session")
def session(request: Request) -> dict:
    return {"required": bool(access_code()), "ok": is_authorised(request)}


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> dict:
    code = access_code()
    if not code:
        return {"ok": True}
    who = f"login:{visitor(request)}"
    if limiter.count(who, 600) >= LOGIN_FAILS_PER_10MIN:
        raise HTTPException(429, "Too many wrong codes. Please wait a few minutes and try again.")
    if not hmac.compare_digest(body.code.strip().encode(), code.encode()):
        limiter.allow(who, LOGIN_FAILS_PER_10MIN + 1, 600)  # record the failure
        raise HTTPException(401, "That code is not right.")
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, session_token(code), max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", secure=secure)
    return {"ok": True}
