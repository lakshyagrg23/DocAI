"""FastAPI app: `uvicorn api.main:app --port 8000`. Serves the JSON API and, when built, the React app from web/dist."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import access
from api.routes import chats, documents, knowledge
from core import db

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init_db().close()  # create the schema once; request handlers use plain connections
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Verifiable DocAI API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(access.router)  # /api/session and /api/login stay open
    for r in (chats.router, documents.router, knowledge.router):
        app.include_router(r, dependencies=[Depends(access.require_access)])
    if (DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:  # client-side routes fall back to index.html
            target = DIST / path
            return FileResponse(target if path and target.is_file() else DIST / "index.html")
    return app


app = create_app()
