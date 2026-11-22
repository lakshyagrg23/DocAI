"""Version timelines and as-of resolution (amendments.md §3-§5). Rebuilt from edges; queries only read clause_versions."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

PATH_ACTIONS = ("substitute", "insert", "delete")


def _doc_of(clause_id: str | None) -> str | None:
    return clause_id.split(":")[0] if clause_id else None


def _close_open(chain: list[dict], eff: str | None) -> None:
    if chain and chain[-1]["valid_to"] is None:
        chain[-1]["valid_to"] = eff


def _build_chain(conn: sqlite3.Connection, vk: str, edges: list[sqlite3.Row]) -> list[dict]:
    base = conn.execute("SELECT c.clause_id,d.effective_date FROM clauses c JOIN documents d ON d.doc_id=c.doc_id "
                        "WHERE c.clause_id=?", (vk,)).fetchone()
    chain: list[dict] = []
    if base:
        chain.append({"clause_id": vk, "valid_from": base["effective_date"], "valid_to": None, "edge_id": None,
                      "action": "original"})
    for e in edges:
        _close_open(chain, e["effective_date"])
        if e["action"] == "delete":
            chain.append({"clause_id": None, "valid_from": e["effective_date"], "valid_to": None,
                          "edge_id": e["edge_id"], "action": "deleted"})
        else:
            chain.append({"clause_id": e["source_clause_id"], "valid_from": e["effective_date"], "valid_to": None,
                          "edge_id": e["edge_id"], "action": "substituted" if chain else "inserted"})
    return chain


def _supersede(chain: list[dict], target_doc: str, eff: str | None, edge_id: str) -> None:
    """Close the chain at `eff` if its open (latest) version belongs to `target_doc`."""
    if chain and chain[-1]["clause_id"] and _doc_of(chain[-1]["clause_id"]) == target_doc and chain[-1]["valid_to"] is None:
        chain[-1]["valid_to"] = eff
        chain.append({"clause_id": None, "valid_from": eff, "valid_to": None, "edge_id": edge_id, "action": "deleted"})


def rebuild_all(conn: sqlite3.Connection) -> None:
    """Recompute every timeline from the resolved edges (the corpus is small; this keeps ingest order irrelevant)."""
    conn.execute("DELETE FROM clause_versions")
    conn.execute("UPDATE clauses SET version_key=clause_id")
    rows = conn.execute(
        "SELECT e.*, d.issue_date AS src_issue FROM amendment_edges e "
        "JOIN clauses c ON c.clause_id=e.source_clause_id JOIN documents d ON d.doc_id=c.doc_id "
        "WHERE e.resolved=1 ORDER BY e.effective_date, d.issue_date, e.edge_id").fetchall()
    by_vk: dict[str, list[sqlite3.Row]] = {}
    for e in rows:
        if e["action"] in PATH_ACTIONS:
            by_vk.setdefault(f"{e['target_doc_id']}:{e['target_path']}", []).append(e)
    sup_docs = [e for e in rows if e["action"] == "supersede_doc"]
    sup_amds = [e for e in rows if e["action"] == "supersede_amendment"]
    for e in sup_docs:  # every clause of a superseded document gets a timeline, so its status can be read like any other
        for c in conn.execute("SELECT clause_id FROM clauses WHERE doc_id=?", (e["target_doc_id"],)):
            by_vk.setdefault(c["clause_id"], [])
    for vk, edges in by_vk.items():
        chain = _build_chain(conn, vk, edges)
        for e in sorted(sup_amds + sup_docs, key=lambda x: (x["effective_date"] or "", x["edge_id"])):
            _supersede(chain, e["target_doc_id"], e["effective_date"], e["edge_id"])
        if len(chain) < 2 and not any(e["target_doc_id"] == _doc_of(vk) for e in sup_docs):
            continue
        for n, v in enumerate(chain):
            conn.execute("INSERT INTO clause_versions(version_key,version_no,clause_id,valid_from,valid_to,edge_id) "
                         "VALUES(?,?,?,?,?,?)", (vk, n, v["clause_id"], v["valid_from"], v["valid_to"], v["edge_id"]))
            if v["clause_id"]:
                conn.execute("UPDATE clauses SET version_key=? WHERE clause_id=?", (vk, v["clause_id"]))
    conn.commit()


def versions_for(conn: sqlite3.Connection, version_key: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM clause_versions WHERE version_key=? ORDER BY version_no", (version_key,)).fetchall()


def _within(v: sqlite3.Row, as_of: str) -> bool:
    return (v["valid_from"] is None or v["valid_from"] <= as_of) and (v["valid_to"] is None or as_of < v["valid_to"])


def status(conn: sqlite3.Connection, clause_id: str, as_of: str) -> str:
    """in_force | superseded | future | deleted (amendments.md §4)."""
    row = conn.execute("SELECT c.version_key,d.effective_date FROM clauses c JOIN documents d ON d.doc_id=c.doc_id "
                       "WHERE c.clause_id=?", (clause_id,)).fetchone()
    if row is None:
        return "future"
    rows = versions_for(conn, row["version_key"] or clause_id)
    if not rows:
        return "in_force" if (row["effective_date"] or "") <= as_of else "future"
    current = next((v for v in rows if _within(v, as_of)), None)
    mine = next((v for v in rows if v["clause_id"] == clause_id), None)
    if current is None:
        return "future"
    if current["clause_id"] == clause_id:
        return "in_force"
    if mine is not None and mine["valid_from"] is not None and mine["valid_from"] > as_of:
        return "future"
    return "superseded"


def key_status(conn: sqlite3.Connection, version_key: str, as_of: str) -> str:
    """active | deleted | not_yet: used to say "this rule was deleted on ..."."""
    rows = versions_for(conn, version_key)
    current = next((v for v in rows if _within(v, as_of)), None)
    if current is None:
        return "not_yet"
    return "active" if current["clause_id"] else "deleted"


def chains(conn: sqlite3.Connection, clause_ids: list[str], as_of: str) -> list[dict[str, Any]]:
    """One chain per version key (with more than one version) behind the given clauses (amendments.md §5)."""
    keys: list[str] = []
    for cid in clause_ids:
        r = conn.execute("SELECT version_key FROM clauses WHERE clause_id=?", (cid,)).fetchone()
        vk = (r["version_key"] if r else None) or cid
        if vk not in keys:
            keys.append(vk)
    out = []
    for vk in keys:
        rows = versions_for(conn, vk)
        if len([v for v in rows if v["clause_id"]]) < 2:
            continue
        steps, in_force = [], -1
        for n, v in enumerate(rows):
            step = _step(conn, v)
            steps.append(step)
            if _within(v, as_of):
                in_force = n
        out.append({"version_key": vk, "steps": steps, "in_force_step": in_force})
    return out


def _step(conn: sqlite3.Connection, v: sqlite3.Row) -> dict[str, Any]:
    cid = v["clause_id"]
    edge = conn.execute("SELECT action,new_text_span_ids,evidence_span_ids FROM amendment_edges WHERE edge_id=?",
                        (v["edge_id"],)).fetchone() if v["edge_id"] else None
    action = {"substitute": "substituted", "insert": "inserted", "delete": "deleted"}.get(edge["action"], "deleted") if edge \
        else "original"
    span_id = None
    if edge and cid:
        new_ids = json.loads(edge["new_text_span_ids"] or "[]")
        span_id = new_ids[0] if new_ids else None
    if span_id is None and cid:
        r = conn.execute("SELECT span_id FROM spans WHERE clause_id=? ORDER BY rowid LIMIT 1", (cid,)).fetchone()
        span_id = r["span_id"] if r else None
    if span_id is None and edge:
        ev = json.loads(edge["evidence_span_ids"] or "[]")
        span_id = ev[0] if ev else None
    doc = conn.execute("SELECT d.doc_id,d.title,d.ref_no FROM documents d WHERE d.doc_id=?",
                       (_doc_of(cid) or _doc_of(span_id),)).fetchone() if (cid or span_id) else None
    text = None
    if span_id:
        r = conn.execute("SELECT text,page FROM spans WHERE span_id=?", (span_id,)).fetchone()
        text = r["text"] if r else None
    return {"clause_id": cid, "doc_id": doc["doc_id"] if doc else None, "doc_title": doc["title"] if doc else None,
            "ref_no": doc["ref_no"] if doc else None, "valid_from": v["valid_from"], "valid_to": v["valid_to"],
            "action": action, "span_id": span_id, "text": text}


def clause_in_force(conn: sqlite3.Connection, version_key: str, as_of: str) -> str | None:
    """The clause id whose text applies to `version_key` on `as_of` (None when not yet in force or deleted)."""
    current = next((v for v in versions_for(conn, version_key) if _within(v, as_of)), None)
    return current["clause_id"] if current else None
