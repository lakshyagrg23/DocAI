"""Chat page (ui.md §Chat page): history with answer cards, input with live stages, evidence viewer."""
from __future__ import annotations

import json

import streamlit as st

from app import state
from app.components import answer_card, evidence
from app.i18n import t
from core import db
from core.answer import assemble

EXAMPLES = ["What fees apply if I pay an EMI late?",
            "What is the prepayment charge today for a floating-rate loan to an individual?",
            "What is the GST rate on the processing fee?"]

conn = state.get_conn()
chat = db.get_chat(conn, state.active_chat_id() or "")
if chat is None:
    st.stop()
lang = chat.language if chat.language in ("en", "hi") else "en"

col_chat, col_evidence = st.columns([3, 2])
messages = db.list_messages(conn, chat.chat_id)
with col_chat:
    st.header(chat.title)
    for m in messages:
        with st.chat_message(m.role):
            if m.role == "assistant" and m.answer_json:
                answer_card.render(conn, json.loads(m.answer_json), m.msg_id, lang)
            else:
                st.markdown(m.content)
    if not messages:
        st.caption("Try one of these:")
        for i, q in enumerate(EXAMPLES):
            if st.button(q, key=f"ex-{i}"):
                st.session_state["pending_question"] = q
                st.rerun()
    question = st.chat_input(t("ask", lang)) or st.session_state.pop("pending_question", None)
    if question:
        if state.model_status()[1] == "Offline":
            st.warning(t("offline", lang))
        else:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"), st.status("Working…", expanded=True) as status:
                assemble.answer(conn, question, chat.chat_id, as_of=chat.as_of_date, client=state.get_model(),
                                retriever=state.get_retriever(), on_stage=lambda s: status.update(label=s))
                status.update(label="Done", state="complete", expanded=False)
            st.session_state["evidence"] = None
            st.rerun()

with col_evidence:
    latest = next((json.loads(m.answer_json) for m in reversed(messages) if m.answer_json), None)
    default = None
    if latest and latest["claims"]:
        default = latest["claims"][0]["span_ids"][0]
    elif latest and latest.get("disagreements"):
        default = latest["disagreements"][0]["sides"][0]["span_id"]
    evidence.evidence_viewer(conn, default)
