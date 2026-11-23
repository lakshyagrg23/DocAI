"""Chats, messages and the SSE `ask` endpoint (design/ui-react.md §5)."""
from __future__ import annotations

import asyncio
import json
import queue
import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from api import access, deps, export, serialize
from core import db
from core.answer import assemble
from core.llm.client import ModelUnavailable

router = APIRouter(prefix="/api")

STEPS = ["Planning", "Retrieving", "Drafting", "Verifying", "Checking conflicts"]
PLAIN = {"Planning": "Understanding your question", "Retrieving": "Finding relevant passages", "Drafting": "Writing the answer",
         "Verifying": "Checking every statement against the documents", "Checking conflicts": "Comparing documents for disagreements"}


class ChatPatch(BaseModel):
    title: str | None = None
    as_of_date: str | None = None
    language: str | None = None
    doc_scope: list[str] | None = None  # [] clears the scope (all documents)


class Ask(BaseModel):
    question: str


def chat_out(c: Any) -> dict:
    return c.model_dump()


@router.get("/chats")
def list_chats(conn: sqlite3.Connection = Depends(deps.conn_dep)) -> list[dict]:
    return [chat_out(c) for c in db.list_chats(conn)]


@router.post("/chats", status_code=201)
def create_chat(conn: sqlite3.Connection = Depends(deps.conn_dep)) -> dict:
    return chat_out(db.create_chat(conn, as_of_date=deps.today()))


@router.patch("/chats/{chat_id}")
def patch_chat(chat_id: str, body: ChatPatch, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> dict:
    if db.get_chat(conn, chat_id) is None:
        raise HTTPException(404, "chat not found")
    if body.title and body.title.strip():
        db.rename_chat(conn, chat_id, body.title.strip())
    if body.doc_scope:
        known = {r["doc_id"] for r in conn.execute("SELECT doc_id FROM documents")}
        unknown = [d for d in body.doc_scope if d not in known]
        if unknown:
            raise HTTPException(422, f"unknown document: {unknown[0]}")
    db.update_chat_settings(conn, chat_id, as_of_date=body.as_of_date, language=body.language, doc_scope=body.doc_scope)
    return chat_out(db.get_chat(conn, chat_id))  # type: ignore[arg-type]


@router.delete("/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: str, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> None:
    db.delete_chat(conn, chat_id)


@router.get("/chats/{chat_id}/messages")
def messages(chat_id: str, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> list[dict]:
    if db.get_chat(conn, chat_id) is None:
        raise HTTPException(404, "chat not found")
    return [serialize.message_out(conn, m) for m in db.list_messages(conn, chat_id)]


@router.get("/chats/{chat_id}/export")
def export_chat(chat_id: str, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> Response:
    built = export.build(conn, chat_id)
    if built is None:
        raise HTTPException(404, "chat not found")
    name, text = built
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _step_of(label: str) -> int:
    return next((i for i, s in enumerate(STEPS) if label.startswith(s)), len(STEPS))


@router.post("/chats/{chat_id}/ask")
async def ask(chat_id: str, body: Ask, conn: sqlite3.Connection = Depends(deps.conn_dep),
              _limit: None = Depends(access.limit_ask)) -> StreamingResponse:
    chat = db.get_chat(conn, chat_id)
    if chat is None:
        raise HTTPException(404, "chat not found")
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "question is empty")
    events: queue.Queue[tuple[str, dict] | None] = queue.Queue()

    def work() -> None:
        wconn = db.connect()
        try:
            events.put(("stage", {"step": 0, "total": len(STEPS), "label": "Waiting for the model", "key": "Waiting"}))
            if deps.passive_health():
                deps.wake_model(lambda: events.put(("stage", {
                    "step": 0, "total": len(STEPS), "key": "Waiting",
                    "label": "Waking the model: after a quiet spell this takes about 3 minutes"})))
            with deps.ANSWER_LOCK:
                def on_stage(label: str) -> None:
                    key = next((s for s in STEPS if label.startswith(s)), "Done")
                    events.put(("stage", {"step": _step_of(label) + 1, "total": len(STEPS), "key": key,
                                          "label": PLAIN.get(key, "Done")}))
                assemble.answer(wconn, question, chat_id, as_of=chat.as_of_date, client=deps.get_model(),
                                retriever=deps.get_retriever(), on_stage=on_stage)
            deps.MODEL_STATUS.ok()
            last = db.list_messages(wconn, chat_id)[-1]
            events.put(("answer", {"user": serialize.message_out(wconn, db.list_messages(wconn, chat_id)[-2]),
                                   "assistant": serialize.message_out(wconn, last),
                                   "chat": chat_out(db.get_chat(wconn, chat_id))}))  # type: ignore[arg-type]
        except ModelUnavailable:
            deps.MODEL_STATUS.fail()
            events.put(("error", {"message": "The model is not reachable right now. Please try again in a moment."}))
        except Exception as e:  # noqa: BLE001 - report any failure to the client instead of hanging the stream
            events.put(("error", {"message": f"Something went wrong: {type(e).__name__}"}))
        finally:
            wconn.close()
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                return
            yield _sse(*item)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
