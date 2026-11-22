"""Phase-1 tests for the React UI's HTTP API: chats, SSE ask, enrichment, documents, page images, conflicts, amendments."""
from __future__ import annotations

import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from test_app import Answerer
from test_ingest import corpus  # noqa: F401  (autouse fixture that builds the PDFs)
from test_versions import ingest

from api import deps, serialize
from api.main import create_app
from core import config, db
from core.llm.client import ModelUnavailable
from core.retrieval.hybrid import Retriever


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    conn = db.init_db(tmp / "corpus.db")
    ingest(conn, Answerer(), "D1", "D2", "D3", "D4", "D5", tmp=tmp)
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


def sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        out.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return out


# ---- naming helpers -----------------------------------------------------------------

def test_display_names_are_readable():
    assert serialize.display_name("PERSONAL LOAN AGREEMENT", "agreement", "KF/PLA/2024") == "Personal Loan Agreement"
    assert serialize.display_name("SCHEDULE OF CHARGES — PERSONAL LOANS", "schedule", "KF/SOC/2024") == \
        "Schedule of Charges — Personal Loans"
    assert serialize.display_name("AMENDMENT No. 1 TO PERSONAL LOAN AGREEMENT KF/PLA/2024", "amendment", "x") == "Amendment No. 1"
    assert serialize.display_name("Fair practices on penal charges", "circular", "FCB/2025/17") == "Circular FCB/2025/17"
    assert serialize.clause_label("8.1") == "Clause 8.1" and serialize.clause_label("p1.3") == "Paragraph 3 (page 1)"
    assert serialize.clause_label("table1.row2", "Charge: Late payment fee | Amount: ₹750", True) == "Table row: Late payment fee"


# ---- health, examples, chats ---------------------------------------------------------

def test_health_states(client, monkeypatch):
    assert client.get("/api/health").json()["state"] in ("ready", "warming", "offline")
    monkeypatch.setattr(deps.get_model(), "health", lambda: {"llm": "ready"}, raising=False)
    assert client.get("/api/health").json() == {"state": "ready", "label": "Ready"}

    def down():
        raise ModelUnavailable("x")
    monkeypatch.setattr(deps.get_model(), "health", down, raising=False)
    assert client.get("/api/health").json()["state"] == "offline"
    assert len(client.get("/api/examples").json()) == 3


def test_chat_crud_and_validation(client):
    c = client.post("/api/chats").json()
    assert c["title"] == "New chat" and c["as_of_date"]
    patched = client.patch(f"/api/chats/{c['chat_id']}", json={"title": "  Late fees  ", "as_of_date": "2025-06-01"}).json()
    assert patched["title"] == "Late fees" and patched["as_of_date"] == "2025-06-01"
    assert any(x["chat_id"] == c["chat_id"] for x in client.get("/api/chats").json())
    assert client.get(f"/api/chats/{c['chat_id']}/messages").json() == []
    assert client.delete(f"/api/chats/{c['chat_id']}").status_code == 204
    assert client.get("/api/chats/nope/messages").status_code == 404
    assert client.patch("/api/chats/nope", json={"title": "x"}).status_code == 404


# ---- ask (SSE) + enrichment ----------------------------------------------------------

