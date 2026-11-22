"""Ingest-side DB writes for pages, clauses, spans (only core/ingest writes these tables)."""
from __future__ import annotations

import json
import sqlite3

from core.ingest.parse import PageContent
from core.models import Clause, Span


def delete_doc_content(conn: sqlite3.Connection, doc_id: str) -> None:
    """Idempotent re-ingest: remove everything derived from a document (index rows are handled by retrieval.index)."""
    conn.execute("DELETE FROM facts WHERE clause_id IN (SELECT clause_id FROM clauses WHERE doc_id=?)", (doc_id,))
    conn.execute("DELETE FROM amendment_edges WHERE source_clause_id IN (SELECT clause_id FROM clauses WHERE doc_id=?)",
                 (doc_id,))
    for table in ("spans", "clauses", "windows", "pages"):
        conn.execute(f"DELETE FROM {table} WHERE doc_id=?", (doc_id,))
    conn.commit()


def save_pages(conn: sqlite3.Connection, doc_id: str, pages: list[PageContent]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO pages(doc_id,page_no,width,height,is_ocr,ocr_conf) VALUES(?,?,?,?,?,?)",
        [(doc_id, p.page_no, p.width, p.height, int(p.is_ocr), p.ocr_conf) for p in pages])
    conn.commit()


def save_clauses(conn: sqlite3.Connection, clauses: list[Clause], spans: list[Span]) -> None:
    conn.executemany(
        """INSERT INTO clauses(clause_id,doc_id,path,heading_trail,kind,text,page_start,page_end,parent_id,
                               version_key,ord) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        [(c.clause_id, c.doc_id, c.path, c.heading_trail, c.kind, c.text, c.page_start, c.page_end, c.parent_id,
          c.version_key, c.ord) for c in clauses])
    conn.executemany(
        """INSERT INTO spans(span_id,clause_id,doc_id,page,text,bboxes,char_start,char_end,is_table_row,ocr_conf)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        [(s.span_id, s.clause_id, s.doc_id, s.page, s.text, json.dumps(s.bboxes), s.char_start, s.char_end,
          int(s.is_table_row), s.ocr_conf) for s in spans])
    conn.commit()


def load_clauses(conn: sqlite3.Connection, doc_id: str) -> tuple[list[Clause], list[Span]]:
    clauses = [Clause(**dict(r)) for r in conn.execute("SELECT * FROM clauses WHERE doc_id=? ORDER BY ord", (doc_id,))]
    spans = []
    for r in conn.execute("SELECT * FROM spans WHERE doc_id=? ORDER BY rowid", (doc_id,)):
        d = dict(r)
        d["bboxes"] = json.loads(d["bboxes"])
        d["is_table_row"] = bool(d["is_table_row"])
        spans.append(Span(**d))
    return clauses, spans
