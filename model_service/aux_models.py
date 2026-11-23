"""Embedding, reranker and NLI (HHEM) models. Lazy-loaded on first call (model-service.md)."""
from __future__ import annotations

import threading

import numpy as np

from core import config


class AuxModels:
    def __init__(self, device: str | None = None) -> None:
        self.device = device or config.AUX_DEVICE
        self._embedder = None
        self._reranker = None
        self._nli = None
        self._lock = threading.Lock()
        self.loaded: list[str] = []

    @property
    def _fp16(self) -> bool:
        return self.device == "cuda"

    def _get_embedder(self):
        with self._lock:
            if self._embedder is None:
                from FlagEmbedding import BGEM3FlagModel
                self._embedder = BGEM3FlagModel("BAAI/bge-m3", use_fp16=self._fp16, devices=self.device)
                self.loaded.append("bge-m3")
        return self._embedder

    def _get_reranker(self):
        with self._lock:
            if self._reranker is None:
                from FlagEmbedding import FlagReranker
                self._reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=self._fp16,
                                              devices=self.device)
                self.loaded.append("bge-reranker-v2-m3")
        return self._reranker

    def _get_nli(self):
        with self._lock:
            if self._nli is None:
                from transformers import AutoModelForSequenceClassification
                m = AutoModelForSequenceClassification.from_pretrained(
                    "vectara/hallucination_evaluation_model", trust_remote_code=True)
                self._nli = m.to(self.device).eval()
                self.loaded.append("hhem-2.1-open")
        return self._nli

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        out = self._get_embedder().encode(texts, batch_size=batch_size, max_length=1024)["dense_vecs"]
        arr = np.asarray(out, dtype=np.float32)
        arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
        return arr.tolist()

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        scores = self._get_reranker().compute_score([[query, p] for p in passages], normalize=True)
        return [float(s) for s in np.atleast_1d(scores)]

    def nli(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores = self._get_nli().predict(pairs)
        if hasattr(scores, "detach"):  # a torch tensor, possibly on the GPU
            scores = scores.detach().cpu().numpy()
        return [float(s) for s in np.atleast_1d(np.asarray(scores))]
