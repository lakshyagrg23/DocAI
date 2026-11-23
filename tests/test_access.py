"""Access gate and spend limits (api/access.py, ADR-021)."""
import pytest
from test_api import client, env  # noqa: F401  (fixtures: an API client over an ingested temp corpus)

from api import access
from core import config

WS = {"workspace_id": config.DEFAULT_WORKSPACE_ID}
CODE = "open-sesame"


@pytest.fixture(autouse=True)
def _fresh_limiter():
    access.limiter.reset()
    yield
    access.limiter.reset()


@pytest.fixture
def gated(monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", CODE)


def test_open_when_no_code_is_configured(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    assert client.get("/api/session").json() == {"required": False, "ok": True}
    assert client.get("/api/documents", params=WS).status_code == 200


def test_every_api_route_is_closed_without_the_code(client, gated):  # noqa: F811
    assert client.get("/api/session").json() == {"required": True, "ok": False}
    for path in ("/api/health", "/api/documents", "/api/chats", "/api/conflicts", "/api/amendments", "/api/examples"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/chats", json={"workspace_id": "x"}).status_code == 401
    assert client.post("/api/chats/x/ask", json={"question": "hi"}).status_code == 401
    assert client.get("/api/documents/D6/pages/1/image").status_code == 401  # images too
    assert client.get("/").status_code in (200, 404)  # the page itself (login screen) is public when built


def test_wrong_code_then_right_code(client, gated):  # noqa: F811
    assert client.post("/api/login", json={"code": "nope"}).status_code == 401
    assert client.get("/api/documents", params=WS).status_code == 401
    r = client.post("/api/login", json={"code": f"  {CODE} "})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/session").json() == {"required": True, "ok": True}
    assert client.get("/api/documents", params=WS).status_code == 200


def test_a_changed_code_signs_everyone_out(client, gated, monkeypatch):  # noqa: F811
    client.post("/api/login", json={"code": CODE})
    assert client.get("/api/documents", params=WS).status_code == 200
    monkeypatch.setenv("ACCESS_CODE", "a-new-code")
    assert client.get("/api/documents", params=WS).status_code == 401


def test_guessing_is_slowed_down(client, gated):  # noqa: F811
    codes = [client.post("/api/login", json={"code": f"guess{i}"}).status_code for i in range(access.LOGIN_FAILS_PER_10MIN + 2)]
    assert codes[: access.LOGIN_FAILS_PER_10MIN] == [401] * access.LOGIN_FAILS_PER_10MIN
    assert codes[-1] == 429
    assert client.post("/api/login", json={"code": CODE}).status_code == 429  # even the right code waits


def test_question_limits_per_visitor_and_per_day(client, gated, monkeypatch):  # noqa: F811
    client.post("/api/login", json={"code": CODE})
    chat = client.post("/api/chats", json={"workspace_id": WS["workspace_id"]}).json()["chat_id"]
    monkeypatch.setattr(access, "ASK_PER_HOUR", 2)
    url = f"/api/chats/{chat}/ask"
    assert client.post(url, json={"question": "What fees apply if I pay an EMI late?"}).status_code == 200
    assert client.post(url, json={"question": "What fees apply if I pay an EMI late?"}).status_code == 200
    r = client.post(url, json={"question": "again"})
    assert r.status_code == 429 and "per hour" in r.json()["detail"]
    other = {"x-forwarded-for": "203.0.113.9"}  # a different visitor has their own allowance
    assert client.post(url, json={"question": "What fees apply if I pay an EMI late?"}, headers=other).status_code == 200
    monkeypatch.setattr(access, "ASK_PER_DAY_TOTAL", 3)
    r = client.post(url, json={"question": "x"}, headers={"x-forwarded-for": "203.0.113.10"})
    assert r.status_code == 429 and "daily" in r.json()["detail"]


def test_upload_limits(client, gated, monkeypatch):  # noqa: F811
    client.post("/api/login", json={"code": CODE})
    monkeypatch.setattr(access, "UPLOAD_PER_HOUR", 1)
    files = [("files", ("a.pdf", b"%PDF-1.4 tiny", "application/pdf")), ("files", ("b.pdf", b"%PDF-1.4 tiny", "application/pdf"))]
    assert client.post("/api/documents", params=WS, files=files).status_code == 429  # two files cost two of one
    monkeypatch.setattr(access, "UPLOAD_PER_HOUR", 10)
    monkeypatch.setattr(access, "UPLOAD_MAX_BYTES", 10)
    r = client.post("/api/documents", params=WS, files=[("files", ("big.pdf", b"%PDF-" + b"0" * 50, "application/pdf"))])
    assert r.status_code == 413


def test_spoofed_forwarded_for_does_not_dodge_the_login_limit(client, gated):  # noqa: F811
    """The client writes the LEFT entries of X-Forwarded-For; only the proxy-appended right-hand entry counts."""
    codes = [client.post("/api/login", json={"code": f"guess{i}"},
                         headers={"x-forwarded-for": f"10.0.0.{i}, 198.51.100.7"}).status_code
             for i in range(access.LOGIN_FAILS_PER_10MIN + 2)]
    assert codes[-1] == 429


def _raw_get(app, path: str) -> tuple[int, bytes]:
    """GET with the path exactly as sent (an HTTP client may normalise '..' away; a raw request does not)."""
    import asyncio

    async def go():
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": path, "raw_path": path.encode(), "query_string": b"", "headers": [], "server": ("t", 80),
                 "client": ("1.2.3.4", 1)}
        out: list[dict] = []

        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.sleep(3600)  # a real client stays connected: never answer with a disconnect or spin
            return {"type": "http.disconnect"}

        async def send(msg):
            out.append(msg)

        await app(scope, receive, send)
        status = next(m["status"] for m in out if m["type"] == "http.response.start")
        return status, b"".join(m.get("body", b"") for m in out if m["type"] == "http.response.body")

    return asyncio.run(go())


def test_static_route_cannot_escape_the_web_folder(client, gated):  # noqa: F811
    from api.main import DIST
    if not (DIST / "index.html").exists():
        pytest.skip("web/dist is not built")
    index = (DIST / "index.html").read_bytes()
    secret = (DIST.parent.parent / "pyproject.toml").read_bytes()  # a real file outside web/dist
    for p in ("/../../pyproject.toml", "/..%2f..%2fpyproject.toml", "/assets/../../../pyproject.toml"):
        status, body = _raw_get(client.app, p)
        assert body != secret, p
    status, body = _raw_get(client.app, "/../../pyproject.toml")
    assert status == 200 and body == index  # falls back to the login page


def test_limiter_window():
    lim = access.Limiter()
    assert lim.allow("k", 2, 10, now=0) and lim.allow("k", 2, 10, now=1)
    assert not lim.allow("k", 2, 10, now=2)
    assert lim.allow("k", 2, 10, now=12)  # the old hits fell out of the window
