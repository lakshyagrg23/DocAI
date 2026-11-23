"""Remove a workspace and everything derived from it (ADR-024). Lives in core/ingest because it writes the ingest tables."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core import config
from core.ingest import store
from core.retrieval import index


def _delete_upload(conn: sqlite3.Connection, doc_id: str, data_dir: Path | None) -> None:
    """Delete the uploaded PDF of a document, but only inside DATA_DIR/uploads and only when no other document uses the file
    (the same upload folder is shared by identical content in other workspaces)."""
    root = ((data_dir or config.DATA_DIR) / "uploads").resolve()
    for job in conn.execute("SELECT path FROM ingest_jobs WHERE doc_id=?", (doc_id,)).fetchall():
        path = Path(job["path"]).resolve()
        shared = conn.execute("SELECT 1 FROM ingest_jobs WHERE path=? AND doc_id!=?", (job["path"], doc_id)).fetchone()
        if path.is_relative_to(root) and not shared and path.is_file():
            path.unlink()
            if not any(path.parent.iterdir()):
                path.parent.rmdir()


def remove_document(conn: sqlite3.Connection, doc_id: str, data_dir: Path | None = None) -> None:
    """Delete one document and all its derived rows. Used only when its whole workspace goes (no rescan is needed then)."""
    conn.execute("DELETE FROM conflicts WHERE fact_a IN (SELECT f.fact_id FROM facts f JOIN clauses c ON c.clause_id=f.clause_id "
                 "WHERE c.doc_id=?) OR fact_b IN (SELECT f.fact_id FROM facts f JOIN clauses c ON c.clause_id=f.clause_id "
                 "WHERE c.doc_id=?)", (doc_id, doc_id))
    conn.execute("DELETE FROM clause_versions WHERE clause_id LIKE ? OR version_key LIKE ?", (f"{doc_id}:%", f"{doc_id}:%"))
    store.delete_doc_content(conn, doc_id)
    index.remove_doc(conn, doc_id, data_dir)
    _delete_upload(conn, doc_id, data_dir)
    conn.execute("DELETE FROM ingest_jobs WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
    conn.commit()


def remove_workspace(conn: sqlite3.Connection, workspace_id: str, data_dir: Path | None = None) -> dict[str, int]:
    """Delete a workspace: its chats and messages, its documents (rows, index entries, uploads) and the workspace itself.
    Other workspaces are untouched: ids, edges, versions and conflicts never cross a workspace boundary."""
    docs = [r["doc_id"] for r in conn.execute("SELECT doc_id FROM documents WHERE workspace_id=?", (workspace_id,))]
    chats = [r["chat_id"] for r in conn.execute("SELECT chat_id FROM chats WHERE workspace_id=?", (workspace_id,))]
    for doc_id in docs:
        remove_document(conn, doc_id, data_dir)
    for chat_id in chats:
        conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM workspaces WHERE workspace_id=?", (workspace_id,))
    conn.commit()
    return {"documents": len(docs), "chats": len(chats)}
