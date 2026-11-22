"""Version expansion (retrieval.md §3): tag clauses in_force | superseded | future as of a date.

M3 scope: uses `clause_versions` rows when they exist (written by M5) and otherwise the document's effective date.
Amendment edges, supersede_doc and version-key rewrites arrive in M5.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

Status = Literal["in_force", "superseded", "future"]


@dataclass
class Candidate:
    clause_id: str
    status: Status
    version_key: str
    valid_from: str | None = None
    valid_to: str | None = None


def status_on(valid_from: str | None, valid_to: str | None, as_of: str) -> Status:
    """ISO dates compare lexicographically. Interval is [valid_from, valid_to); valid_to None = open-ended."""
    if valid_from is not None and as_of < valid_from:
        return "future"
    if valid_to is not None and as_of >= valid_to:
        return "superseded"
    return "in_force"


def expand(conn: sqlite3.Connection, clause_ids: list[str], as_of: str) -> dict[str, Candidate]:
    """Candidates for the given clauses plus every other version sharing their version key."""
    out: dict[str, Candidate] = {}
    for cid in clause_ids:
        row = conn.execute(
            "SELECT c.version_key, d.effective_date FROM clauses c JOIN documents d ON d.doc_id=c.doc_id "
            "WHERE c.clause_id=?", (cid,)).fetchone()
        if row is None:
            continue
        vkey = row["version_key"] or cid
        versions = conn.execute("SELECT clause_id,valid_from,valid_to FROM clause_versions WHERE version_key=? "
                                "ORDER BY version_no", (vkey,)).fetchall()
        if versions:
            for v in versions:
                if v["clause_id"] is None:  # deletion marker: the rule ended, there is no text to show
                    continue
                out[v["clause_id"]] = Candidate(v["clause_id"], status_on(v["valid_from"], v["valid_to"], as_of),
                                                vkey, v["valid_from"], v["valid_to"])
        if cid not in out:
            out[cid] = Candidate(cid, status_on(row["effective_date"], None, as_of), vkey, row["effective_date"])
    return out
