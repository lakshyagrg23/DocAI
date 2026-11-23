"""SQLite schema + basic data access (data-model.md)."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ulid import ULID

from core import config
from core.models import Chat, Document, Message, Workspace

# The same PDF may live in two workspaces, so the content hash is unique per workspace, not globally (ADR-024).
DOCUMENTS_DDL = """CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY, title TEXT, doc_type TEXT,
  issuer TEXT, ref_no TEXT, ref_aliases TEXT,
  issue_date TEXT, effective_date TEXT,
  sha256 TEXT, filename TEXT, pages INT, has_ocr INT DEFAULT 0, language TEXT DEFAULT 'en',
  status TEXT, status_detail TEXT, created_at TEXT, workspace_id TEXT,
  UNIQUE(workspace_id, sha256));
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces(workspace_id TEXT PRIMARY KEY, name TEXT, created_at TEXT);
""" + DOCUMENTS_DDL + """
CREATE TABLE IF NOT EXISTS pages(doc_id TEXT, page_no INT, width REAL, height REAL, is_ocr INT, ocr_conf REAL,
  PRIMARY KEY(doc_id, page_no));
CREATE TABLE IF NOT EXISTS clauses(
  clause_id TEXT PRIMARY KEY, doc_id TEXT, path TEXT, heading_trail TEXT, kind TEXT,
  text TEXT, page_start INT, page_end INT, parent_id TEXT, version_key TEXT, ord INT);
CREATE TABLE IF NOT EXISTS spans(
  span_id TEXT PRIMARY KEY, clause_id TEXT, doc_id TEXT, page INT,
  text TEXT, bboxes TEXT,
  char_start INT, char_end INT, is_table_row INT DEFAULT 0, ocr_conf REAL);
CREATE TABLE IF NOT EXISTS windows(
  window_id TEXT PRIMARY KEY, clause_id TEXT, doc_id TEXT, text TEXT, span_ids TEXT, row_idx INT);
CREATE TABLE IF NOT EXISTS subjects(subject_id TEXT PRIMARY KEY, label TEXT, aliases TEXT, emb_row INT);
CREATE TABLE IF NOT EXISTS facts(
  fact_id TEXT PRIMARY KEY, clause_id TEXT, span_id TEXT, subject_id TEXT,
  attribute TEXT, op TEXT, value_type TEXT, value_norm TEXT,
  value_raw TEXT, scope TEXT, modality TEXT, condition_text TEXT);
CREATE TABLE IF NOT EXISTS amendment_edges(
  edge_id TEXT PRIMARY KEY, source_clause_id TEXT, target_doc_id TEXT, target_path TEXT,
  action TEXT, new_text_span_ids TEXT, effective_date TEXT, evidence_span_ids TEXT,
  confidence REAL, resolved INT, raw_target_ref TEXT);
CREATE TABLE IF NOT EXISTS clause_versions(
  version_key TEXT, version_no INT, clause_id TEXT,
  valid_from TEXT, valid_to TEXT,
  edge_id TEXT, PRIMARY KEY(version_key, version_no));
CREATE TABLE IF NOT EXISTS conflicts(
  conflict_id TEXT PRIMARY KEY, subject_id TEXT, fact_a TEXT, fact_b TEXT,
  type TEXT, overlap_from TEXT, overlap_to TEXT, detected_by TEXT, explanation TEXT, severity TEXT,
  differing TEXT,
  UNIQUE(fact_a, fact_b));
CREATE TABLE IF NOT EXISTS chats(chat_id TEXT PRIMARY KEY, title TEXT, created_at TEXT, as_of_date TEXT,
  language TEXT DEFAULT 'auto', doc_scope TEXT, workspace_id TEXT);
