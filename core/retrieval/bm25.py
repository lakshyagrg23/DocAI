"""Lexical search over the BM25 index built at ingest."""
from __future__ import annotations

import numpy as np

from core.retrieval.index import Index, tokenize


def top_k(index: Index, query: str, k: int, allowed: np.ndarray | None = None) -> list[int]:
    """Row indexes (into index.window_ids) of the best BM25 matches, best first; zero-score rows are dropped."""
    if index.bm25 is None or not index.window_ids:
        return []
    toks = tokenize(query)
    if not toks:
        return []
    scores = np.asarray(index.bm25.get_scores(toks), dtype=np.float64)
    if allowed is not None:
        scores = np.where(allowed, scores, -np.inf)
    order = np.argsort(-scores, kind="stable")[:k]
    return [int(i) for i in order if scores[i] > 0]
