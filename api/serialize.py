"""Turns stored rows and AnswerJSON into what the React UI renders (design/ui-react.md §3, §5). Presentation only."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from core import versions
from core.models import Message

SMALL = {"of", "and", "to", "the", "in", "for", "on", "a", "an"}
RE_AMEND = re.compile(r"amendment\s+no\.?\s*\d+", re.IGNORECASE)


def title_case(title: str) -> str:
    """The corpus has ALL-CAPS titles; show them in readable title case (keep reference codes as written)."""
    letters = [c for c in title if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.6:
        # already mixed case: only fix capitalised small words in the middle ("Schedule Of Charges")
        return " ".join(w.lower() if i and w.lower() in SMALL else w for i, w in enumerate(title.split()))
    words = []
    for i, w in enumerate(title.split()):
        words.append(w if "/" in w or any(c.isdigit() for c in w) else (w.lower() if w.lower() in SMALL and i else w.capitalize()))
    return " ".join(words)


def display_name(title: str | None, doc_type: str | None, ref_no: str | None) -> str:
    title = title or "Document"
    if doc_type == "amendment":
        m = RE_AMEND.search(title)
        return title_case(m.group(0)) if m else title_case(title)
    if doc_type == "circular" and ref_no:
        return f"Circular {ref_no}"
    return title_case(title)


def doc_sub(doc_type: str | None, ref_no: str | None) -> str:
    return " · ".join(x for x in ((doc_type or "").capitalize(), ref_no or "") if x)


def clause_label(path: str, span_text: str | None = None, is_row: bool = False) -> str:
    """Human label: "Clause 8.1", "Table row: Late payment fee", "Paragraph 1"."""
    if is_row and span_text:
        first = span_text.split(" | ")[0]
        name = first.split(": ", 1)[-1].strip()
        return f"Table row: {name}" if name else "Table row"
    m = re.fullmatch(r"p(\d+)\.(\d+)", path)
    if m:
        return f"Paragraph {m[2]} (page {m[1]})"
    if path.startswith("table") and ".row" in path:
        t, r = path[len("table"):].split(".row")
        return f"Table {t}, row {r}"
    return f"Clause {path}"


def row_cells(text: str) -> dict[str, str] | None:
    parts = [p.strip() for p in text.split(" | ")]
    if len(parts) < 2 or not all(": " in p for p in parts):
        return None
    return dict(p.split(": ", 1) for p in parts)


def source_info(conn: sqlite3.Connection, span_id: str, as_of: str) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT s.span_id,s.clause_id,s.doc_id,s.page,s.text,s.bboxes,s.ocr_conf,s.is_table_row,c.path,"
        "d.title,d.doc_type,d.ref_no,d.effective_date,d.pages FROM spans s JOIN clauses c ON c.clause_id=s.clause_id "
        "JOIN documents d ON d.doc_id=s.doc_id WHERE s.span_id=?", (span_id,)).fetchone()
    if r is None:
        return None
    size = conn.execute("SELECT width,height FROM pages WHERE doc_id=? AND page_no=?", (r["doc_id"], r["page"])).fetchone()
    return {
        "span_id": r["span_id"], "clause_id": r["clause_id"], "doc_id": r["doc_id"],
        "doc_name": display_name(r["title"], r["doc_type"], r["ref_no"]), "doc_sub": doc_sub(r["doc_type"], r["ref_no"]),
        "clause_label": clause_label(r["path"], r["text"], bool(r["is_table_row"])), "page": r["page"], "pages": r["pages"],
        "page_width": size["width"] if size else None, "page_height": size["height"] if size else None,
        "bboxes": json.loads(r["bboxes"] or "[]"), "text": r["text"], "row": row_cells(r["text"]) if r["is_table_row"] else None,
        "ocr": r["ocr_conf"] is not None, "ocr_conf": r["ocr_conf"],
        "status": versions.status(conn, r["clause_id"], as_of), "effective": r["effective_date"],
    }


def _walk_span_ids(ans: dict) -> list[str]:
    """Span ids in the order a reader meets them: statements, then disagreement sides, timeline quotes, calc inputs."""
    ids: list[str] = []
    for c in ans.get("claims", []):
        ids += c["span_ids"]
    for d in ans.get("disagreements", []):
        ids += [s["span_id"] for s in d.get("sides", [])]
    for ch in ans.get("chains", []):
        ids += [s["span_id"] for s in ch.get("steps", []) if s.get("span_id")]
    for i in (ans.get("calculation") or {}).get("inputs", []):
        if i.get("span_id"):
            ids.append(i["span_id"])
    ids += [s for c in ans.get("blocked_claims", []) for s in c["span_ids"]]
    return list(dict.fromkeys(ids))


def enrich_answer(conn: sqlite3.Connection, ans: dict) -> dict:
    """Add `sources` (span_id -> info with a stable citation number `n`) and `citations` (ids in citation order)."""
    sources: dict[str, Any] = {}
    for n, sid in enumerate(_walk_span_ids(ans), 1):
        info = source_info(conn, sid, ans["as_of_date"])
        if info:
            info["n"] = n
            sources[sid] = info
    cards = []
    for d in ans.get("disagreements", []):  # every side gets a readable name and the page geometry for the UI
        sides = []
        for side in d["sides"]:
            info = sources.get(side["span_id"], {})
            sides.append({**side, **{k: info.get(k) for k in ("doc_name", "doc_sub", "clause_label", "page_width", "page_height",
                                                               "bboxes", "row", "pages")}})
        cards.append({**d, "sides": sides})
    return {**ans, "disagreements": cards, "sources": sources, "citations": list(sources)}


def message_out(conn: sqlite3.Connection, m: Message) -> dict[str, Any]:
    answer = enrich_answer(conn, json.loads(m.answer_json)) if m.answer_json else None
    return {"msg_id": m.msg_id, "role": m.role, "content": m.content, "created_at": m.created_at, "answer": answer}


def enrich_cards(conn: sqlite3.Connection, cards: list[dict], as_of: str) -> list[dict]:
    """Disagreement cards (disagree.cards_from_ids) with a readable source on every side."""
    out = []
    for card in cards:
        sides = []
        for s in card["sides"]:
            info = source_info(conn, s["span_id"], as_of) or {}
            sides.append({**s, **{k: info.get(k) for k in ("doc_name", "doc_sub", "clause_label", "page_width",
                                                               "page_height", "bboxes", "row", "pages")}})
        out.append({**card, "sides": sides})
    return out


def doc_name_for(conn: sqlite3.Connection, doc_id: str | None) -> str | None:
    r = conn.execute("SELECT title,doc_type,ref_no FROM documents WHERE doc_id=?", (doc_id,)).fetchone() if doc_id else None
    return display_name(r["title"], r["doc_type"], r["ref_no"]) if r else None
