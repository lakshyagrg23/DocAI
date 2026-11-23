"""Client for our model service at MODEL_BASE_URL. The only place the app makes model calls."""
from __future__ import annotations

import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from core import config

T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(RuntimeError):
    """Model service unreachable or erroring after retries; the UI shows the amber 'warming up' state."""


class ModelClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None, backoff_s: float = 1.0) -> None:
        self.base_url = (base_url or config.MODEL_BASE_URL).rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key or config.MODEL_API_KEY}"},
            transport=transport,
            follow_redirects=True,  # Modal answers a cold start / long call with a 303 that must be followed
        )
        self._backoff_s = backoff_s

    def _post(self, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(config.CLIENT_ATTEMPTS):
            try:
                r = self._http.post(path, json=payload, timeout=timeout)
                if r.status_code in (401, 403, 422):  # not retryable
                    raise ModelUnavailable(f"{path}: HTTP {r.status_code} {r.text[:200]}")
                r.raise_for_status()
                return r.json()
            except ModelUnavailable:
                raise
            except (httpx.HTTPError, ValueError) as e:
                last = e
                if attempt < config.CLIENT_ATTEMPTS - 1:
                    time.sleep(self._backoff_s * 2**attempt)
        raise ModelUnavailable(f"{path}: {last!r}")

    def health(self) -> dict[str, Any]:
        try:
            r = self._http.get("/health", timeout=10)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ModelUnavailable(f"/health: {e!r}") from e

    def chat(self, messages: list[dict[str, str]], max_tokens: int = 900,
             json_schema: dict[str, Any] | None = None) -> str:
        out = self._post("/llm/chat", {"messages": messages, "json_schema": json_schema,
                                       "max_tokens": max_tokens}, config.LLM_TIMEOUT_S)
        return out["text"]

    def chat_json(self, messages: list[dict[str, str]], model_cls: type[T], max_tokens: int = 900) -> T:
        """Guided decoding + Pydantic validation + LLM_MAX_RETRIES retries with the error appended."""
        schema = model_cls.model_json_schema()
        msgs = list(messages)
        err: ValidationError | None = None
        for _ in range(config.LLM_MAX_RETRIES + 1):
            text = self.chat(msgs, max_tokens=max_tokens, json_schema=schema)
            try:
                return model_cls.model_validate_json(text)
            except ValidationError as e:
                err = e
                msgs = [*messages,
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": f"Your JSON was invalid: {e.errors(include_url=False)}. "
                                                    "Return corrected JSON only."}]
        raise ModelUnavailable(f"chat_json: invalid output after retry: {err}")

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        if not texts:
            return []
        return self._post("/embed", {"texts": texts, "batch_size": batch_size}, config.AUX_TIMEOUT_S)["dense"]

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return self._post("/rerank", {"query": query, "passages": passages}, config.AUX_TIMEOUT_S)["scores"]

    def nli(self, pairs: list[tuple[str, str]]) -> list[float]:
        """pairs = (premise, hypothesis). Returns HHEM consistency 0-1."""
        if not pairs:
            return []
        body = {"pairs": [{"premise": p, "hypothesis": h} for p, h in pairs]}
        return self._post("/nli", body, config.AUX_TIMEOUT_S)["scores"]


_default: ModelClient | None = None


def get_client() -> ModelClient:
    global _default
    if _default is None:
        _default = ModelClient()
    return _default
