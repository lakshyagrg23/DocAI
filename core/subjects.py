"""Subject canonicalisation (facts-and-subjects.md §4): map free-text subjects from different documents to one id."""
from __future__ import annotations

import json
import re
import sqlite3

import numpy as np
from rapidfuzz import fuzz

from core import config
from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import SameSubject
from core.subjects_seed import SEED

STOP = {"the", "of", "for", "on", "a", "an", "to", "and", "in", "by", "any", "per"}


def slug(label: str) -> str:
    words = [w for w in re.split(r"[^a-z0-9]+", label.lower()) if w and w not in STOP]
    return "_".join(words) or "unknown"


def ensure_seed(conn: sqlite3.Connection) -> None:
    for sid, aliases in SEED.items():
        if conn.execute("SELECT 1 FROM subjects WHERE subject_id=?", (sid,)).fetchone() is None:
            conn.execute("INSERT INTO subjects(subject_id,label,aliases,emb_row) VALUES(?,?,?,NULL)",
                         (sid, sid.replace("_", " "), json.dumps(aliases)))
    conn.commit()


def _aliases(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    out = []
    for r in conn.execute("SELECT subject_id,label,aliases FROM subjects"):
        out.append((r["subject_id"], r["label"]))
        out += [(r["subject_id"], a) for a in json.loads(r["aliases"] or "[]")]
    return out


def fuzzy_match(conn: sqlite3.Connection, label: str) -> str | None:
    """Alias match. A one-word alias ("interest", "age") must be the whole label: it would otherwise swallow
    every label that merely contains it."""
    norm = " ".join(w for w in re.split(r"[^a-z0-9]+", label.lower()) if w)
    best: tuple[float, str] | None = None
    for sid, alias in _aliases(conn):
        a = " ".join(w for w in re.split(r"[^a-z0-9]+", alias.lower()) if w)
        if not a:
            continue
        score = 100.0 if a == norm else 0.0 if " " not in a else fuzz.token_set_ratio(norm, a)
        if score >= config.SUBJECT_FUZZ_MIN and (best is None or score > best[0]):
            best = (score, sid)
    return best[1] if best else None


def _add_alias(conn: sqlite3.Connection, sid: str, label: str) -> None:
    row = conn.execute("SELECT aliases FROM subjects WHERE subject_id=?", (sid,)).fetchone()
    aliases = json.loads(row["aliases"] or "[]")
    if label not in aliases:
        aliases.append(label)
        conn.execute("UPDATE subjects SET aliases=? WHERE subject_id=?", (json.dumps(aliases), sid))
        conn.commit()


def canonical_subject(conn: sqlite3.Connection, label: str, client: ModelClient | None = None) -> str:
    """Return the subject_id for `label`, creating a subject when nothing matches."""
    ensure_seed(conn)
    label = label.strip()
    sid = fuzzy_match(conn, label)
    if sid:
        _add_alias(conn, sid, label)
        return sid
    rows = conn.execute("SELECT subject_id,label FROM subjects").fetchall()
    if client is not None and rows:
        try:
            labels = [r["label"] for r in rows]
            vecs = np.asarray(client.embed([label, *labels]), dtype=np.float32)
            vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
            sims = vecs[1:] @ vecs[0]
            i = int(np.argmax(sims))
            if sims[i] >= config.SUBJECT_SIM_MIN:
                _version, system = load_prompt("same_subject")
                verdict = client.chat_json(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": f"A: {label}\nB: {labels[i]}"}], SameSubject, max_tokens=30)
                if verdict.same:
                    _add_alias(conn, rows[i]["subject_id"], label)
                    return rows[i]["subject_id"]
        except (ModelUnavailable, ValueError):
            pass  # no model: fall through and create a new subject
    new_id = slug(label)
    if conn.execute("SELECT 1 FROM subjects WHERE subject_id=?", (new_id,)).fetchone() is None:
        conn.execute("INSERT INTO subjects(subject_id,label,aliases,emb_row) VALUES(?,?,?,NULL)",
                     (new_id, label, json.dumps([label])))
        conn.commit()
    return new_id


ATTRIBUTES = {"amount", "rate", "age", "tenure", "date", "permitted", "other"}


def normalise_attribute(attribute: str, value_type: str) -> str:
    a = attribute.strip().lower()
    if a in ATTRIBUTES:
        return a
    if "age" in a.split():
        return "age"
    if value_type in ("percent",):
        return "rate"
    if value_type == "money":
        return "amount"
    if value_type == "duration":
        return "tenure"
    if value_type == "date":
        return "date"
    if value_type == "bool":
        return "permitted"
    return "other"
