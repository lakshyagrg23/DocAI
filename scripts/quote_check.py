"""Quote exactness (eval.md): a displayed citation's stored text must equal the PDF text at the span's bounding boxes.

Digital spans: the words of the page inside each bbox, concatenated in reading order, equal the span text (whitespace
ignored; the clause number printed before a clause is part of the first span). Table-row spans: every cell value is
found in the words of the row box. OCR spans are skipped: their stored text *is* the OCR output (they carry the badge).
"""
from __future__ import annotations

import json
import sqlite3

import pymupdf

from core.normalize import normalize_text
from core.render import highlight


def _words_in(page: pymupdf.Page, bbox: list[float]) -> str:
    rect = pymupdf.Rect(bbox)
    ws = [w for w in page.get_text("words", sort=True)
          if rect.x0 - 1 <= (w[0] + w[2]) / 2 <= rect.x1 + 1 and rect.y0 - 1 <= (w[1] + w[3]) / 2 <= rect.y1 + 1]
    return " ".join(w[4] for w in ws)


def _flat(s: str) -> str:
    return normalize_text("".join(s.split()))


def span_matches(conn: sqlite3.Connection, span_id: str) -> bool | None:
    """True/False for a digital span, None when it cannot or need not be checked (OCR span, missing PDF)."""
    r = conn.execute("SELECT doc_id,page,text,bboxes,is_table_row,ocr_conf FROM spans WHERE span_id=?", (span_id,)).fetchone()
    if r is None:
        return False
    if r["ocr_conf"] is not None:
        return None
    path = highlight.pdf_path(conn, r["doc_id"])
    if path is None:
        return None
    with pymupdf.open(path) as doc:
        page = doc[r["page"] - 1]
        got = " ".join(_words_in(page, b) for b in json.loads(r["bboxes"]))
    if r["is_table_row"]:
        cells = [c.split(": ", 1)[-1] for c in r["text"].split(" | ")]
        return all(_flat(c) in _flat(got) for c in cells if c.strip())
    return _flat(r["text"]) == _flat(got)


def displayed_span_ids(ans: dict) -> list[str]:
    ids = [s for c in ans["claims"] for s in c["span_ids"]]
    ids += [side["span_id"] for d in ans.get("disagreements", []) for side in d.get("sides", [])]
    ids += [i["span_id"] for i in (ans.get("calculation") or {}).get("inputs", []) if i.get("span_id")]
    return list(dict.fromkeys(ids))


def mismatches(conn: sqlite3.Connection, ans: dict) -> tuple[int, list[str]]:
    """(number of displayed spans checked, span ids whose text differs from the PDF)."""
    checked, bad = 0, []
    for sid in displayed_span_ids(ans):
        ok = span_matches(conn, sid)
        if ok is None:
            continue
        checked += 1
        if not ok:
            bad.append(sid)
    return checked, bad
