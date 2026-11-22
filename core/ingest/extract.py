"""Fact extraction at ingest (facts-and-subjects.md §1-§3): LLM proposes, code validates, nothing unverified is stored."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from core import config, db
from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import Extraction
from core.normalize import normalize_text, parse_value
from core.subjects import canonical_subject, normalise_attribute

log = logging.getLogger("ingest")
RE_ELIGIBLE = re.compile(r"\d|%|₹|\brs\b|\binr\b|\bage\b|\baged\b|\b(?:shall|must|may|prohibited)\b|\bnot permitted\b",
                         re.IGNORECASE)


def eligible_clauses(conn: sqlite3.Connection, doc_id: str) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT clause_id,kind,text FROM clauses WHERE doc_id=? ORDER BY ord", (doc_id,)).fetchall()
    return [r for r in rows if r["kind"] != "definition" and RE_ELIGIBLE.search(r["text"] or "")]


def _spans_of(conn: sqlite3.Connection, clause_ids: list[str]) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(clause_ids))
    return conn.execute(f"SELECT span_id,clause_id,text FROM spans WHERE clause_id IN ({marks}) ORDER BY rowid",
                        clause_ids).fetchall()


def render_batch(spans: list[sqlite3.Row], title: str | None, doc_type: str | None) -> str:
    head = f"Document: {title or 'unknown'} (type: {doc_type or 'other'})\n\n"
    return head + "\n".join(f"[{s['span_id']}] {s['text']}" for s in spans)


def validate_fact(fact, spans_by_id: dict[str, str]) -> str | None:
    """Return None when the fact is acceptable, else the reason it is dropped."""
    text = spans_by_id.get(fact.span_id)
    if text is None:
        return "span not in this batch"
    if normalize_text(fact.value_raw) not in normalize_text(text):
        return "value_raw not found in span text"
    if fact.value_type not in ("enum", "text"):
        try:
            parse_value(fact.value_raw, fact.value_type)
        except ValueError as e:
            return f"unparseable: {e}"
    return None


def _log_dropped(doc_id: str, fact, reason: str) -> None:
    d = config.DATA_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "ingest.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"doc": doc_id, "dropped": fact.model_dump(), "reason": reason}, ensure_ascii=False) + "\n")


def _extract_batch(client: ModelClient, user: str, system: str) -> Extraction | None:
    try:
        return client.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                Extraction, max_tokens=1500)
    except (ModelUnavailable, ValueError) as e:
        log.warning("fact extraction call failed: %s", e)
        return None


def run(conn: sqlite3.Connection, doc_id: str, client: ModelClient) -> None:
    """Post-stage: extract, validate, canonicalise and store the facts of one document."""
    conn.execute("DELETE FROM facts WHERE clause_id IN (SELECT clause_id FROM clauses WHERE doc_id=?)", (doc_id,))
    conn.commit()
    doc = db.get_document(conn, doc_id)
    clauses = eligible_clauses(conn, doc_id)
    batches = [clauses[i:i + config.EXTRACT_BATCH] for i in range(0, len(clauses), config.EXTRACT_BATCH)]
    _, system = load_prompt("extract_facts")
    jobs = []
    for b in batches:
        spans = _spans_of(conn, [c["clause_id"] for c in b])
        jobs.append((spans, render_batch(spans, doc.title if doc else None, doc.doc_type if doc else None)))
    with ThreadPoolExecutor(max_workers=config.EXTRACT_WORKERS) as pool:
        results = list(pool.map(lambda j: _extract_batch(client, j[1], system), jobs))
    n = 0
    for (spans, _), out in zip(jobs, results, strict=True):
        if out is None:
            continue
        by_id = {s["span_id"]: s["text"] for s in spans}
        clause_of = {s["span_id"]: s["clause_id"] for s in spans}
        for fact in out.facts:
            fact.span_id = fact.span_id.strip().strip("[]").strip()
            reason = validate_fact(fact, by_id)
            if reason:
                _log_dropped(doc_id, fact, reason)
                continue
            value = parse_value(fact.value_raw, fact.value_type) if fact.value_type not in ("enum", "text") else None
            sid = canonical_subject(conn, fact.subject, client)
            conn.execute(
                "INSERT INTO facts(fact_id,clause_id,span_id,subject_id,attribute,op,value_type,value_norm,value_raw,"
                "scope,modality,condition_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (db.new_id("f"), clause_of[fact.span_id], fact.span_id, sid,
                 normalise_attribute(fact.attribute, fact.value_type), fact.op, fact.value_type,
                 value.model_dump_json() if value else None, fact.value_raw, json.dumps(fact.scope),
                 fact.modality, fact.condition_text))
            n += 1
    conn.commit()
    log.info("facts: %s -> %d stored", doc_id, n)
