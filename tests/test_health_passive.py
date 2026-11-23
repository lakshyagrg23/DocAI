"""Passive health (HEALTH_PASSIVE=1, used on Modal): the status check never contacts the model, a question wakes it."""
import pytest
from test_api import client, env, sse  # noqa: F401  (fixtures: an API client over an ingested temp corpus)

from api import deps
from core import config
from core.llm.client import ModelUnavailable

WS = {"workspace_id": config.DEFAULT_WORKSPACE_ID}


@pytest.fixture
def passive(monkeypatch):
    monkeypatch.setenv("HEALTH_PASSIVE", "1")
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    deps.MODEL_STATUS.last_ok = deps.MODEL_STATUS.last_fail = None
    yield
    deps.MODEL_STATUS.last_ok = deps.MODEL_STATUS.last_fail = None


def test_status_machine():
    st = deps.ModelStatus()
    assert st.state(now=1000) == "asleep"
    st.last_ok = 1000.0
    assert st.state(now=1000 + config.MODEL_IDLE_S - 1) == "ready"
    assert st.state(now=1000 + config.MODEL_IDLE_S + 1) == "asleep"  # the GPU has gone to sleep by itself
    st.last_fail = 2000.0
    assert st.state(now=2000 + 1) == "offline"
    assert st.state(now=2000 + config.MODEL_OFFLINE_S + 1) == "asleep"  # offline expires, so a retry is possible


def test_health_never_calls_the_model(client, passive, monkeypatch):  # noqa: F811
    def boom():
        raise AssertionError("the health check must not contact the model service")
    monkeypatch.setattr(deps.get_model(), "health", boom, raising=False)
    h = client.get("/api/health").json()
    assert h["state"] == "asleep" and "first question" in h["label"]
    deps.MODEL_STATUS.ok()
    assert client.get("/api/health").json() == {"state": "ready", "label": "Ready"}
    deps.MODEL_STATUS.fail()
    assert client.get("/api/health").json()["state"] == "offline"


def test_first_question_wakes_the_model_once(client, passive, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(deps.get_model(), "health", lambda: calls.append(1) or {"llm": "ready"}, raising=False)
    chat = client.post("/api/chats", json={"workspace_id": WS["workspace_id"]}).json()["chat_id"]
    q = {"question": "What fees apply if I pay an EMI late?"}
    events = sse(client.post(f"/api/chats/{chat}/ask", json=q).text)
    assert [e for e, _ in events][-1] == "answer"
    waking = [d["label"] for e, d in events if e == "stage" and "Waking" in d["label"]]
    assert waking and len(calls) == 1
    assert client.get("/api/health").json()["state"] == "ready"
    sse(client.post(f"/api/chats/{chat}/ask", json=q).text)
    assert len(calls) == 1  # already awake: no second wake-up


def test_a_model_that_never_wakes_gives_a_clear_error(client, passive, monkeypatch):  # noqa: F811
    def down():
        raise ModelUnavailable("asleep")
    monkeypatch.setattr(deps.get_model(), "health", down, raising=False)
    monkeypatch.setattr(config, "MODEL_WAKE_DEADLINE_S", 0.05)
    monkeypatch.setattr(config, "MODEL_WAKE_POLL_S", 0.01)
    chat = client.post("/api/chats", json={"workspace_id": WS["workspace_id"]}).json()["chat_id"]
    events = sse(client.post(f"/api/chats/{chat}/ask", json={"question": "hello there"}).text)
    assert events[-1][0] == "error" and "not reachable" in events[-1][1]["message"]
    assert client.get("/api/health").json()["state"] == "offline"


def test_active_health_is_unchanged_without_the_flag(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("HEALTH_PASSIVE", raising=False)
    monkeypatch.setattr(deps.get_model(), "health", lambda: {"llm": "ready"}, raising=False)
    assert client.get("/api/health").json() == {"state": "ready", "label": "Ready"}
