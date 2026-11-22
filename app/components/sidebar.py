"""Sidebar for all pages (ui.md §Sidebar): promise, model status, multi-chat CRUD, per-chat settings."""
from __future__ import annotations

import sqlite3
from datetime import date

import streamlit as st

from app import state
from app.i18n import t
from core import db
from core.models import Chat

LANGS = {"auto": "Auto", "en": "English", "hi": "हिन्दी"}


def _select(chat_id: str) -> None:
    st.session_state["chat_id"] = chat_id
    st.query_params["chat"] = chat_id
    st.session_state["evidence"] = None
    st.session_state["ev_page"] = None


def _ensure_active(conn: sqlite3.Connection) -> Chat:
    chats = db.list_chats(conn)
    wanted = st.session_state.get("chat_id") or st.query_params.get("chat")
    chat = next((c for c in chats if c.chat_id == wanted), None) or (chats[0] if chats else None)
    if chat is None:
        chat = db.create_chat(conn, as_of_date=state.today_iso())
    if st.session_state.get("chat_id") != chat.chat_id:
        _select(chat.chat_id)
    return chat


def render(conn: sqlite3.Connection) -> Chat:
    chat = _ensure_active(conn)
    lang = chat.language if chat.language in ("en", "hi") else "en"
    with st.sidebar:
        st.title("Verifiable DocAI")
        st.caption(t("tagline", lang))
        dot, label = state.model_status()
        st.markdown(f"{dot} Model: **{label}**")
        if st.button(f"➕ {t('new_chat', lang)}", width="stretch", key="new-chat"):
            new = db.create_chat(conn, as_of_date=state.today_iso())
            _select(new.chat_id)
            st.rerun()
        st.markdown(f"**{t('chats', lang)}**")
        for c in db.list_chats(conn):
            col, more = st.columns([5, 1])
            if col.button(("● " if c.chat_id == chat.chat_id else "") + c.title, key=f"chat-{c.chat_id}",
                          width="stretch"):
                _select(c.chat_id)
                st.rerun()
            with more.popover("⋯"):
                new_title = st.text_input("Rename", value=c.title, key=f"rn-{c.chat_id}")
                if st.button("Save name", key=f"rns-{c.chat_id}") and new_title.strip():
                    db.rename_chat(conn, c.chat_id, new_title.strip())
                    st.rerun()
                if st.button("Delete chat", key=f"del-{c.chat_id}"):
                    db.delete_chat(conn, c.chat_id)
                    st.session_state["chat_id"] = None
                    st.query_params.pop("chat", None)
                    st.rerun()
        st.divider()
        st.markdown(f"**{t('settings', lang)}**")
        current = date.fromisoformat(chat.as_of_date) if chat.as_of_date else date.today()
        picked = st.date_input(t("as_of", lang), value=current, key=f"asof-{chat.chat_id}")
        if picked.isoformat() != chat.as_of_date:
            db.update_chat_settings(conn, chat.chat_id, as_of_date=picked.isoformat())
        keys = list(LANGS)
        choice = st.selectbox(t("language", lang), keys, index=keys.index(chat.language) if chat.language in keys else 0,
                              format_func=LANGS.get, key=f"lang-{chat.chat_id}")
        if choice != chat.language:
            db.update_chat_settings(conn, chat.chat_id, language=choice)
    return db.get_chat(conn, chat.chat_id) or chat
