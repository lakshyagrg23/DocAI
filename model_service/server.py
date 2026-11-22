"""FastAPI model service: /llm/chat, /embed, /rerank, /nli, /health (architecture.md contract)."""
from __future__ import annotations

import hmac
from typing import Any, Protocol

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from core import config


class LLMBackend(Protocol):
    def chat(self, messages: list[dict[str, str]], json_schema: dict[str, Any] | None,
             max_tokens: int) -> tuple[str, int]: ...

    def status(self) -> str: ...


class AuxBackend(Protocol):
    loaded: list[str]

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]: ...

    def rerank(self, query: str, passages: list[str]) -> list[float]: ...

    def nli(self, pairs: list[tuple[str, str]]) -> list[float]: ...


class ChatReq(BaseModel):
    messages: list[dict[str, str]]
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 900


class EmbedReq(BaseModel):
    texts: list[str]
    batch_size: int = 32


class RerankReq(BaseModel):
    query: str
    passages: list[str]


class NliPair(BaseModel):
    premise: str
    hypothesis: str


class NliReq(BaseModel):
    pairs: list[NliPair]


def create_app(llm: LLMBackend | None = None, aux: AuxBackend | None = None,
               api_key: str | None = None) -> FastAPI:
    if llm is None:
        from model_service.llm_backend import OllamaBackend
        llm = OllamaBackend()
    if aux is None:
        from model_service.aux_models import AuxModels
        aux = AuxModels()
    key = api_key or config.MODEL_API_KEY

    def auth(authorization: str = Header(default="")) -> None:
        if not hmac.compare_digest(authorization.encode(), f"Bearer {key}".encode()):
            raise HTTPException(status_code=401, detail="bad token")

    app = FastAPI(title="docai model service", dependencies=[Depends(auth)])

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "llm": llm.status(), "models": list(aux.loaded)}

    @app.post("/llm/chat")
    def llm_chat(req: ChatReq) -> dict[str, Any]:
        try:
            text, ms = llm.chat(req.messages, req.json_schema, req.max_tokens)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=503, detail=f"ollama: {e!r}") from e
        return {"text": text, "ms": ms}

    @app.post("/embed")
    def embed(req: EmbedReq) -> dict[str, Any]:
        return {"dense": aux.embed(req.texts, req.batch_size)}

    @app.post("/rerank")
    def rerank(req: RerankReq) -> dict[str, Any]:
        return {"scores": aux.rerank(req.query, req.passages)}

    @app.post("/nli")
    def nli(req: NliReq) -> dict[str, Any]:
        return {"scores": aux.nli([(p.premise, p.hypothesis) for p in req.pairs])}

    return app
