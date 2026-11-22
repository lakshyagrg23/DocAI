"""Amendment directives at ingest (amendments.md §1-§2): LLM proposes, code validates and resolves targets."""
from __future__ import annotations

import json
import logging
import re
import sqlite3

from rapidfuzz import fuzz

from core import config, db
from core.ingest.extract import _spans_of
from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import AmendExtraction, AmendmentDirective
from core.normalize import normalize_text, parse_value

log = logging.getLogger("ingest")
AMEND_RX = re.compile(
    r"\b(amend(?:ed|ment|ments)?|substitut(?:e|ed|ion)|supersession|supersed(?:e|ed|es)|replac(?:e|ed)|insert(?:ed)?|"
    r"delet(?:e|ed)|omit(?:ted)?|stands? (?:modified|amended)|in partial modification|with effect from|w\.e\.f\.)",
    re.IGNORECASE)
RE_SUPERSESSION_WORDS = re.compile(r"supersed|superses|supersess|replac|repeal|withdraw|cancel|rescind", re.IGNORECASE)
PATH_ACTIONS = {"substitute", "insert", "delete"}
RE_CLAUSE_REF = re.compile(r"\b(?:clause|para(?:graph)?|section|article)\s+(\d+(?:\.\d+)*)", re.IGNORECASE)


def recover_target_path(d: AmendmentDirective, spans: dict[str, str]) -> str | None:
    """The model sometimes leaves target_path empty although the evidence names the clause: take it when unambiguous."""
    refs = set(RE_CLAUSE_REF.findall(" ".join(spans[s] for s in d.evidence_span_ids if s in spans)))
    return refs.pop() if len(refs) == 1 else None


def candidate_clauses(conn: sqlite3.Connection, doc_id: str) -> list[sqlite3.Row]:
    doc = db.get_document(conn, doc_id)
    rows = conn.execute("SELECT clause_id,text FROM clauses WHERE doc_id=? ORDER BY ord", (doc_id,)).fetchall()
    if doc and doc.doc_type == "amendment":
        return list(rows)
    return [r for r in rows if AMEND_RX.search(r["text"] or "")]


def validate_directive(d: AmendmentDirective, spans: dict[str, str], clause_of: dict[str, str]) -> str | None:
    """Return None when acceptable, else the drop reason."""
    ev = [s for s in d.evidence_span_ids if s in spans]
    if not ev:
        return "no evidence span in this document"
    ev_text = " ".join(spans[s] for s in ev)
    if d.action in PATH_ACTIONS:
        if not d.target_path or normalize_text(d.target_path) not in normalize_text(ev_text):
            return "target_path not stated in the evidence"
    elif not RE_SUPERSESSION_WORDS.search(ev_text):
        return "no supersession wording in the evidence"
    if d.action == "supersede_doc" and d.target_path:
        return "supersede_doc must not name a clause"
    return None


def _new_text(d: AmendmentDirective, spans: dict[str, str], clause_of: dict[str, str]) -> list[str]:
    ids = [s for s in d.new_text_span_ids if s in spans]
    if ids or d.action not in ("substitute", "insert"):
        return ids
    # the model gave none: the replacement wording is the rest of the evidence clause (or the clause itself)
    clause = clause_of[d.evidence_span_ids[0]] if d.evidence_span_ids and d.evidence_span_ids[0] in clause_of else None
    rest = [s for s, c in clause_of.items() if c == clause and s not in d.evidence_span_ids]
    return rest or [s for s in d.evidence_span_ids if s in spans]


def _parse_date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parse_value(raw, "date").date
    except ValueError:
        return None


