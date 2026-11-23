"""Workspaces: a named set of documents plus the chats that may use only those documents (ADR-024)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import deps
from core import config, db
from core.ingest import remove

router = APIRouter(prefix="/api")
ACTIVE_JOB_STATES = ("queued", "parsing", "ocr", "extracting", "resolving")  # not needs_ocr: that job is parked, not running


class WorkspaceBody(BaseModel):
    name: str


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise HTTPException(422, "Give the workspace a name.")
    if len(name) > config.WORKSPACE_NAME_MAX:
        raise HTTPException(422, f"The name can be at most {config.WORKSPACE_NAME_MAX} characters.")
    return name


def _out(conn: sqlite3.Connection, workspace_id: str) -> dict:
    return next(w for w in db.list_workspaces(conn) if w["workspace_id"] == workspace_id) | {
        "demo": workspace_id == config.DEFAULT_WORKSPACE_ID}


@router.get("/workspaces")
def list_workspaces(conn: sqlite3.Connection = Depends(deps.conn_dep)) -> list[dict]:
    return [w | {"demo": w["workspace_id"] == config.DEFAULT_WORKSPACE_ID} for w in db.list_workspaces(conn)]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceBody, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> dict:
    name = clean_name(body.name)
    if len(db.list_workspaces(conn)) >= config.MAX_WORKSPACES:
        raise HTTPException(409, f"At most {config.MAX_WORKSPACES} workspaces are allowed. Delete one you no longer need.")
    return _out(conn, db.create_workspace(conn, name).workspace_id)


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: str, body: WorkspaceBody, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> dict:
    deps.require_workspace(conn, workspace_id)
    db.rename_workspace(conn, workspace_id, clean_name(body.name))
    return _out(conn, workspace_id)


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, conn: sqlite3.Connection = Depends(deps.conn_dep)) -> None:
    deps.require_workspace(conn, workspace_id)
    if workspace_id == config.DEFAULT_WORKSPACE_ID:
        raise HTTPException(409, "The demo workspace cannot be deleted.")
    busy = conn.execute(f"SELECT 1 FROM ingest_jobs j JOIN documents d ON d.doc_id=j.doc_id WHERE d.workspace_id=? "
                        f"AND j.state IN ({','.join('?' * len(ACTIVE_JOB_STATES))}) LIMIT 1",
                        (workspace_id, *ACTIVE_JOB_STATES)).fetchone()
    if busy:  # the ingest worker would write into rows that no longer exist
        raise HTTPException(409, "Documents in this workspace are still being processed. Try again in a minute.")
    with deps.ANSWER_LOCK:  # an answer in flight must not lose its documents or its chat halfway
        remove.remove_workspace(conn, workspace_id)
