"""Workspaces (ADR-024): migration of old databases, hard isolation of retrieval / conflicts / amendments, the HTTP API, deletion."""
from __future__ import annotations

import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_api import Answerer, sse
from test_ingest import PDFS, corpus  # noqa: F401  (autouse fixture that builds the PDFs)
from test_versions import DOCS

from api import deps
from api.main import create_app
from core import config, db, versions
from core.ingest import pipeline, remove
from core.models import Chat, Document
from core.retrieval.hybrid import Retriever
from core.retrieval.index import load_index

DEMO = config.DEFAULT_WORKSPACE_ID


def put(conn, tmp, ws: str, *names: str, stable_ids: bool = True) -> None:
    for n in names:
        pipeline.enqueue(PDFS / DOCS[n], conn, start_worker=False, workspace_id=ws, stable_ids=stable_ids)
    pipeline.run_pending(conn, Answerer(), tmp)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """demo: D1 + D2 (the late-fee conflict C1). second: D3 (amends D1) + D5 (a cap that would conflict with D2). empty: nothing."""
    tmp = tmp_path_factory.mktemp("ws")
    conn = db.init_db(tmp / "corpus.db")
    put(conn, tmp, DEMO, "D1", "D2")
    db.ensure_workspace(conn, "ws_second", "Second")
    db.ensure_workspace(conn, "ws_empty", "Empty")
    put(conn, tmp, "ws_second", "D3", "D5")
    return conn, tmp


