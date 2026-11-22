"""LLM backend: Ollama native /api/chat with JSON-schema structured output (ADR-011)."""
from __future__ import annotations

import time
from typing import Any

import httpx

from core import config


class OllamaBackend:
    def __init__(self, url: str | None = None, model: str | None = None) -> None:
        self.url = (url or config.OLLAMA_URL).rstrip("/")
        self.model = model or config.LLM_MODEL

    def chat(self, messages: list[dict[str, str]], json_schema: dict[str, Any] | None,
             max_tokens: int) -> tuple[str, int]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # Qwen3-series models think by default; that breaks latency and determinism
            "options": {"temperature": config.LLM_TEMPERATURE, "seed": config.LLM_SEED,
                        "num_ctx": config.LLM_NUM_CTX, "num_predict": max_tokens},
        }
        if json_schema:
            body["format"] = json_schema
        t0 = time.perf_counter()
        r = httpx.post(f"{self.url}/api/chat", json=body, timeout=config.LLM_TIMEOUT_S)
        r.raise_for_status()
        ms = int((time.perf_counter() - t0) * 1000)
        return r.json()["message"]["content"], ms

    def status(self) -> str:
        """'ready' if Ollama is up and has the model; else 'loading'."""
        try:
            tags = httpx.get(f"{self.url}/api/tags", timeout=5).json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return "loading"
        names = {m.get("name") for m in tags} | {m.get("model") for m in tags}
        want = self.model if ":" in self.model else f"{self.model}:latest"
        return "ready" if want in names else "loading"
