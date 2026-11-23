"""Evidence pack (retrieval.md §4): the in-force spans the drafting LLM may cite, plus context for chains."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from core import config
from core.retrieval.expand import Candidate, expand
from core.retrieval.hybrid import Hit
from core.retrieval.index import approx_tokens


@dataclass
class EvidenceSpan:
    span_id: str
    clause_id: str
    doc_id: str
    page: int
    text: str
    line: str  # as shown to the LLM
    is_table_row: bool = False
    ocr_conf: float | None = None
    score: float = 0.0
    status: str = "in_force"


@dataclass
class EvidencePack:
    spans: list[EvidenceSpan] = field(default_factory=list)  # shown to the drafting LLM (in force only)
    context_spans: list[EvidenceSpan] = field(default_factory=list)  # superseded / future; chains and checks only
    tokens: int = 0
    truncated: bool = False

    def render(self) -> str:
        return "\n".join(s.line for s in self.spans)

    def span_ids(self) -> set[str]:
        return {s.span_id for s in self.spans}


def where_label(path: str) -> str:
    if path.startswith("table") and ".row" in path:
        t, r = path[len("table"):].split(".row")
        return f"table {t} row {r}"
    if path.startswith("p") and path[1:2].isdigit():
        return f"para {path}"
    return f"cl. {path}"


def format_span(span_id: str, title: str | None, ref_no: str | None, path: str, page: int, text: str,
                effective: str | None = None, note: str | None = None) -> str:
    """[D1:7.2#s1] (Personal Loan Agreement KF/PLA/2024, cl. 7.2, p.3, effective 2026-01-01) <text>"""
    doc = " ".join(x for x in (title, ref_no) if x) or "document"
    meta = [doc, where_label(path), f"p.{page}"]
    if note:
        meta.append(note)
    elif effective:
        meta.append(f"effective {effective}")
    return f"[{span_id}] ({', '.join(meta)}) {text}"


def _load_spans(conn: sqlite3.Connection, clause_id: str, score: float, status: str) -> list[EvidenceSpan]:
    out = []
    rows = conn.execute(
        """SELECT s.span_id,s.clause_id,s.doc_id,s.page,s.text,s.is_table_row,s.ocr_conf,
                  c.path,d.title,d.ref_no,d.effective_date
           FROM spans s JOIN clauses c ON c.clause_id=s.clause_id JOIN documents d ON d.doc_id=s.doc_id
           WHERE s.clause_id=? ORDER BY s.rowid""", (clause_id,)).fetchall()
    for r in rows:
        line = format_span(r["span_id"], r["title"], r["ref_no"], r["path"], r["page"], r["text"], r["effective_date"])
        out.append(EvidenceSpan(r["span_id"], r["clause_id"], r["doc_id"], r["page"], r["text"], line,
                                bool(r["is_table_row"]), r["ocr_conf"], score, status))
    return out


def build_pack(conn: sqlite3.Connection, hits: list[Hit], as_of: str,
               max_spans: int = config.EVIDENCE_MAX_SPANS, max_tokens: int = config.EVIDENCE_MAX_TOKENS
               ) -> EvidencePack:
    """Whole clauses, best-scoring first, until the span/token caps; out-of-force versions go to context_spans."""
    clause_score: dict[str, float] = {}
    for h in hits:
        clause_score[h.clause_id] = max(h.score, clause_score.get(h.clause_id, float("-inf")))
    cands: dict[str, Candidate] = expand(conn, list(clause_score), as_of)
    vkey_score: dict[str, float] = {}
    for cid, sc in clause_score.items():
        if cid in cands:
            vkey_score[cands[cid].version_key] = max(sc, vkey_score.get(cands[cid].version_key, float("-inf")))
    ord_of = {r["clause_id"]: r["ord"] for r in conn.execute(
        f"SELECT clause_id,ord FROM clauses WHERE clause_id IN ({','.join('?' * len(cands))})", list(cands))} if cands else {}

    pack = EvidencePack()
    in_force = sorted((c for c in cands.values() if c.status == "in_force"),
                      key=lambda c: (-vkey_score.get(c.version_key, 0.0), ord_of.get(c.clause_id, 0), c.clause_id))
    for c in in_force:
        spans = _load_spans(conn, c.clause_id, vkey_score.get(c.version_key, 0.0), "in_force")
        need = sum(approx_tokens(s.line) for s in spans)
        if not spans:
            continue
        if len(pack.spans) + len(spans) > max_spans or pack.tokens + need > max_tokens:
            pack.truncated = True
            continue
        pack.spans.extend(spans)
        pack.tokens += need
    for c in cands.values():
        if c.status != "in_force":
            pack.context_spans.extend(_load_spans(conn, c.clause_id, vkey_score.get(c.version_key, 0.0), c.status))
    return pack


def restrict(pack: EvidencePack, doc_scope: list[str] | None) -> EvidencePack:
    """Keep only spans from the chat's allowed documents (None = all documents; an empty list keeps nothing)."""
    if doc_scope is None:
        return pack
    keep = set(doc_scope)
    pack.spans = [s for s in pack.spans if s.doc_id in keep]
    pack.context_spans = [s for s in pack.context_spans if s.doc_id in keep]
    pack.tokens = sum(approx_tokens(s.line) for s in pack.spans)
    return pack


def pack_to_json(pack: EvidencePack) -> str:
    return json.dumps({"spans": [s.span_id for s in pack.spans], "context": [s.span_id for s in pack.context_spans],
                       "tokens": pack.tokens, "truncated": pack.truncated})
