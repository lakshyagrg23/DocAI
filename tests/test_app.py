"""M7 tests: every Streamlit page renders on an ingested corpus (headless AppTest), chat CRUD, highlight rendering."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_conflicts import Facts
from test_ingest import PDFS, corpus  # noqa: F401  (corpus = autouse fixture that builds the PDFs)
from test_versions import ingest

from core import config, db
from core.answer import assemble
from core.models import Draft, DraftClaim, QueryPlan
from core.render import highlight
from core.retrieval.hybrid import Retriever

ROOT = Path(__file__).resolve().parents[1]
MAIN = str(ROOT / "app" / "main.py")


class Answerer(Facts):
    def chat_json(self, messages, model_cls, max_tokens=900):
        if model_cls is QueryPlan:
            return QueryPlan(sub_questions=["late payment fee per instalment"])
        if model_cls is Draft:
            return Draft(claims=[DraftClaim(text="The late payment fee is ₹500 per instalment", span_ids=["D1:8.1#s1"]),
                                 DraftClaim(text="The late payment fee is ₹750 per instalment",
                                            span_ids=["D2:table1.row2#s1"])])
        return super().chat_json(messages, model_cls, max_tokens)

    def nli(self, pairs):
        return [0.95] * len(pairs)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m7")
    conn = db.init_db(tmp / "corpus.db")
    client = Answerer()
    ingest(conn, client, "D1", "D2", "D3", "D4", "D5", tmp=tmp)
    chat = db.create_chat(conn, as_of_date="2026-11-22")
    assemble.answer(conn, "What fees apply if I pay an EMI late?", chat.chat_id, as_of="2026-11-22", client=client,
                    retriever=Retriever(conn, client, tmp))
    return conn, chat, tmp


@pytest.fixture
def app(env, monkeypatch):
    import streamlit as st
    _, chat, tmp = env
    monkeypatch.setattr(config, "DB_PATH", tmp / "corpus.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp)
    st.cache_resource.clear()
    from app import state
    monkeypatch.setattr(state, "model_status", lambda: ("🟢", "Ready"))
    at = AppTest.from_file(MAIN, default_timeout=60)
    at.query_params["chat"] = chat.chat_id
    return at.run(), chat


def texts(at, kind="markdown") -> str:
    return "\n".join(str(getattr(e, "value", "")) for e in getattr(at, kind))


def test_chat_page_renders_the_stored_conflict_answer(app):
    at, _ = app
    assert not at.exception
    body = texts(at)
    assert "What fees apply if I pay an EMI late?" in body and "₹500 per instalment" in body and "₹750 per instalment" in body
    assert "Documents disagree: late payment fee" in body  # the disagreement card
    assert any(b.label == "D1 · p.4" or b.label.startswith("D1 ·") for b in at.button)  # citation pills
    assert at.chat_input and "Ask about your documents" in at.chat_input[0].placeholder


@pytest.mark.parametrize("page,needle", [("pages/documents.py", "Documents"), ("pages/conflicts.py", "Conflicts"),
                                         ("pages/amendments.py", "Amendments")])
def test_other_pages_render(app, page, needle):
    at, _ = app
    at.switch_page(page).run()
    assert not at.exception, at.exception
    assert needle in texts(at, "header") or needle in texts(at, "title")


def test_conflicts_page_lists_the_cards_and_amendments_page_the_timeline(app):
    at, _ = app
    at.switch_page("pages/conflicts.py").run()
    body = texts(at) + texts(at, "caption")  # one card per subject: both conflicts (C1, C2) are explained on it
    assert "late payment fee" in body and "vs" in body and "exceeds the" in body
    at.switch_page("pages/amendments.py").run()
    body = texts(at)
    assert "D1:7.2" in body and "D3:1" in body and "D4:1" in body and "in force" in body


SIDEBAR_SCRIPT = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from app import state
from app.components import sidebar
chat = sidebar.render(state.get_conn())
st.write("ACTIVE " + chat.chat_id)
"""


def sidebar_app(env, monkeypatch):
    import streamlit as st

    from app import state
    _, chat, tmp = env
    monkeypatch.setattr(config, "DB_PATH", tmp / "corpus.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp)
    st.cache_resource.clear()
    monkeypatch.setattr(state, "model_status", lambda: ("🟢", "Ready"))
    at = AppTest.from_string(SIDEBAR_SCRIPT.format(root=ROOT), default_timeout=60)
    at.query_params["chat"] = chat.chat_id
    return at.run(), chat


def active(at) -> str:
    return next(m.value for m in at.markdown if str(m.value).startswith("ACTIVE ")).split()[1]


def test_new_chat_keeps_separate_histories_and_can_be_deleted(env, monkeypatch):
    conn = env[0]
    at, chat = sidebar_app(env, monkeypatch)
    assert active(at) == chat.chat_id and not at.exception
    next(b for b in at.sidebar.button if b.key == "new-chat").click().run()
    new_id = active(at)
    assert new_id != chat.chat_id and len(db.list_chats(conn)) == 2
    assert db.list_messages(conn, new_id) == []  # the new chat starts empty
    assert len(db.list_messages(conn, chat.chat_id)) == 2  # the first chat keeps its history
    next(b for b in at.sidebar.button if b.key == f"chat-{chat.chat_id}").click().run()  # switch back
    assert active(at) == chat.chat_id
    next(b for b in at.sidebar.button if b.key == f"del-{new_id}").click().run()
    assert [c.chat_id for c in db.list_chats(conn)] == [chat.chat_id]


def test_as_of_date_and_language_persist_per_chat(env, monkeypatch):
    conn = env[0]
    at, chat = sidebar_app(env, monkeypatch)
    at.sidebar.date_input[0].set_value(date(2025, 6, 1)).run()
    at.sidebar.selectbox[0].select("hi").run()
    saved = db.get_chat(conn, chat.chat_id)
    assert saved.as_of_date == "2025-06-01" and saved.language == "hi"
    db.update_chat_settings(conn, chat.chat_id, as_of_date="2026-11-22", language="auto")


def test_highlight_renders_a_page_png_with_a_rectangle():
    path = PDFS / "D1_loan_agreement.pdf"
    plain = highlight.render(path, 4, [])
    marked = highlight.render(path, 4, [[50, 100, 300, 130]])
    assert plain[:8] == b"\x89PNG\r\n\x1a\n" and marked != plain and highlight.page_count(path) == 6


def test_pdf_path_and_span_boxes_are_valid(env):
    conn, _, _ = env
    sp = conn.execute("SELECT page,bboxes FROM spans WHERE span_id='D1:8.1#s1'").fetchone()
    assert json.loads(sp["bboxes"]) and sp["page"] >= 1
    assert highlight.pdf_path(conn, "D1") is not None and highlight.pdf_path(conn, "NOPE") is None