def run(conn: sqlite3.Connection, doc_id: str, client: ModelClient) -> None:
    """Post-stage: extract this document's amendment directives, resolve all edges, rebuild all version timelines."""
    from core import (
        versions,  # local import: versions imports nothing from ingest, keeps the module graph acyclic
    )

    conn.execute("DELETE FROM amendment_edges WHERE source_clause_id IN (SELECT clause_id FROM clauses WHERE doc_id=?)",
                 (doc_id,))
    conn.commit()
    doc = db.get_document(conn, doc_id)
    cands = candidate_clauses(conn, doc_id)
    if cands:
        spans = _spans_of(conn, [c["clause_id"] for c in cands])
        text_of = {s["span_id"]: s["text"] for s in spans}
        clause_of = {s["span_id"]: s["clause_id"] for s in spans}
        _, system = load_prompt("extract_amendments")
        user = f"Document: {doc.title if doc else ''} (type: {doc.doc_type if doc else ''})\n\n" + \
               "\n".join(f"[{s['span_id']}] {s['text']}" for s in spans)
        try:
            out = client.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                   AmendExtraction, max_tokens=900)
        except (ModelUnavailable, ValueError) as e:
            log.warning("amendment extraction failed for %s: %s", doc_id, e)
            out = AmendExtraction()
        for n, d in enumerate(out.amendments, 1):
            d.evidence_span_ids = [s.strip().strip("[]").strip() for s in d.evidence_span_ids]
            d.new_text_span_ids = [s.strip().strip("[]").strip() for s in d.new_text_span_ids]
            if d.action in PATH_ACTIONS and not d.target_path:
                d.target_path = recover_target_path(d, text_of)
            reason = validate_directive(d, text_of, clause_of)
            if reason:
                log.info("amendment dropped (%s): %s", reason, d.model_dump())
                continue
            source = clause_of[next(s for s in d.evidence_span_ids if s in text_of)]
            eff = _parse_date(d.effective_date) or (doc.effective_date if doc else None)
            conn.execute(
                "INSERT INTO amendment_edges(edge_id,source_clause_id,target_doc_id,target_path,action,new_text_span_ids,"
                "effective_date,evidence_span_ids,confidence,resolved,raw_target_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (f"E:{source}:{n}", source, None, d.target_path, d.action, json.dumps(_new_text(d, text_of, clause_of)),
                 eff, json.dumps(d.evidence_span_ids), 1.0, 0, d.target_ref))
        conn.commit()
    resolve_all(conn)
    versions.rebuild_all(conn)


def resolve_all(conn: sqlite3.Connection) -> None:
    """(Re-)resolve every edge's target document. Idempotent, so late uploads and re-ingests heal old edges."""
    docs = conn.execute("SELECT doc_id,title,ref_no,ref_aliases,issue_date FROM documents").fetchall()
    for e in conn.execute("SELECT edge_id,source_clause_id,target_path,action,raw_target_ref FROM amendment_edges").fetchall():
        source_doc = e["source_clause_id"].split(":")[0]
        source_issue = (conn.execute("SELECT issue_date FROM documents WHERE doc_id=?", (source_doc,)).fetchone() or {})
        best: tuple[tuple, str] | None = None
        for d in docs:
            if d["doc_id"] == source_doc:
                continue
            names = [d["title"] or "", d["ref_no"] or "", *json.loads(d["ref_aliases"] or "[]")]
            scored = [(fuzz.partial_ratio((e["raw_target_ref"] or "").lower(), n.lower()), len(n)) for n in names if n]
            score, matched_len = max(scored, default=(0, 0))  # ties: the longer (more specific) name wins
            if score < config.TARGET_MATCH_MIN:
                continue
            has_clause = 1
            if e["action"] in ("substitute", "delete"):
                has_clause = int(conn.execute("SELECT 1 FROM clauses WHERE clause_id=?",
                                              (f"{d['doc_id']}:{e['target_path']}",)).fetchone() is not None)
                if not has_clause:
                    continue  # a substitution needs an existing clause to replace
            issued_before = int(not source_issue or not d["issue_date"] or d["issue_date"] <= (source_issue["issue_date"] or "9999"))
            key = (has_clause * 2 + issued_before, score, matched_len, d["issue_date"] or "")
            if best is None or key > best[0]:
                best = (key, d["doc_id"])
        conn.execute("UPDATE amendment_edges SET target_doc_id=?, resolved=? WHERE edge_id=?",
                     (best[1] if best else None, int(best is not None), e["edge_id"]))
    conn.commit()
