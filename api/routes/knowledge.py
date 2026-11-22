"""Health, examples, single sources, conflicts and amendments."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from api import deps, serialize
from api.examples import EXAMPLES
from core import versions
from core.answer import disagree
from core.llm.client import ModelUnavailable

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    try:
        h = deps.get_model().health()
    except ModelUnavailable:
        return {"state": "offline", "label": "Offline"}
    ready = h.get("llm") == "ready"
    return {"state": "ready" if ready else "warming", "label": "Ready" if ready else "Warming up"}


@router.get("/examples")
def examples() -> list[dict]:
    return EXAMPLES


@router.get("/spans/{span_id:path}")
def span(span_id: str, as_of: str | None = None, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> dict:
    info = serialize.source_info(conn, span_id, as_of or deps.today())
    if info is None:
        raise HTTPException(404, "source not found")
    return info


@router.get("/conflicts")
def conflicts(as_of: str | None = None, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> dict:
    as_of = as_of or deps.today()
    cards = disagree.cards_from_ids(conn, disagree.active_conflict_ids(conn, as_of), as_of)
    return {"as_of": as_of, "cards": serialize.enrich_cards(conn, cards, as_of)}


@router.get("/amendments")
def amendments(as_of: str | None = None, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> dict:
    as_of = as_of or deps.today()
    keys = [r[0] for r in conn.execute("SELECT version_key FROM clause_versions GROUP BY version_key HAVING COUNT(*) > 1")]
    timelines = []
    for vk in keys:
        for chain in versions.chains(conn, [vk], as_of):
            for step in chain["steps"]:
                step["doc_name"] = serialize.doc_name_for(conn, step.get("doc_id"))
                step["source"] = serialize.source_info(conn, step["span_id"], as_of) if step.get("span_id") else None
            current = versions.clause_in_force(conn, vk, as_of)
            row = conn.execute("SELECT c.text,d.title,d.doc_type,d.ref_no FROM clauses c JOIN documents d ON d.doc_id=c.doc_id "
                               "WHERE c.clause_id=?", (current,)).fetchone() if current else None
            chain["label"] = serialize.clause_label(vk.split(":", 1)[1])
            chain["current"] = ({"clause_id": current, "text": row["text"],
                                 "doc_name": serialize.display_name(row["title"], row["doc_type"], row["ref_no"])}
                                if row else None)
            timelines.append(chain)
    unresolved = [{"doc_id": r["doc_id"], "action": r["action"], "target": r["raw_target_ref"]} for r in conn.execute(
        "SELECT e.raw_target_ref, e.action, c.doc_id FROM amendment_edges e JOIN clauses c ON c.clause_id=e.source_clause_id "
        "WHERE e.resolved=0")]
    return {"as_of": as_of, "timelines": timelines, "unresolved": unresolved}