def test_ask_streams_stages_then_a_readable_answer(client):
    chat = client.post("/api/chats").json()
    chat_id = chat["chat_id"]
    client.patch(f"/api/chats/{chat_id}", json={"as_of_date": "2026-11-22"})
    r = client.post(f"/api/chats/{chat_id}/ask", json={"question": "What fees apply if I pay an EMI late?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "stage" and kinds[-1] == "answer" and "error" not in kinds
    steps = [d["step"] for k, d in events if k == "stage"]
    assert steps == sorted(steps) and any(d["label"] == "Checking every statement against the documents"
                                          for k, d in events if k == "stage")
    answer = events[-1][1]["assistant"]["answer"]
    assert answer["status"] == "conflict" and events[-1][1]["chat"]["title"].startswith("What fees apply")
    src = answer["sources"]
    d1 = src["D1:8.1#s1"]
    assert d1["doc_name"] == "Personal Loan Agreement" and d1["clause_label"] == "Clause 8.1" and d1["page"] == 4
    assert d1["status"] == "in_force" and d1["bboxes"] and d1["page_width"] > 0 and d1["n"] == 1
    d2 = src["D2:table1.row2#s1"]
    assert d2["clause_label"] == "Table row: Late payment fee" and d2["row"]["Amount"] == "₹750 per instalment"
    assert answer["citations"][:2] == ["D1:8.1#s1", "D2:table1.row2#s1"]
    card = answer["disagreements"][0]
    assert card["subject"] == "late_payment_fee" and {s["op"] for s in card["sides"]} >= {"eq", "max"}
    assert {s["doc_name"] for s in card["sides"]} == {"Personal Loan Agreement", "Schedule of Charges — Personal Loans",
                                                     "Circular FCB/2025/17"}  # readable names inside answers too
    assert all(s["clause_label"] and s["bboxes"] for s in card["sides"])
    msgs = client.get(f"/api/chats/{chat_id}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["answer"]["sources"]


def test_ask_rejects_empty_question_and_unknown_chat(client):
    chat_id = client.post("/api/chats").json()["chat_id"]
    assert client.post(f"/api/chats/{chat_id}/ask", json={"question": "   "}).status_code == 422
    assert client.post("/api/chats/nope/ask", json={"question": "hi"}).status_code == 404


def test_ask_reports_model_outage_as_an_error_event(client, monkeypatch):
    chat_id = client.post("/api/chats").json()["chat_id"]

    def boom(*a, **k):
        raise ModelUnavailable("down")
    monkeypatch.setattr("api.routes.chats.assemble.answer", boom)
    events = sse(client.post(f"/api/chats/{chat_id}/ask", json={"question": "anything"}).text)
    assert events[-1][0] == "error" and "not reachable" in events[-1][1]["message"]


# ---- sources, documents, images -------------------------------------------------------

def test_single_source_lookup_with_encoded_hash(client):
    r = client.get(f"/api/spans/{quote('D1:7.2#s1', safe='')}", params={"as_of": "2026-11-22"})
    assert r.status_code == 200 and r.json()["status"] == "superseded" and r.json()["doc_name"] == "Personal Loan Agreement"
    assert client.get("/api/spans/D9:1%23s1").status_code == 404


def test_documents_outline_and_pages(client):
    docs = {d["doc_id"]: d for d in client.get("/api/documents").json()}
    assert docs["D1"]["status_label"] == "Ready" and docs["D3"]["name"] == "Amendment No. 1" and not docs["D1"]["busy"]
    outline = {c["clause_id"]: c for c in client.get("/api/documents/D1/outline", params={"as_of": "2026-11-22"}).json()}
    assert outline["D1:7.2"]["status"] == "superseded" and outline["D1:7.2"]["replaced_by"] == "D4:1"
    assert outline["D1:5.1"]["status"] == "in_force" and outline["D1:7.2"]["label"] == "Clause 7.2"
    png = client.get("/api/documents/D1/pages/4/image")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n" and "max-age" in png.headers["cache-control"]
    assert client.get("/api/documents/D1/pages/99/image").status_code == 404
    assert client.get("/api/documents/NOPE/pages/1/image").status_code == 404
    assert client.get("/api/documents/NOPE/outline").status_code == 404
    assert client.get("/api/documents/D1/file").headers["content-type"] == "application/pdf"


def test_upload_validates_pdfs_and_queues(client, monkeypatch, env):
    conn = env[0]
    job = conn.execute("SELECT job_id FROM ingest_jobs WHERE doc_id='D5'").fetchone()["job_id"]
    queued = []
    monkeypatch.setattr("api.routes.documents.pipeline.enqueue", lambda path, c: queued.append(path) or job)
    ok = client.post("/api/documents", files=[("files", ("../evil name.pdf", b"%PDF-1.4 fake", "application/pdf"))])
    assert ok.status_code == 202 and ok.json()[0]["doc_id"] == "D5"
    assert queued and queued[0].parent.name == "uploads" and ".." not in queued[0].name  # sanitised file name
    bad = client.post("/api/documents", files=[("files", ("notes.pdf", b"hello", "application/pdf"))])
    assert bad.status_code == 422 and "not a PDF" in bad.json()["detail"]


# ---- conflicts and amendments ------------------------------------------------------------

def test_conflicts_endpoint_filters_by_date(client):
    now = client.get("/api/conflicts", params={"as_of": "2026-11-22"}).json()
    assert len(now["cards"]) == 1 and {s["doc"] for s in now["cards"][0]["sides"]} == {"D1", "D2", "D5"}
    side = next(s for s in now["cards"][0]["sides"] if s["doc"] == "D2")
    assert side["doc_name"].startswith("Schedule of Charges") and side["clause_label"] == "Table row: Late payment fee", side
    early = client.get("/api/conflicts", params={"as_of": "2025-06-01"}).json()
    assert {s["doc"] for s in early["cards"][0]["sides"]} == {"D1", "D2"}  # the circular is not in force yet
    assert client.get("/api/conflicts", params={"as_of": "2023-01-01"}).json()["cards"] == []


def test_amendments_endpoint_gives_a_timeline_with_the_current_text(client):
    data = client.get("/api/amendments", params={"as_of": "2026-11-22"}).json()
    tl = data["timelines"][0]
    assert tl["version_key"] == "D1:7.2" and tl["label"] == "Clause 7.2" and tl["in_force_step"] == 2
    assert [s["doc_name"] for s in tl["steps"]] == ["Personal Loan Agreement", "Amendment No. 1", "Amendment No. 2"]
    assert tl["steps"][1]["source"]["clause_label"] == "Clause 1" and tl["current"]["doc_name"] == "Amendment No. 2"
    old = client.get("/api/amendments", params={"as_of": "2025-06-01"}).json()["timelines"][0]
    assert old["in_force_step"] == 1 and data["unresolved"] == []
