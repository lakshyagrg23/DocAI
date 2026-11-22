"""Shared API resources: per-request DB connection, one model client, one retriever, a lock that serialises answers."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from datetime import date

from core import db
from core.llm.client import ModelClient, get_client
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
