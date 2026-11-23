"""Documents: list with live ingest status, upload, clause outline, page images (design/ui-react.md §5)."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from api import access, deps, serialize
from core import config, versions
from core.ingest import pipeline
from core.render import highlight

router = APIRouter(prefix="/api")
STATUS_PLAIN = {"Queued": "Waiting", "Parsing": "Reading the document", "OCR": "Reading the scanned pages", "Extracting facts": "Finding facts and amounts",
                "Resolving amendments": "Linking amendments", "Checking conflicts": "Comparing with other documents",
                "Ready": "Ready", "Failed": "Failed"}
BUSY = {"Parsing", "OCR", "Extracting facts", "Resolving amendments", "Checking conflicts"}


def _count(conn: sqlite3.Connection, sql: str, doc_id: str) -> int:
    return conn.execute(sql, (doc_id,)).fetchone()[0]


def _doc_out(conn: sqlite3.Connection, d: sqlite3.Row) -> dict:
    status, detail = d["status"], d["status_detail"] or ""
    needs_ocr = detail.startswith("needs OCR")
    return {"doc_id": d["doc_id"], "name": serialize.display_name(d["title"], d["doc_type"], d["ref_no"]),
            "sub": serialize.doc_sub(d["doc_type"], d["ref_no"]), "type": d["doc_type"], "ref_no": d["ref_no"],
            "issued": d["issue_date"], "effective": d["effective_date"], "pages": d["pages"], "ocr": bool(d["has_ocr"]),
            "clauses": _count(conn, "SELECT COUNT(*) FROM clauses WHERE doc_id=?", d["doc_id"]),
            "facts": _count(conn, "SELECT COUNT(*) FROM facts f JOIN clauses c ON c.clause_id=f.clause_id WHERE c.doc_id=?",
                            d["doc_id"]),
            "status": status, "status_label": STATUS_PLAIN.get(status, status),
            "busy": status in BUSY or (status == "Queued" and not needs_ocr),
            "detail": detail or None, "needs_ocr": needs_ocr}


@router.get("/documents")
def list_documents(workspace_id: str, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> list[dict]:
    deps.require_workspace(conn, workspace_id)
    return [_doc_out(conn, d) for d in conn.execute("SELECT * FROM documents WHERE workspace_id=? ORDER BY doc_id", (workspace_id,))]


@router.post("/documents", status_code=202)
async def upload(request: Request, workspace_id: str, files: list[UploadFile],
                 conn: sqlite3.Connection = Depends(deps.conn_dep)) -> list[dict]:
    deps.require_workspace(conn, workspace_id)
    access.limit_upload(request, len(files))
    dest_dir = config.DATA_DIR / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(f.filename or "upload.pdf").name)
        if f.size is not None and f.size > access.UPLOAD_MAX_BYTES:
            raise HTTPException(413, f"{name} is larger than {access.UPLOAD_MAX_BYTES // (1024 * 1024)} MB")
        data = await f.read()
        if len(data) > access.UPLOAD_MAX_BYTES:
            raise HTTPException(413, f"{name} is larger than {access.UPLOAD_MAX_BYTES // (1024 * 1024)} MB")
        if not name.lower().endswith(".pdf") or not data.startswith(b"%PDF"):
            raise HTTPException(422, f"{name} is not a PDF file")
        sub = dest_dir / hashlib.sha256(data).hexdigest()[:16]  # one folder per content: same name never overwrites a file
        sub.mkdir(parents=True, exist_ok=True)
        dest = sub / name
        dest.write_bytes(data)
        job = pipeline.enqueue(dest, conn, stable_ids=False, workspace_id=workspace_id)
        doc_id = conn.execute("SELECT doc_id FROM ingest_jobs WHERE job_id=?", (job,)).fetchone()["doc_id"]
        out.append(_doc_out(conn, conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()))
    return out


@router.get("/documents/{doc_id}/outline")
def outline(doc_id: str, as_of: str | None = None, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> list[dict]:
    as_of = as_of or deps.today()
    if conn.execute("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)).fetchone() is None:
        raise HTTPException(404, "document not found")
    rows = conn.execute("SELECT clause_id,path,kind,text,page_start,version_key FROM clauses WHERE doc_id=? ORDER BY ord",
                        (doc_id,))
    out = []
    for c in rows:
        status = versions.status(conn, c["clause_id"], as_of)
        repl = versions.clause_in_force(conn, c["version_key"], as_of) if status == "superseded" else None
        out.append({"clause_id": c["clause_id"], "label": serialize.clause_label(c["path"]), "page": c["page_start"],
                    "text": c["text"], "status": status, "replaced_by": repl})
    return out


@router.get("/documents/{doc_id}/pages/{page}/image")
def page_image(doc_id: str, page: int, dpi: int = 120, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> Response:
    path = highlight.pdf_path(conn, doc_id)
    if path is None:
        raise HTTPException(404, "the original PDF is not available on this server")
    if not 1 <= page <= highlight.page_count(path):
        raise HTTPException(404, "page out of range")
    return Response(highlight.render(path, page, [], dpi=min(max(dpi, 60), 220)), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/documents/{doc_id}/file")
def original(doc_id: str, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> FileResponse:
    path = highlight.pdf_path(conn, doc_id)
    if path is None:
        raise HTTPException(404, "the original PDF is not available on this server")
    return FileResponse(path, media_type="application/pdf")
