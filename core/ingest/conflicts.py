"""Ingest-time contradiction scan (contradictions.md §1-§4). Code decides numeric pairs; the LLM only judges text pairs."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from itertools import combinations

from core.conflict_rules import ConflictVerdict, FactView, candidate, compare, merge_ranges, overlap
from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import FactValue, JudgeVerdict
from core.retrieval.evidence import where_label

log = logging.getLogger("ingest")


def conflict_id(fact_a: str, fact_b: str) -> str:
    return "C_" + hashlib.sha1(f"{fact_a}|{fact_b}".encode()).hexdigest()[:8]


def load_views(conn: sqlite3.Connection, subject_id: str | None = None,
               clause_ids: list[str] | None = None) -> list[FactView]:
    """Facts with their clause's version key, validity interval and a human label."""
    sql = ("SELECT f.*, c.version_key, c.path, d.title, d.effective_date FROM facts f "
           "JOIN clauses c ON c.clause_id=f.clause_id JOIN documents d ON d.doc_id=c.doc_id")
    where, args = [], []
    if subject_id:
        where.append("f.subject_id=?")
        args.append(subject_id)
    if clause_ids:
        where.append(f"f.clause_id IN ({','.join('?' * len(clause_ids))})")
        args += clause_ids
    rows = conn.execute(sql + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY f.fact_id", args).fetchall()
    out = []
    for r in rows:
        ver = conn.execute("SELECT valid_from,valid_to FROM clause_versions WHERE clause_id=? AND version_key=?",
                           (r["clause_id"], r["version_key"])).fetchone()
        start, end = (ver["valid_from"], ver["valid_to"]) if ver else (r["effective_date"], None)
        value = FactValue.model_validate_json(r["value_norm"]) if r["value_norm"] else FactValue(text=r["value_raw"])
        out.append(FactView(r["fact_id"], r["clause_id"], r["span_id"], r["subject_id"], r["attribute"], r["op"],
                            r["value_type"], value, json.loads(r["scope"] or "{}"), r["version_key"] or r["clause_id"],
                            start, end, f"{r['title']}, {where_label(r['path'])}", r["value_raw"]))
    return out


def judge(a: FactView, b: FactView, client: ModelClient) -> ConflictVerdict | None:
    _, system = load_prompt("judge_conflict")
    user = f"Subject: {a.subject_id}\nA ({a.label}): {a.raw}\nB ({b.label}): {b.raw}"
    try:
        v = client.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}], JudgeVerdict,
                             max_tokens=200)
    except (ModelUnavailable, ValueError):
        return None
    if not v.conflict:
        return None
    o = overlap(a, b)
    return ConflictVerdict(v.type, "medium", v.explanation or f"{a.raw} ({a.label}) vs {b.raw} ({b.label})",
                           {"a": [a.raw], "b": [b.raw]}, o[0] if o else None, o[1] if o else None)


def find_conflicts(views: list[FactView], client: ModelClient | None = None) -> list[tuple[FactView, FactView, ConflictVerdict]]:
    out = []
    by_subject: dict[str, list[FactView]] = {}
    for f in merge_ranges(views):
        by_subject.setdefault(f.subject_id, []).append(f)
    for facts in by_subject.values():
        for a, b in combinations(sorted(facts, key=lambda f: f.fact_id), 2):
            if not candidate(a, b):
                continue
            verdict = compare(a, b)
            if verdict is None and client is not None and a.attribute == b.attribute \
                    and a.value_type in ("text", "enum") and b.value_type in ("text", "enum"):
                verdict = judge(a, b, client)
            if verdict is not None:
                out.append((a, b, verdict))
    return out


def store(conn: sqlite3.Connection, found: list[tuple[FactView, FactView, ConflictVerdict]], detected_by: str) -> int:
    n = 0
    for a, b, v in found:
        cid = conflict_id(a.fact_id, b.fact_id)
        cur = conn.execute(
            "INSERT OR IGNORE INTO conflicts(conflict_id,subject_id,fact_a,fact_b,type,overlap_from,overlap_to,detected_by,"
            "explanation,severity,differing) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (cid, a.subject_id, a.fact_id, b.fact_id, v.type, v.overlap_from, v.overlap_to, detected_by, v.explanation,
             v.severity, json.dumps(v.differing)))
        n += cur.rowcount
    conn.commit()
    return n


def run(conn: sqlite3.Connection, doc_id: str, client: ModelClient) -> None:
    """Post-stage. Re-scans every subject: a new document can change version intervals of old facts, and the corpus is small
    (the spec's per-subject incremental scan is an optimisation we do not need yet)."""
    conn.execute("DELETE FROM conflicts WHERE detected_by='ingest'")
    conn.commit()
    found = find_conflicts(load_views(conn), client)
    log.info("conflicts after %s: %d", doc_id, store(conn, found, "ingest"))


def stored(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM conflicts ORDER BY conflict_id").fetchall()

