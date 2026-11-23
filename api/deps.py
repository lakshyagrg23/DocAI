"""Shared API resources: per-request DB connection, one model client, one retriever, a lock that serialises answers."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from datetime import date

from core import config, db
from core.llm.client import ModelClient, ModelUnavailable, get_client
from core.retrieval.hybrid import Retriever

ANSWER_LOCK = threading.Lock()  # one answer at a time: the CPU model service is the bottleneck anyway
_state: dict[str, object] = {}


def get_model() -> ModelClient:
    if "model" not in _state:
        _state["model"] = get_client()
    return _state["model"]  # type: ignore[return-value]


def get_retriever() -> Retriever:
    if "retriever" not in _state:
        _state["retriever"] = Retriever(db.connect(), get_model())
    return _state["retriever"]  # type: ignore[return-value]


def reset() -> None:
    MODEL_STATUS.last_ok = MODEL_STATUS.last_fail = None
    """Forget cached singletons (tests point the API at a temporary data directory)."""
    r = _state.get("retriever")
    if r is not None:
        r.conn.close()  # type: ignore[attr-defined]
    _state.clear()


def conn_dep() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def today() -> str:
    return date.today().isoformat()


# ---- model status without waking the GPU ----------------------------------------------------------------------
# On Modal every call to the model service can start a paid GPU. A health check that polls it (the UI does, every 15 s)
# would keep the GPU awake for as long as a tab is open. With HEALTH_PASSIVE=1 the status comes from the calls the app
# has really made, and a question wakes the model explicitly (wake_model).

class ModelStatus:
    def __init__(self) -> None:
        self.last_ok: float | None = None
        self.last_fail: float | None = None

    def ok(self) -> None:
        self.last_ok, self.last_fail = time.time(), None

    def fail(self) -> None:
        self.last_fail = time.time()

    def state(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        if self.last_fail is not None and now - self.last_fail < config.MODEL_OFFLINE_S:
            return "offline"
        if self.last_ok is not None and now - self.last_ok < config.MODEL_IDLE_S:
            return "ready"
        return "asleep"


MODEL_STATUS = ModelStatus()
PASSIVE_LABELS = {"ready": "Ready", "offline": "Offline",
                  "asleep": "Asleep: your first question wakes it (about 3 minutes)"}


def passive_health() -> bool:
    return os.environ.get("HEALTH_PASSIVE") == "1"


def wake_model(on_wait=None, deadline_s: float | None = None) -> None:
    """Make sure the model service answers before a question starts. Raises ModelUnavailable after the deadline."""
    if MODEL_STATUS.state() == "ready":
        return
    if on_wait:
        on_wait()
    end = time.time() + (config.MODEL_WAKE_DEADLINE_S if deadline_s is None else deadline_s)
    while True:
        try:
            if get_model().health().get("llm") == "ready":
                MODEL_STATUS.ok()
                return
        except ModelUnavailable:
            pass
        if time.time() > end:
            MODEL_STATUS.fail()
            raise ModelUnavailable("the model did not start in time")
        time.sleep(config.MODEL_WAKE_POLL_S)
