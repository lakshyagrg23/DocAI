"""Retrieval index: windows + dense .npy + BM25 pickle (ingest.md §5). Written at ingest, read-only at query time."""
from __future__ import annotations

import json
import pickle
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from core import config
from core.ingest.store import load_clauses
from core.models import Clause, Span, Window

EmbedFn = Callable[[list[str]], list[list[float]]]
TOKEN_RE = re.compile(r"[a-z0-9₹%]+(?:\.[0-9]+)*")
SKIP_KINDS = {"table", "table_header"}  # containers / header rows are never retrieved on their own


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3) + 1


def index_dir(data_dir: Path | None = None) -> Path:
    d = (data_dir or config.DATA_DIR) / "index"
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_windows(clause: Clause, spans: list[Span]) -> list[Window]:
    """One window per clause, or several (WINDOW_TOKENS with WINDOW_OVERLAP) cut at span boundaries."""
    if clause.kind in SKIP_KINDS or not spans:
        return []
    groups: list[list[Span]] = []
    cur: list[Span] = []
    cur_tok = 0
    for sp in spans:
        t = approx_tokens(sp.text)
        if cur and cur_tok + t > config.WINDOW_TOKENS:
            groups.append(cur)
            overlap: list[Span] = []
            tot = 0
            for s in reversed(cur):
                tt = approx_tokens(s.text)
                if tot + tt > config.WINDOW_OVERLAP:
                    break
                overlap.insert(0, s)
                tot += tt
            cur, cur_tok = overlap, tot
        cur.append(sp)
        cur_tok += t
    groups.append(cur)
    prefix = f"{clause.heading_trail}\n" if clause.heading_trail else ""
    return [Window(window_id=f"{clause.clause_id}@w{i}", clause_id=clause.clause_id, doc_id=clause.doc_id,
                   text=prefix + " ".join(s.text for s in g), span_ids=[s.span_id for s in g])
            for i, g in enumerate(groups, start=1)]


def embed_chunked(embed_fn: EmbedFn, texts: list[str]) -> np.ndarray:
    out: list[list[float]] = []
    for i in range(0, len(texts), config.EMBED_CHUNK):
        out.extend(embed_fn(texts[i:i + config.EMBED_CHUNK]))
    return np.asarray(out, dtype=np.float32).reshape(len(texts), -1) if out else np.zeros((0, config.EMBED_DIM), np.float32)


def _write_bm25(conn: sqlite3.Connection, idir: Path) -> None:
    rows = conn.execute("SELECT window_id, text FROM windows ORDER BY row_idx").fetchall()
    path = idir / "bm25.pkl"
    if not rows:
        path.unlink(missing_ok=True)
        return
    bm25 = BM25Okapi([tokenize(r["text"]) or ["_"] for r in rows])
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({"window_ids": [r["window_id"] for r in rows], "bm25": bm25}, f)
    tmp.replace(path)


def _rewrite(conn: sqlite3.Connection, doc_id: str, new: list[Window], new_vecs: np.ndarray,
             data_dir: Path | None) -> None:
    """Replace the doc's windows. Embeddings are computed before this runs, so a failure leaves the index intact."""
    idir = index_dir(data_dir)
    dense_path = idir / "dense.npy"
    old = np.load(dense_path).astype(np.float32) if dense_path.exists() else np.zeros((0, new_vecs.shape[1] if len(new_vecs) else config.EMBED_DIM), np.float32)
    kept = conn.execute("SELECT window_id,row_idx FROM windows WHERE doc_id!=? ORDER BY row_idx", (doc_id,)).fetchall()
    kept_mat = old[[r["row_idx"] for r in kept]] if kept else np.zeros((0, old.shape[1]), np.float32)
    mat = np.vstack([kept_mat, new_vecs]) if len(new_vecs) else kept_mat
    conn.execute("DELETE FROM windows WHERE doc_id=?", (doc_id,))
    conn.executemany("UPDATE windows SET row_idx=? WHERE window_id=?", [(i, r["window_id"]) for i, r in enumerate(kept)])
    base = len(kept)
    conn.executemany(
        "INSERT INTO windows(window_id,clause_id,doc_id,text,span_ids,row_idx) VALUES(?,?,?,?,?,?)",
        [(w.window_id, w.clause_id, w.doc_id, w.text, json.dumps(w.span_ids), base + i) for i, w in enumerate(new)])
    conn.commit()
    tmp = dense_path.with_suffix(".tmp.npy")
    np.save(tmp, mat.astype(np.float16))
    tmp.replace(dense_path)
    _write_bm25(conn, idir)


def reindex_doc(conn: sqlite3.Connection, doc_id: str, embed_fn: EmbedFn, data_dir: Path | None = None) -> int:
    """(Re)build the doc's windows from its stored clauses and spans; returns the number of windows."""
    clauses, spans = load_clauses(conn, doc_id)
    by_clause: dict[str, list[Span]] = {}
    for s in spans:
        by_clause.setdefault(s.clause_id, []).append(s)
    windows = [w for c in clauses for w in make_windows(c, by_clause.get(c.clause_id, []))]
    vecs = embed_chunked(embed_fn, [w.text for w in windows]) if windows else np.zeros((0, config.EMBED_DIM), np.float32)
    _rewrite(conn, doc_id, windows, vecs, data_dir)
    return len(windows)


def remove_doc(conn: sqlite3.Connection, doc_id: str, data_dir: Path | None = None) -> None:
    _rewrite(conn, doc_id, [], np.zeros((0, config.EMBED_DIM), np.float32), data_dir)


@dataclass
class Index:
    dense: np.ndarray  # (n, dim) float32, L2-normalised, aligned with windows.row_idx
    window_ids: list[str]
    bm25: BM25Okapi | None


def load_index(data_dir: Path | None = None) -> Index:
    idir = index_dir(data_dir)
    dense_path, bm_path = idir / "dense.npy", idir / "bm25.pkl"
    dense = np.load(dense_path).astype(np.float32) if dense_path.exists() else np.zeros((0, config.EMBED_DIM), np.float32)
    if bm_path.exists():
        with open(bm_path, "rb") as f:
            blob = pickle.load(f)
        return Index(dense, blob["window_ids"], blob["bm25"])
    return Index(dense, [], None)