@pytest.fixture
def client(env, monkeypatch):
    _, tmp = env
    monkeypatch.setattr(config, "DB_PATH", tmp / "corpus.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp)
    deps.reset()
    scripted = Answerer()
    scripted.health = lambda: {"llm": "ready"}  # type: ignore[attr-defined]
    monkeypatch.setattr(deps, "get_model", lambda: scripted)
    monkeypatch.setattr(deps, "get_retriever", lambda: Retriever(db.connect(), scripted, tmp))
    with TestClient(create_app()) as c:
        yield c


def chat_in(client, ws: str) -> str:
    return client.post("/api/chats", json={"workspace_id": ws}).json()["chat_id"]


# ---- migration ------------------------------------------------------------------------

LEGACY = """
CREATE TABLE documents(doc_id TEXT PRIMARY KEY, title TEXT, doc_type TEXT, issuer TEXT, ref_no TEXT, ref_aliases TEXT,
  issue_date TEXT, effective_date TEXT, sha256 TEXT UNIQUE, filename TEXT, pages INT, has_ocr INT DEFAULT 0,
  language TEXT DEFAULT 'en', status TEXT, status_detail TEXT, created_at TEXT);
CREATE TABLE chats(chat_id TEXT PRIMARY KEY, title TEXT, created_at TEXT, as_of_date TEXT, language TEXT DEFAULT 'auto',
  doc_scope TEXT);
INSERT INTO documents(doc_id,title,sha256,status) VALUES('D1','Loan','aaa','Ready');
INSERT INTO chats(chat_id,title,created_at) VALUES('c1','Old chat','2026-01-01T00:00:00+00:00');
"""


def test_a_database_from_before_workspaces_moves_into_the_default_workspace(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(LEGACY)
    raw.commit()
    raw.close()
    conn = db.init_db(path)
    assert db.get_document(conn, "D1").workspace_id == DEMO and db.get_chat(conn, "c1").workspace_id == DEMO
    assert [(w["workspace_id"], w["name"], w["documents"], w["chats"]) for w in db.list_workspaces(conn)] == \
        [(DEMO, config.DEFAULT_WORKSPACE_NAME, 1, 1)]
    # the content hash is now unique per workspace: the same file may live in two workspaces, not twice in one
    other = db.create_workspace(conn, "Other")
    db.upsert_document(conn, Document(doc_id="Dx", sha256="aaa", workspace_id=other.workspace_id))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO documents(doc_id,sha256,workspace_id) VALUES('Dy','aaa',?)", (other.workspace_id,))
    conn.close()
    again = db.init_db(path)  # idempotent: a second start changes nothing
    assert [w["documents"] for w in db.list_workspaces(again)] == [1, 1] and len(db.list_chats(again)) == 1


def test_a_fresh_database_has_no_workspaces(tmp_path):
    assert db.list_workspaces(db.init_db(tmp_path / "new.db")) == []


# ---- documents -------------------------------------------------------------------------

def test_the_same_pdf_in_two_workspaces_is_two_documents(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    db.ensure_workspace(conn, "ws_a", "A")
    db.ensure_workspace(conn, "ws_b", "B")
    pdf = PDFS / DOCS["D1"]
    a = pipeline.enqueue(pdf, conn, start_worker=False, stable_ids=False, workspace_id="ws_a")
    b = pipeline.enqueue(pdf, conn, start_worker=False, stable_ids=False, workspace_id="ws_b")
    again = pipeline.enqueue(pdf, conn, start_worker=False, stable_ids=False, workspace_id="ws_a")
    assert a != b and a == again  # a repeat upload to the same workspace is deduplicated, to another one is not
    ids = {w: db.workspace_doc_ids(conn, w) for w in ("ws_a", "ws_b")}
    assert len(ids["ws_a"]) == len(ids["ws_b"]) == 1 and ids["ws_a"] != ids["ws_b"]
    # a stable id (D1) already used elsewhere is never reused for another workspace's copy
    c = pipeline.enqueue(pdf, conn, start_worker=False, workspace_id=DEMO)
    d = pipeline.enqueue(pdf, conn, start_worker=False, workspace_id="ws_a")  # known sha in ws_a: same job as before
    assert d == a and conn.execute("SELECT doc_id FROM ingest_jobs WHERE job_id=?", (c,)).fetchone()["doc_id"] == "D1"


# ---- isolation ----------------------------------------------------------------------------

def test_conflicts_and_amendments_never_cross_workspaces(env):
    conn, _ = env
    spans = conn.execute("SELECT f.fact_id, c.doc_id, d.workspace_id FROM facts f JOIN clauses c ON c.clause_id=f.clause_id "
                         "JOIN documents d ON d.doc_id=c.doc_id").fetchall()
    ws_of = {r["fact_id"]: r["workspace_id"] for r in spans}
    found = conn.execute("SELECT fact_a, fact_b FROM conflicts").fetchall()
    assert found and all(ws_of[r["fact_a"]] == ws_of[r["fact_b"]] for r in found)
    docs = {c["doc_id"] for r in found for c in conn.execute(
        "SELECT c.doc_id FROM facts f JOIN clauses c ON c.clause_id=f.clause_id WHERE f.fact_id IN (?,?)",
        (r["fact_a"], r["fact_b"]))}
    assert docs == {"D1", "D2"}  # C1 only: D5's cap on late fees is in another workspace, so there is no C2
    edge = conn.execute("SELECT resolved, target_doc_id FROM amendment_edges WHERE source_clause_id LIKE 'D3:%'").fetchone()
    assert edge["resolved"] == 0 and edge["target_doc_id"] is None  # D3 amends D1, which is not in its workspace
    assert versions.versions_for(conn, "D1:7.2") == []  # so D1's rule keeps its single version


def test_the_scope_of_a_chat_is_a_hard_boundary(env):
    conn, _ = env
    chat = lambda **kw: Chat(chat_id="c", title="t", created_at="x", **kw)
    assert db.chat_doc_scope(conn, chat(workspace_id=DEMO)) == ["D1", "D2"]
    assert db.chat_doc_scope(conn, chat(workspace_id=DEMO, doc_scope=["D2", "D5"])) == ["D2"]  # picker cannot leave the workspace
    assert db.chat_doc_scope(conn, chat(workspace_id="ws_empty")) == []  # empty, and NOT "everything"
    assert db.chat_doc_scope(conn, chat(workspace_id="ws_empty", doc_scope=["D1"])) == []
    assert db.chat_doc_scope(conn, chat()) is None  # legacy chat without a workspace


def test_a_chat_cannot_cite_documents_of_another_workspace(client):
    chat_id = chat_in(client, "ws_second")
    client.patch(f"/api/chats/{chat_id}", json={"as_of_date": "2026-11-22"})
    r = client.post(f"/api/chats/{chat_id}/ask", json={"question": "What fees apply if I pay an EMI late?"})
    answer = sse(r.text)[-1][1]["assistant"]["answer"]
    # the scripted model cites D1 and D2 (demo workspace); nothing from there may be shown
    assert answer["status"] == "abstained" and answer["claims"] == [] and answer["disagreements"] == []
    shown = {s for c in answer["claims"] for s in c["span_ids"]}
    assert not shown and not any(sid.startswith(("D1", "D2")) for sid in answer["sources"])


def test_an_empty_workspace_abstains_without_searching(client):
    chat_id = chat_in(client, "ws_empty")
    r = client.post(f"/api/chats/{chat_id}/ask", json={"question": "What fees apply if I pay an EMI late?"})
    answer = sse(r.text)[-1][1]["assistant"]["answer"]
    assert answer["status"] == "abstained" and answer["claims"] == [] and answer["sources"] == {}
    assert any("No relevant passages" in m for m in answer["missing_evidence"])


def test_the_demo_workspace_still_answers_and_sees_only_its_own_conflict(client):
    chat_id = chat_in(client, DEMO)
    client.patch(f"/api/chats/{chat_id}", json={"as_of_date": "2026-11-22"})
    r = client.post(f"/api/chats/{chat_id}/ask", json={"question": "What fees apply if I pay an EMI late?"})
    answer = sse(r.text)[-1][1]["assistant"]["answer"]
    assert answer["status"] == "conflict"
    assert {s["doc"] for s in answer["disagreements"][0]["sides"]} == {"D1", "D2"}


# ---- HTTP API ---------------------------------------------------------------------------------

def test_listing_endpoints_are_filtered_by_workspace_and_need_one(client):
    ids = lambda ws: {d["doc_id"] for d in client.get("/api/documents", params={"workspace_id": ws}).json()}
    assert ids(DEMO) == {"D1", "D2"} and ids("ws_second") == {"D3", "D5"} and ids("ws_empty") == set()
    for path in ("/api/documents", "/api/chats", "/api/conflicts", "/api/amendments"):
        assert client.get(path).status_code == 422  # a workspace is always required: there is no "everything" view
        assert client.get(path, params={"workspace_id": "nope"}).status_code == 404
    first, other = chat_in(client, DEMO), chat_in(client, "ws_second")
    mine = {c["chat_id"] for c in client.get("/api/chats", params={"workspace_id": DEMO}).json()}
    assert first in mine and other not in mine
    day = {"workspace_id": DEMO, "as_of": "2026-11-22"}
    assert {s["doc"] for c in client.get("/api/conflicts", params=day).json()["cards"] for s in c["sides"]} == {"D1", "D2"}
    assert client.get("/api/conflicts", params={"workspace_id": "ws_second", "as_of": "2026-11-22"}).json()["cards"] == []
    assert client.get("/api/amendments", params=day).json() == {"as_of": "2026-11-22", "timelines": [], "unresolved": []}
    second = client.get("/api/amendments", params={"workspace_id": "ws_second", "as_of": "2026-11-22"}).json()
    assert second["timelines"] == [] and [u["doc_id"] for u in second["unresolved"]] == ["D3"]


def test_the_chat_picker_only_accepts_documents_of_its_own_workspace(client):
    chat_id = chat_in(client, DEMO)
    assert client.patch(f"/api/chats/{chat_id}", json={"doc_scope": ["D5"]}).status_code == 422  # D5 is in ws_second
    assert client.patch(f"/api/chats/{chat_id}", json={"doc_scope": ["D2"]}).json()["doc_scope"] == ["D2"]
    assert client.post("/api/chats", json={"workspace_id": "nope"}).status_code == 404
    assert client.post("/api/chats").status_code == 422


def test_create_rename_and_validate_workspaces(client, monkeypatch):
    made = client.post("/api/workspaces", json={"name": "  Home   loan  "})
    assert made.status_code == 201 and made.json()["name"] == "Home loan"
    ws = made.json()
    assert ws["documents"] == 0 and ws["chats"] == 0 and ws["demo"] is False
    assert client.patch(f"/api/workspaces/{ws['workspace_id']}", json={"name": "Car loan"}).json()["name"] == "Car loan"
    assert client.post("/api/workspaces", json={"name": "   "}).status_code == 422
    assert client.post("/api/workspaces", json={"name": "x" * (config.WORKSPACE_NAME_MAX + 1)}).status_code == 422
    assert client.patch("/api/workspaces/nope", json={"name": "x"}).status_code == 404
    listed = {w["workspace_id"]: w for w in client.get("/api/workspaces").json()}
    assert listed[DEMO]["documents"] == 2 and listed[DEMO]["demo"] is True and listed["ws_second"]["documents"] == 2
    monkeypatch.setattr(config, "MAX_WORKSPACES", len(listed))
    assert client.post("/api/workspaces", json={"name": "One too many"}).status_code == 409
    assert client.delete(f"/api/workspaces/{ws['workspace_id']}").status_code == 204


def test_the_demo_workspace_and_busy_workspaces_cannot_be_deleted(client, env):
    conn, _ = env
    assert client.delete(f"/api/workspaces/{DEMO}").status_code == 409
    assert client.delete("/api/workspaces/nope").status_code == 404
    ws = client.post("/api/workspaces", json={"name": "Busy"}).json()["workspace_id"]
    conn.execute("INSERT INTO documents(doc_id,sha256,workspace_id,status) VALUES('Ubusy','z',?, 'Parsing')", (ws,))
    conn.execute("INSERT INTO ingest_jobs(job_id,doc_id,path,state) VALUES('job_busy','Ubusy','/x.pdf','parsing')")
    conn.commit()
    r = client.delete(f"/api/workspaces/{ws}")
    assert r.status_code == 409 and "still being processed" in r.json()["detail"]
    conn.execute("UPDATE ingest_jobs SET state='needs_ocr' WHERE job_id='job_busy'")  # parked, not running: deletable
    conn.commit()
    assert client.delete(f"/api/workspaces/{ws}").status_code == 204


# ---- deletion -------------------------------------------------------------------------------------

def test_deleting_a_workspace_removes_its_data_and_nothing_else(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    put(conn, tmp_path, DEMO, "D1")
    db.ensure_workspace(conn, "ws_gone", "Gone")
    upload = tmp_path / "uploads" / "abc123" / "D5_fcb_circular.pdf"
    upload.parent.mkdir(parents=True)
    shutil.copy(PDFS / DOCS["D5"], upload)
    pipeline.enqueue(upload, conn, start_worker=False, workspace_id="ws_gone", stable_ids=False)
    pipeline.run_pending(conn, Answerer(), tmp_path)
    chat = db.create_chat(conn, workspace_id="ws_gone")
    db.add_message(conn, chat.chat_id, "user", "hello")
    keep = {r["window_id"] for r in conn.execute("SELECT window_id FROM windows WHERE doc_id='D1'")}
    gone_docs = db.workspace_doc_ids(conn, "ws_gone")
    assert len(gone_docs) == 1 and len(load_index(tmp_path).window_ids) > len(keep)

    assert remove.remove_workspace(conn, "ws_gone", tmp_path) == {"documents": 1, "chats": 1}

    assert db.get_workspace(conn, "ws_gone") is None and db.get_chat(conn, chat.chat_id) is None
    for table in ("documents", "clauses", "spans", "windows", "facts", "ingest_jobs"):
        col = "doc_id"
        left = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (gone_docs[0],)).fetchone()[0] if table != "facts" else 0
        assert left == 0, table
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat.chat_id,)).fetchone()[0] == 0
    assert db.get_document(conn, "D1") is not None and {r["window_id"] for r in conn.execute("SELECT window_id FROM windows")} == keep
    idx = load_index(tmp_path)  # the search index only holds the surviving workspace
    assert set(idx.window_ids) == keep and idx.dense.shape[0] == len(keep)
    assert not upload.exists() and not upload.parent.exists()  # the uploaded copy is deleted
    assert (PDFS / DOCS["D5"]).exists()  # the demo files outside uploads/ never are