CREATE TABLE IF NOT EXISTS messages(msg_id TEXT PRIMARY KEY, chat_id TEXT, role TEXT, content TEXT,
  answer_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS ingest_jobs(job_id TEXT PRIMARY KEY, doc_id TEXT, path TEXT, state TEXT, error TEXT,
  created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_spans_clause ON spans(clause_id);
CREATE INDEX IF NOT EXISTS ix_clauses_doc ON clauses(doc_id);
CREATE INDEX IF NOT EXISTS ix_clauses_vkey ON clauses(version_key);
CREATE INDEX IF NOT EXISTS ix_facts_subject ON facts(subject_id);
CREATE INDEX IF NOT EXISTS ix_facts_clause ON facts(clause_id);
CREATE INDEX IF NOT EXISTS ix_edges_target ON amendment_edges(target_doc_id, target_path);
CREATE INDEX IF NOT EXISTS ix_messages_chat ON messages(chat_id);
"""

TABLES = [
    "workspaces", "documents", "pages", "clauses", "spans", "windows", "subjects", "facts",
    "amendment_edges", "clause_versions", "conflicts", "chats", "messages", "ingest_jobs",
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{str(ULID()).lower()}"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _has_global_sha_unique(conn: sqlite3.Connection) -> bool:
    for idx in conn.execute("PRAGMA index_list(documents)").fetchall():
        if idx["unique"] and [c["name"] for c in conn.execute(f"PRAGMA index_info({idx['name']})")] == ["sha256"]:
            return True
    return False


def migrate(conn: sqlite3.Connection) -> None:
    """Bring a database created before workspaces (ADR-024) up to date. Idempotent; a no-op on a current database.

    Everything that existed before (documents, chats) is put into the default workspace, so no data is lost or hidden."""
    for table in ("documents", "chats"):
        if "workspace_id" not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT")
    if _has_global_sha_unique(conn):  # SQLite cannot drop a constraint: rebuild the table with the per-workspace one
        cols = ",".join(_columns(conn, "documents"))
        conn.executescript("ALTER TABLE documents RENAME TO documents_old;" + DOCUMENTS_DDL)
        conn.execute(f"INSERT INTO documents({cols}) SELECT {cols} FROM documents_old")
        conn.execute("DROP TABLE documents_old")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_docs_ws ON documents(workspace_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_chats_ws ON chats(workspace_id)")
    orphans = conn.execute("SELECT (SELECT COUNT(*) FROM documents WHERE workspace_id IS NULL)"
                           " + (SELECT COUNT(*) FROM chats WHERE workspace_id IS NULL)").fetchone()[0]
    if orphans:
        ensure_workspace(conn, config.DEFAULT_WORKSPACE_ID, config.DEFAULT_WORKSPACE_NAME)
        for table in ("documents", "chats"):
            conn.execute(f"UPDATE {table} SET workspace_id=? WHERE workspace_id IS NULL", (config.DEFAULT_WORKSPACE_ID,))
    conn.commit()


# --- workspaces --------------------------------------------------------------

def ensure_workspace(conn: sqlite3.Connection, workspace_id: str, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO workspaces(workspace_id,name,created_at) VALUES(?,?,?)",
                 (workspace_id, name, now_iso()))
    conn.commit()


def create_workspace(conn: sqlite3.Connection, name: str) -> Workspace:
    ws = Workspace(workspace_id=new_id("ws"), name=name, created_at=now_iso())
    conn.execute("INSERT INTO workspaces(workspace_id,name,created_at) VALUES(?,?,?)", (ws.workspace_id, ws.name, ws.created_at))
    conn.commit()
    return ws


def get_workspace(conn: sqlite3.Connection, workspace_id: str) -> Workspace | None:
    r = conn.execute("SELECT * FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
    return Workspace(**dict(r)) if r else None


def list_workspaces(conn: sqlite3.Connection) -> list[dict]:
    """Workspaces (oldest first) with their document and chat counts."""
    rows = conn.execute(
        "SELECT w.*, (SELECT COUNT(*) FROM documents d WHERE d.workspace_id=w.workspace_id) AS documents,"
        " (SELECT COUNT(*) FROM documents d WHERE d.workspace_id=w.workspace_id AND d.status='Ready') AS ready,"
        " (SELECT COUNT(*) FROM chats c WHERE c.workspace_id=w.workspace_id) AS chats "
        "FROM workspaces w ORDER BY w.created_at, w.workspace_id").fetchall()
    return [dict(r) for r in rows]


def rename_workspace(conn: sqlite3.Connection, workspace_id: str, name: str) -> None:
    conn.execute("UPDATE workspaces SET name=? WHERE workspace_id=?", (name, workspace_id))
    conn.commit()


def workspace_doc_ids(conn: sqlite3.Connection, workspace_id: str) -> list[str]:
    return [r["doc_id"] for r in conn.execute("SELECT doc_id FROM documents WHERE workspace_id=? ORDER BY doc_id", (workspace_id,))]


def chat_doc_scope(conn: sqlite3.Connection, chat: Chat) -> list[str] | None:
    """The documents a chat may use: its workspace's documents, narrowed by the chat's own picker when it has one.

    A list is a hard boundary even when empty (an empty workspace must not fall back to "everything").
    None only for a chat without a workspace (legacy callers), where the chat's own scope, if any, applies."""
    if chat.workspace_id is None:
        return chat.doc_scope
    allowed = workspace_doc_ids(conn, chat.workspace_id)
    if chat.doc_scope:
        keep = set(chat.doc_scope)
        return [d for d in allowed if d in keep]
    return allowed


# --- documents ---------------------------------------------------------------

def upsert_document(conn: sqlite3.Connection, doc: Document) -> None:
    conn.execute(
        """INSERT INTO documents(doc_id,title,doc_type,issuer,ref_no,ref_aliases,issue_date,effective_date,
             sha256,filename,pages,has_ocr,language,status,status_detail,created_at,workspace_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(doc_id) DO UPDATE SET title=excluded.title, doc_type=excluded.doc_type,
             issuer=excluded.issuer, ref_no=excluded.ref_no, ref_aliases=excluded.ref_aliases,
             issue_date=excluded.issue_date, effective_date=excluded.effective_date,
             filename=excluded.filename, pages=excluded.pages, has_ocr=excluded.has_ocr,
             language=excluded.language, status=excluded.status, status_detail=excluded.status_detail""",
        (doc.doc_id, doc.title, doc.doc_type, doc.issuer, doc.ref_no, json.dumps(doc.ref_aliases),
         doc.issue_date, doc.effective_date, doc.sha256, doc.filename, doc.pages, int(doc.has_ocr),
         doc.language, doc.status, doc.status_detail, doc.created_at or now_iso(), doc.workspace_id),
    )
    conn.commit()


def _doc_from_row(r: sqlite3.Row) -> Document:
    d = dict(r)
    d["ref_aliases"] = json.loads(d["ref_aliases"] or "[]")
    d["has_ocr"] = bool(d["has_ocr"])
    return Document(**d)


def get_document(conn: sqlite3.Connection, doc_id: str) -> Document | None:
    r = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return _doc_from_row(r) if r else None


def list_documents(conn: sqlite3.Connection, workspace_id: str | None = None) -> list[Document]:
    if workspace_id is None:
        rows = conn.execute("SELECT * FROM documents ORDER BY doc_id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM documents WHERE workspace_id=? ORDER BY doc_id", (workspace_id,)).fetchall()
    return [_doc_from_row(r) for r in rows]


def workspace_of_doc(conn: sqlite3.Connection, doc_id: str) -> str | None:
    r = conn.execute("SELECT workspace_id FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return r["workspace_id"] if r else None


def set_document_status(conn: sqlite3.Connection, doc_id: str, status: str, detail: str | None = None) -> None:
    conn.execute("UPDATE documents SET status=?, status_detail=? WHERE doc_id=?", (status, detail, doc_id))
    conn.commit()


# --- chats / messages --------------------------------------------------------

def create_chat(conn: sqlite3.Connection, title: str = "New chat", as_of_date: str | None = None,
                workspace_id: str | None = None) -> Chat:
    chat = Chat(chat_id=new_id("chat"), title=title, created_at=now_iso(), as_of_date=as_of_date, workspace_id=workspace_id)
    conn.execute(
        "INSERT INTO chats(chat_id,title,created_at,as_of_date,language,doc_scope,workspace_id) VALUES(?,?,?,?,?,?,?)",
        (chat.chat_id, chat.title, chat.created_at, chat.as_of_date, chat.language, None, workspace_id),
    )
    conn.commit()
    return chat


def _chat_from_row(r: sqlite3.Row) -> Chat:
    d = dict(r)
    d["doc_scope"] = json.loads(d["doc_scope"]) if d["doc_scope"] else None
    return Chat(**d)


def list_chats(conn: sqlite3.Connection, workspace_id: str | None = None) -> list[Chat]:
    if workspace_id is None:
        rows = conn.execute("SELECT * FROM chats ORDER BY created_at DESC, chat_id DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM chats WHERE workspace_id=? ORDER BY created_at DESC, chat_id DESC",
                            (workspace_id,)).fetchall()
    return [_chat_from_row(r) for r in rows]


def get_chat(conn: sqlite3.Connection, chat_id: str) -> Chat | None:
    r = conn.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
    return _chat_from_row(r) if r else None


def rename_chat(conn: sqlite3.Connection, chat_id: str, title: str) -> None:
    conn.execute("UPDATE chats SET title=? WHERE chat_id=?", (title, chat_id))
    conn.commit()


def delete_chat(conn: sqlite3.Connection, chat_id: str) -> None:
    conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))
    conn.commit()


def add_message(conn: sqlite3.Connection, chat_id: str, role: str, content: str,
                answer_json: str | None = None) -> Message:
    msg = Message(msg_id=new_id("m"), chat_id=chat_id, role=role, content=content,  # type: ignore[arg-type]
                  answer_json=answer_json, created_at=now_iso())
    conn.execute(
        "INSERT INTO messages(msg_id,chat_id,role,content,answer_json,created_at) VALUES(?,?,?,?,?,?)",
        (msg.msg_id, msg.chat_id, msg.role, msg.content, msg.answer_json, msg.created_at),
    )
    conn.commit()
    return msg


def list_messages(conn: sqlite3.Connection, chat_id: str) -> list[Message]:
    rows = conn.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY created_at, msg_id", (chat_id,)).fetchall()
    return [Message(**dict(r)) for r in rows]


def update_chat_settings(conn: sqlite3.Connection, chat_id: str, as_of_date: str | None = None,
                         language: str | None = None, doc_scope: list[str] | None = None) -> None:
    """Persist the per-chat settings (as-of date, language, document scope); None leaves a field unchanged."""
    if as_of_date is not None:
        conn.execute("UPDATE chats SET as_of_date=? WHERE chat_id=?", (as_of_date, chat_id))
    if language is not None:
        conn.execute("UPDATE chats SET language=? WHERE chat_id=?", (language, chat_id))
    if doc_scope is not None:
        conn.execute("UPDATE chats SET doc_scope=? WHERE chat_id=?", (json.dumps(doc_scope) if doc_scope else None, chat_id))
    conn.commit()
