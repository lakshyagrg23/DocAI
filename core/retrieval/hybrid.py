"""Hybrid retrieval: dense + BM25 -> RRF -> cross-encoder rerank (retrieval.md §2). Read-only on DB and index."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import config
from core.llm.client import ModelClient
from core.retrieval import bm25
from core.retrieval.index import Index, index_dir, load_index


@dataclass
class Hit:
    window_id: str
    clause_id: str
    doc_id: str
    score: float  # rerank score (higher = more relevant)
    rrf: float
    dense_rank: int | None = None
    bm25_rank: int | None = None
    query: str = ""


def rrf(rankings: Iterable[list[str]], k: int = config.RRF_K) -> dict[str, float]:
    """Reciprocal rank fusion: score(id) = sum over lists of 1 / (k + rank), rank starting at 1."""
    out: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            out[item] = out.get(item, 0.0) + 1.0 / (k + rank)
    return out


class Retriever:
    def __init__(self, conn: sqlite3.Connection, client: ModelClient, data_dir: Path | None = None) -> None:
        self.conn, self.client, self.data_dir = conn, client, data_dir
        self._stamp: tuple[float, float] | None = None
        self.index: Index = Index(np.zeros((0, config.EMBED_DIM), np.float32), [], None)
        self.windows: dict[str, tuple[str, str, str]] = {}  # window_id -> (clause_id, doc_id, text)

    def _refresh(self) -> None:
        d = index_dir(self.data_dir)
        stamp = tuple((d / f).stat().st_mtime if (d / f).exists() else 0.0 for f in ("dense.npy", "bm25.pkl"))
        if stamp == self._stamp:
            return
        self.index = load_index(self.data_dir)
        self.windows = {r["window_id"]: (r["clause_id"], r["doc_id"], r["text"]) for r in
                        self.conn.execute("SELECT window_id,clause_id,doc_id,text FROM windows")}
        self._stamp = stamp  # type: ignore[assignment]

    def _allowed(self, doc_scope: list[str] | None) -> np.ndarray | None:
        if doc_scope is None:  # None = unrestricted; an empty list allows nothing (an empty workspace has no evidence)
            return None
        scope = set(doc_scope)
        return np.array([self.windows[w][1] in scope for w in self.index.window_ids], dtype=bool)

    def _dense(self, query: str, k: int, allowed: np.ndarray | None) -> list[int]:
        if self.index.dense.shape[0] == 0:
            return []
        q = np.asarray(self.client.embed([query])[0], dtype=np.float32)
        sims = self.index.dense @ q
        if allowed is not None:
            sims = np.where(allowed, sims, -np.inf)
        order = np.argsort(-sims, kind="stable")[:k]
        return [int(i) for i in order if np.isfinite(sims[i])]

    def search(self, query: str, doc_scope: list[str] | None = None) -> list[Hit]:
        """One query: dense + BM25 -> RRF (top 30) -> rerank -> best RERANK_KEEP windows."""
        self._refresh()
        ids = self.index.window_ids
        if not ids:
            return []
        allowed = self._allowed(doc_scope)
        dense = self._dense(query, config.TOPK_DENSE, allowed)
        lex = bm25.top_k(self.index, query, config.TOPK_BM25, allowed)
        fused = rrf([[ids[i] for i in dense], [ids[i] for i in lex]])
        dense_rank = {ids[i]: r for r, i in enumerate(dense, 1)}
        bm25_rank = {ids[i]: r for r, i in enumerate(lex, 1)}
        cands = sorted(fused, key=lambda w: (-fused[w], w))[:30]
        texts = [self.windows[w][2] for w in cands]
        scores: list[float] = []
        for i in range(0, len(texts), config.RERANK_CHUNK):  # short requests: CPU reranker must answer within AUX_TIMEOUT_S
            scores += self.client.rerank(query, texts[i:i + config.RERANK_CHUNK])
        ranked = sorted(zip(cands, scores, strict=True), key=lambda x: (-x[1], x[0]))[:config.RERANK_KEEP]
        return [Hit(window_id=w, clause_id=self.windows[w][0], doc_id=self.windows[w][1], score=float(s),
                    rrf=fused[w], dense_rank=dense_rank.get(w), bm25_rank=bm25_rank.get(w), query=query)
                for w, s in ranked]

    def retrieve(self, queries: list[str], doc_scope: list[str] | None = None) -> list[Hit]:
        """Union over (sub-)questions, keeping each window's best rerank score; best first."""
        best: dict[str, Hit] = {}
        for q in queries:
            for h in self.search(q, doc_scope):
                if h.window_id not in best or h.score > best[h.window_id].score:
                    best[h.window_id] = h
        return sorted(best.values(), key=lambda h: (-h.score, h.window_id))
