from core import db
from core.db import TABLES
from core.models import Document


def test_init_db_creates_all_tables(tmp_path):
    conn = db.init_db(tmp_path / "x" / "corpus.db")
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLES) <= names
    db.init_db(tmp_path / "x" / "corpus.db")  # idempotent


def test_document_roundtrip_and_status(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    db.upsert_document(conn, Document(doc_id="D1", title="Loan", ref_aliases=["KF/PLA/2024"], sha256="a"))
    d = db.get_document(conn, "D1")
    assert d and d.ref_aliases == ["KF/PLA/2024"] and d.status == "Queued"
    db.set_document_status(conn, "D1", "Ready")
    assert db.list_documents(conn)[0].status == "Ready"


def test_chats_have_separate_histories(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    a, b = db.create_chat(conn, "A"), db.create_chat(conn, "B")
    db.add_message(conn, a.chat_id, "user", "hello")
    db.add_message(conn, b.chat_id, "user", "other")
    assert [m.content for m in db.list_messages(conn, a.chat_id)] == ["hello"]
    db.rename_chat(conn, a.chat_id, "Renamed")
    assert db.get_chat(conn, a.chat_id).title == "Renamed"
    db.delete_chat(conn, a.chat_id)
    assert db.get_chat(conn, a.chat_id) is None
    assert len(db.list_messages(conn, b.chat_id)) == 1
