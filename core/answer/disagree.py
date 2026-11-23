"""Query-time contradiction handling (contradictions.md §5): lookup, re-check, disagreement cards, partner expansion."""
from __future__ import annotations

import json
import sqlite3

from core import versions
from core.ingest.conflicts import find_conflicts, load_views, store
from core.models import VerifiedClaim
from core.normalize import RE_NIL_CLAIM, number_tokens
from core.retrieval.evidence import EvidencePack, _load_spans
from core.retrieval.index import approx_tokens


def _in_effect(row: sqlite3.Row, as_of: str) -> bool:
    return (row["overlap_from"] is None or row["overlap_from"] <= as_of) and \
           (row["overlap_to"] is None or as_of < row["overlap_to"])


def _fact(conn: sqlite3.Connection, fact_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT f.*, c.doc_id FROM facts f JOIN clauses c ON c.clause_id=f.clause_id WHERE f.fact_id=?",
                        (fact_id,)).fetchone()


def _doc_of(conn: sqlite3.Connection, clause_id: str) -> str | None:
    r = conn.execute("SELECT doc_id FROM clauses WHERE clause_id=?", (clause_id,)).fetchone()
    return r["doc_id"] if r else None


def conflicts_in_effect(conn: sqlite3.Connection, clause_ids: list[str], as_of: str,
                        doc_scope: list[str] | None = None) -> list[tuple[sqlite3.Row, str]]:
    """Stored conflicts touching these clauses that apply at `as_of` and whose other side is in force.
    With a document scope, only conflicts between two selected documents count.
    Returns (conflict, which side ('a'|'b') belongs to the given clause)."""
    if not clause_ids:
        return []
    marks = ",".join("?" * len(clause_ids))
    rows = conn.execute(
        f"SELECT cf.*, fa.clause_id AS ca, fb.clause_id AS cb FROM conflicts cf JOIN facts fa ON fa.fact_id=cf.fact_a "
        f"JOIN facts fb ON fb.fact_id=cf.fact_b WHERE fa.clause_id IN ({marks}) OR fb.clause_id IN ({marks})",
        clause_ids * 2).fetchall()
    out = []
    for r in rows:
        if not _in_effect(r, as_of):
            continue
        if versions.status(conn, r["ca"], as_of) != "in_force" or versions.status(conn, r["cb"], as_of) != "in_force":
            continue
        if doc_scope is not None and not {_doc_of(conn, r["ca"]), _doc_of(conn, r["cb"])} <= set(doc_scope):
            continue
        if r["ca"] in clause_ids:
            out.append((r, "a"))
        if r["cb"] in clause_ids:
            out.append((r, "b"))
    return out


def asserts_disputed(claim_text: str, differing_side: list) -> bool:
    """A claim is only contradicted when it states a value that is actually in dispute (C3 differs on the upper age
    bound, so "the minimum age is 21" is not contradicted)."""
    disputed = [d for d in differing_side if isinstance(d, (int, float)) and not isinstance(d, bool)]
    if disputed:
        have = {float(v) for _, v in number_tokens(claim_text) if not isinstance(v, str)}
        if any(float(d) in have for d in disputed):
            return True
    if any(d == "nil" for d in differing_side) and RE_NIL_CLAIM.search(claim_text):
        return True
    # bool and text conflicts: the claim restates the fact
    return any(isinstance(d, bool) for d in differing_side) or any(isinstance(d, str) and d != "nil" for d in differing_side)


def mark_contradicted(conn: sqlite3.Connection, claims: list[VerifiedClaim], as_of: str,
                      doc_scope: list[str] | None = None) -> None:
    """Lookup (§5.1): supported claims that assert a disputed value become `contradicted`."""
    for c in claims:
        if c.verdict != "supported":
            continue
        clause_ids = list(dict.fromkeys(s.split("#")[0] for s in c.span_ids))
        span_facts = {r["fact_id"] for r in conn.execute(
            f"SELECT fact_id FROM facts WHERE span_id IN ({','.join('?' * len(c.span_ids))})", c.span_ids)} if c.span_ids else set()
        hits = []
        for row, side in conflicts_in_effect(conn, clause_ids, as_of, doc_scope):
            fact_id = row["fact_a"] if side == "a" else row["fact_b"]
            if fact_id in span_facts and asserts_disputed(c.text, json.loads(row["differing"] or "{}").get(side, [])):
                hits.append(row["conflict_id"])
        if hits:
            c.verdict = "contradicted"
            c.checks.conflict_ids = list(dict.fromkeys(hits))
            c.reason = "the documents disagree on this"


