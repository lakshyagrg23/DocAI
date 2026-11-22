"""Shared Streamlit resources: one DB connection, one model client, one retriever, model status."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from core import db
from core.llm.client import ModelClient, ModelUnavailable, get_client
from core.retrieval.hybrid import Retriever


@st.cache_resource
def get_conn():
    return db.init_db()


@st.cache_resource
def get_model() -> ModelClient:
    return get_client()


@st.cache_resource
def get_retriever() -> Retriever:
    return Retriever(get_conn(), get_model())


@st.cache_data(ttl=15)
def model_status() -> tuple[str, str]:
    """(dot, label) for the sidebar: green ready, orange warming up, red offline."""
    try:
        h = get_model().health()
    except ModelUnavailable:
        return "🔴", "Offline"
    return ("🟢", "Ready") if h.get("llm") == "ready" else ("🟠", "Warming up")


def active_chat_id() -> str | None:
    return st.session_state.get("chat_id")


def today_iso() -> str:
    return date.today().isoformat()
