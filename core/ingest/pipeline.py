"""Ingest orchestration: job queue in SQLite + one worker thread (ingest.md, architecture.md).

States: queued -> parsing -> (ocr) -> extracting -> resolving -> ready | failed | needs_ocr.
Facts and amendments run as POST_STAGES; the conflict scan runs after them.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import traceback
from collections.abc import Callable
from pathlib import Path

import pymupdf

from core import config, db
from core.ingest import amendments, conflicts, extract, register, store
from core.ingest.parse import page_needs_ocr, parse_pdf
from core.ingest.segment import segment
from core.llm.client import ModelClient, get_client
from core.retrieval import index

log = logging.getLogger("ingest")
PostStage = Callable[[sqlite3.Connection, str, ModelClient], None]
POST_STAGES: list[tuple[str, PostStage]] = [  # (doc status label, fn)
    ("Extracting facts", extract.run),
    ("Resolving amendments", amendments.run),
    ("Checking conflicts", conflicts.run),
]

_lock = threading.Lock()
_thread: threading.Thread | None = None


def ocr_available() -> bool:
    from core.ingest import ocr
    return ocr.available()


def _set_job(conn: sqlite3.Connection, job_id: str, state: str, error: str | None = None) -> None:
    conn.execute("UPDATE ingest_jobs SET state=?, error=?, updated_at=? WHERE job_id=?",
                 (state, error, db.now_iso(), job_id))
    conn.commit()


def enqueue(path: Path | str, conn: sqlite3.Connection | None = None, start_worker: bool = True) -> str:
    """Register the file cheaply (sha, id, row) and queue it. A known sha returns the existing doc's latest job."""
    own = conn is None
    conn = conn or db.init_db()
    path = Path(path)
    sha = register.sha256_file(path)
    row = conn.execute("SELECT doc_id FROM documents WHERE sha256=?", (sha,)).fetchone()
    if row:
        job = conn.execute("SELECT job_id,state FROM ingest_jobs WHERE doc_id=? ORDER BY created_at DESC LIMIT 1",
                           (row["doc_id"],)).fetchone()
        if job and job["state"] == "needs_ocr" and ocr_available():  # parked earlier; the scanned pages can be read now
            _set_job(conn, job["job_id"], "queued")
        if job:
            if start_worker and job["state"] in ("queued", "needs_ocr"):
                _ensure_worker()
            return job["job_id"]
        doc_id = row["doc_id"]
    else:
        doc_id = register.make_doc_id(path.name, sha)
        db.upsert_document(conn, register.build_document(doc_id, path, sha, None))
    job_id = db.new_id("job")
    now = db.now_iso()
    conn.execute("INSERT INTO ingest_jobs(job_id,doc_id,path,state,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                 (job_id, doc_id, str(path), "queued", None, now, now))
    conn.commit()
    if start_worker:
        _ensure_worker()
    if own:
        conn.close()
    return job_id


def process_job(conn: sqlite3.Connection, job_id: str, client: ModelClient | None = None,
                data_dir: Path | None = None) -> str:
    """Run one job end to end. Returns the final job state."""
    job = conn.execute("SELECT * FROM ingest_jobs WHERE job_id=?", (job_id,)).fetchone()
    doc_id, path = job["doc_id"], Path(job["path"])
    client = client or get_client()
    try:
        _set_job(conn, job_id, "parsing")
        db.set_document_status(conn, doc_id, "Parsing", "reading metadata")
        sha = register.sha256_file(path)
        meta, source = register.extract_meta(register.first_page_text(path), path.name, client)
        doc = register.build_document(doc_id, path, sha, meta)
        if source == "heuristic" and doc.status_detail is None:
            doc.status_detail = "metadata by heuristics"
        db.upsert_document(conn, doc)

        with pymupdf.open(path) as pdf:
            scanned = [i for i, p in enumerate(pdf, 1) if page_needs_ocr(p)]
            n_pages = len(pdf)
        conn.execute("UPDATE documents SET pages=?, has_ocr=? WHERE doc_id=?", (n_pages, int(bool(scanned)), doc_id))
        conn.commit()
        if scanned and not ocr_available():
            conn.execute("UPDATE documents SET effective_date=NULL WHERE doc_id=?", (doc_id,))  # no text yet: don't guess
            db.set_document_status(conn, doc_id, "Queued", "needs OCR (Tesseract is not installed)")
            _set_job(conn, job_id, "needs_ocr")
            return "needs_ocr"

        store.delete_doc_content(conn, doc_id)
        db.set_document_status(conn, doc_id, "Parsing", "parsing pages")
        pages = parse_pdf(path, on_ocr=lambda i, n: db.set_document_status(conn, doc_id, "OCR", f"OCR page {i}/{n}"))
        store.save_pages(conn, doc_id, pages)
        if pages and pages[0].is_ocr:  # a scanned first page had no text at registration: read the metadata from the OCR text
            text = "\n".join(ln.text for ln in pages[0].lines)[:config.REGISTER_PAGE_CHARS]
            meta, _ = register.extract_meta(text, path.name, client)
            doc = register.build_document(doc_id, path, sha, meta)
            db.upsert_document(conn, doc)
            conn.execute("UPDATE documents SET pages=?, has_ocr=1 WHERE doc_id=?", (n_pages, doc_id))
            conn.commit()
        db.set_document_status(conn, doc_id, "Parsing", "segmenting clauses")
        clauses, spans = segment(doc_id, pages)
        conf = {p.page_no: p.ocr_conf for p in pages if p.is_ocr and p.ocr_conf is not None}
        for sp in spans:
            sp.ocr_conf = conf.get(sp.page)  # a non-null ocr_conf is what marks a span as scanned
        store.save_clauses(conn, clauses, spans)
        db.set_document_status(conn, doc_id, "Parsing", "indexing")
        index.reindex_doc(conn, doc_id, client.embed, data_dir)
        for label, fn in POST_STAGES:
            db.set_document_status(conn, doc_id, label)
            fn(conn, doc_id, client)
        db.set_document_status(conn, doc_id, "Ready", doc.status_detail)
        _set_job(conn, job_id, "ready")
        return "ready"
    except Exception as e:  # noqa: BLE001 - the worker must survive any single bad document
        log.error("ingest failed for %s: %s", doc_id, traceback.format_exc())
        db.set_document_status(conn, doc_id, "Failed", f"{type(e).__name__}: {e}"[:300])
        _set_job(conn, job_id, "failed", str(e)[:500])
        return "failed"


def run_pending(conn: sqlite3.Connection, client: ModelClient | None = None, data_dir: Path | None = None) -> int:
    """Process queued jobs one at a time, oldest first. Returns how many ran."""
    n = 0
    while (row := conn.execute("SELECT job_id FROM ingest_jobs WHERE state='queued' ORDER BY created_at, job_id LIMIT 1")
           .fetchone()):
        process_job(conn, row["job_id"], client, data_dir)
        n += 1
    return n


def _worker() -> None:
    global _thread
    conn = db.init_db()
    while True:
        run_pending(conn)
        with _lock:
            if not conn.execute("SELECT 1 FROM ingest_jobs WHERE state='queued' LIMIT 1").fetchone():
                _thread = None
                conn.close()
                return


def _ensure_worker() -> None:
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, name="ingest-worker", daemon=True)
            _thread.start()


def document_status(conn: sqlite3.Connection, doc_id: str) -> tuple[str, str | None]:
    r = conn.execute("SELECT status,status_detail FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return (r["status"], r["status_detail"]) if r else ("Unknown", None)