def build_disagreements(conn: sqlite3.Connection, claims: list[VerifiedClaim], as_of: str) -> list[dict]:
    """One card per subject listing every side of the conflicts that contradicted a displayed claim (§5.3)."""
    ids = list(dict.fromkeys(i for c in claims if c.verdict == "contradicted" for i in c.checks.conflict_ids))
    return cards_from_ids(conn, ids, as_of)


def active_conflict_ids(conn: sqlite3.Connection, as_of: str, doc_scope: list[str] | None = None) -> list[str]:
    """Every stored conflict that applies at `as_of` (both sides in force): the Conflicts page.
    With a document scope (a workspace's documents) only conflicts between two of those documents count."""
    out = []
    for r in conn.execute("SELECT cf.*, fa.clause_id AS ca, fb.clause_id AS cb FROM conflicts cf "
                          "JOIN facts fa ON fa.fact_id=cf.fact_a JOIN facts fb ON fb.fact_id=cf.fact_b "
                          "ORDER BY cf.conflict_id"):
        if doc_scope is not None and not {_doc_of(conn, r["ca"]), _doc_of(conn, r["cb"])} <= set(doc_scope):
            continue
        if _in_effect(r, as_of) and versions.status(conn, r["ca"], as_of) == "in_force" \
                and versions.status(conn, r["cb"], as_of) == "in_force":
            out.append(r["conflict_id"])
    return out


def cards_from_ids(conn: sqlite3.Connection, ids: list[str], as_of: str) -> list[dict]:
    by_subject: dict[str, dict] = {}
    for cid in ids:
        r = conn.execute("SELECT * FROM conflicts WHERE conflict_id=?", (cid,)).fetchone()
        if r is None:
            continue
        card = by_subject.setdefault(r["subject_id"], {"conflict_id": cid, "conflict_ids": [], "subject": r["subject_id"],
                                                        "sides": [], "explanation": [], "type": r["type"],
                                                        "severity": r["severity"]})
        card["conflict_ids"].append(cid)
        if r["explanation"] not in card["explanation"]:
            card["explanation"].append(r["explanation"])
        for fid in (r["fact_a"], r["fact_b"]):
            f = _fact(conn, fid)
            if f is None or any(s["span_id"] == f["span_id"] for s in card["sides"]):
                continue
            sp = conn.execute("SELECT s.page,s.text,s.ocr_conf,d.title FROM spans s JOIN documents d ON d.doc_id=s.doc_id "
                              "WHERE s.span_id=?", (f["span_id"],)).fetchone()
            card["sides"].append({"span_id": f["span_id"], "clause_id": f["clause_id"], "doc": f["doc_id"],
                                  "doc_title": sp["title"] if sp else None, "page": sp["page"] if sp else None,
                                  "status": versions.status(conn, f["clause_id"], as_of), "value": f["value_raw"],
                                  "op": f["op"], "attribute": f["attribute"], "scope": json.loads(f["scope"] or "{}"),
                                  "text": sp["text"] if sp else None, "ocr": bool(sp and sp["ocr_conf"] is not None)})
    for card in by_subject.values():
        card["explanation"] = " · ".join(card["explanation"])
    return list(by_subject.values())


def conflict_partners(conn: sqlite3.Connection, clause_ids: list[str], as_of: str,
                      doc_scope: list[str] | None = None) -> list[str]:
    """In-force clauses on the other side of a conflict in effect: the answer must show both sides."""
    partners: list[str] = []
    for row, side in conflicts_in_effect(conn, clause_ids, as_of, doc_scope):
        other = row["cb"] if side == "a" else row["ca"]
        if other not in clause_ids and other not in partners:
            partners.append(other)
    return partners


def add_partners(conn: sqlite3.Connection, pack: EvidencePack, as_of: str, doc_scope: list[str] | None = None) -> list[str]:
    """Append the partner clauses' spans to the pack (they were not retrieved, but they are the other half of a conflict)."""
    have = {s.clause_id for s in pack.spans}
    added = []
    for cid in conflict_partners(conn, sorted(have), as_of, doc_scope):
        for sp in _load_spans(conn, cid, 0.0, "in_force"):
            if doc_scope is not None and sp.doc_id not in doc_scope:
                continue  # outside this chat's workspace or document picker
            pack.spans.append(sp)
            pack.tokens += approx_tokens(sp.line)
        added.append(cid)
    return added


def recheck(conn: sqlite3.Connection, clause_ids: list[str]) -> int:
    """§5.2: compare facts of the evidence clauses pairwise; persist conflicts that ingest did not find."""
    views = load_views(conn, clause_ids=clause_ids) if clause_ids else []
    return store(conn, find_conflicts(views), "query") if views else 0

