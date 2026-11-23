# Design: Workspaces

Decision record: ADR-024. Status: implemented 2026-11-23 (backend, API, React UI). Not yet deployed.

A **workspace** is a named set of documents plus the chats about them, like a ChatGPT/Claude project, built for this product:
documents are only ever compared with other documents of the *same* workspace, so one matter's amendments and conflicts can never
mix with another's. The UI says "workspace" everywhere; the code and database say `workspace_id`.

## 1. Rules (what must always hold)

1. Every document and every chat belongs to exactly one workspace.
2. A chat can read only its workspace's documents. Its optional document picker (`chats.doc_scope`) can only *narrow* that set.
3. Scope is a hard boundary: an **empty list means "no documents"**, never "everything". `None` (unrestricted) exists only for
   legacy callers without a chat (eval scripts).
4. Ingest never crosses workspaces: conflict scans, amendment-target resolution and version timelines use only one workspace's
   documents. The same PDF may be uploaded to several workspaces; each upload is its own document.
5. Nothing from another workspace may be returned to the browser, even via a model-written span id in a blocked claim.
6. Workspaces are an **organisation boundary, not a security boundary**: there are still no user accounts, one access code gates the
   whole app (ADR-021), and `GET /api/spans/{id}` / page images are addressed by id only.

## 2. Data model

| Table | Change |
|---|---|
| `workspaces` (new) | `workspace_id` (`ws_<ulid>`), `name`, `created_at` |
| `documents` | + `workspace_id`; `sha256` is unique **per workspace** (`UNIQUE(workspace_id, sha256)`), not globally |
| `chats` | + `workspace_id` |

- Document ids: stable `D1`…`H3` for trusted local ingest; uploads are `U` + 6 hex. Outside the default workspace the hex also
  hashes the workspace id, so the same PDF in two workspaces gets two ids. A stable id already used by another workspace falls back
  to the hashed form.
- **Default workspace** (`config.DEFAULT_WORKSPACE_ID = "ws_demo"`, name "Kestrel demo"): trusted local ingest and tests land there
  (`enqueue(..., workspace_id=DEFAULT)`), and it is where everything that existed before workspaces is moved. It cannot be deleted
  through the API (a public visitor must not be able to delete the demo).
- `core/config.py`: `MAX_WORKSPACES = 20`, `WORKSPACE_NAME_MAX = 60`.

### Migration (`db.migrate`, run by every `init_db`)
Idempotent. (1) adds `workspace_id` to `documents` and `chats` if missing; (2) if `documents` still has the old global
`UNIQUE(sha256)`, rebuilds the table with the per-workspace constraint (SQLite cannot drop a constraint); (3) creates the indexes;
(4) if any document or chat has no workspace, creates the default workspace and assigns them to it. A fresh database has no
workspaces and is not seeded. Verified on a copy of the real local database (6 documents moved, nothing lost).

## 3. How scope is enforced

`db.chat_doc_scope(conn, chat)` = the workspace's document ids, intersected with the chat's picker when it has one. It is the single
source of the list passed as `doc_scope` through the existing plumbing:

| Where | Mechanism |
|---|---|
| Retrieval | `Retriever._allowed` masks dense and BM25 candidates. `assemble` skips retrieval entirely when the scope is `[]` |
| Evidence pack | `evidence.restrict` (amendment versions can live in other documents) |
| Conflicts at query time | `disagree.conflicts_in_effect`, `add_partners`, `mark_contradicted`: both sides must be in scope |
| Conflicts page | `disagree.active_conflict_ids(conn, as_of, doc_scope)` |
| Amendments page | version keys filtered by document; unresolved list joined to documents of the workspace |
| Ingest conflict scan | `conflicts.run` loads only the document's workspace (`load_views(workspace_id=)`) and deletes/re-stores only that workspace's `ingest` conflicts |
| Amendment targets | `amendments.resolve_all` skips candidate target documents of another workspace |
| Answer JSON → browser | `serialize.enrich_answer(allowed_docs)` drops span ids of other workspaces (also used by the Markdown export) |

The semantics change in `hybrid._allowed`, `evidence.restrict` and `disagree` (`is None` instead of falsiness) is what makes an empty
workspace answer "I don't have proof" instead of searching everything.

Deliberately **not** per-workspace: the subject registry (`subjects`: labels and aliases such as `late_payment_fee`). It is a
vocabulary, not evidence; conflicts are still only formed between facts of one workspace. The dense/BM25 index is also global and
filtered by scope at query time (cheap at this size; revisit if workspaces grow to thousands of documents).

## 4. API

| Method + path | Notes |
|---|---|
| `GET /api/workspaces` | with `documents`, `ready`, `chats` counts and `demo` (true for the default workspace) |
| `POST /api/workspaces` `{name}` | name trimmed, 1–60 chars (422); at most 20 workspaces (409) |
| `PATCH /api/workspaces/{id}` `{name}` | |
| `DELETE /api/workspaces/{id}` | 204. 409 for the demo workspace and while any of its documents is still being ingested (`queued/parsing/ocr/extracting/resolving`; a parked `needs_ocr` job does not block). Removes chats, messages, documents, derived rows, index entries and uploaded files (only under `DATA_DIR/uploads`, and not files other documents still use). Holds the answer lock |
| `GET /api/documents?workspace_id=` | workspace required (422 without, 404 if unknown) |
| `POST /api/documents?workspace_id=` | upload into that workspace |
| `GET /api/chats?workspace_id=`, `POST /api/chats {workspace_id}` | |
| `PATCH /api/chats/{id}` | `doc_scope` must be documents of the chat's own workspace (422) |
| `GET /api/conflicts?workspace_id=&as_of=`, `GET /api/amendments?workspace_id=&as_of=` | |

There is no endpoint that lists everything across workspaces. Single-document delete is **not** built (see §7).

## 5. UI

- Routes: `/` redirects to the last-used workspace (localStorage `docai.workspace`), else the first, else `/workspaces`.
  `/workspaces` lists workspaces as cards (counts, "Demo" badge, rename, delete with confirmation; no delete for the demo).
  Everything else lives under `/w/:workspaceId/{,chat/:chatId,library,conflicts,amendments}`. Old un-prefixed URLs redirect to `/`.
- `WorkspaceGate` (route element for `/w/:workspaceId`): unknown/deleted workspace → `/workspaces`; closes the Sources panel when the
  workspace changes; waits while the list is refetching so a just-created workspace is not bounced.
- Sidebar: workspace switcher at the top (menu: all workspaces, "All workspaces" link), then New chat, search and that
  workspace's chats; Documents / Conflicts / Amendments links point inside the workspace. Collapsed rail has the same links.
- Chat page: header shows "Workspace / chat title". Opening a chat id that is not in the open workspace goes back to the start
  screen. Empty states: no documents → "Add documents to get started" with a link; the example questions appear only in the demo
  workspace (they are about the demo corpus); other workspaces get a plain prompt.
- Library, Conflicts, Amendments, the composer's document picker and uploads all take the workspace from the URL. Query keys include the
  workspace id (`['chats', wid]`, `['documents', wid]`, `['conflicts', wid, asOf]`, …).
- Wording lives in the page files and `plain.ts` (`plural`).

## 6. Change log (2026-11-23)

Backend
- `core/config.py`: workspace constants. `core/models.py`: `Workspace`, `workspace_id` on `Document` and `Chat`.
- `core/db.py`: schema, `migrate()`, workspace DAOs (`create/get/list/rename/ensure_workspace`, `workspace_doc_ids`, `workspace_of_doc`,
  `chat_doc_scope`), workspace-aware `create_chat`, `list_chats`, `list_documents`.
- `core/ingest/register.py` (`make_doc_id` takes the workspace), `pipeline.py` (`enqueue(workspace_id=)`, per-workspace dedupe, id
  collision fallback), `conflicts.py`, `amendments.py` (isolation), new `remove.py` (`remove_document`, `remove_workspace`).
- `core/retrieval/hybrid.py`, `evidence.py`, `core/answer/disagree.py`, `assemble.py` (hard-boundary scope).
- `api/routes/workspaces.py` (new), `documents.py`, `chats.py`, `knowledge.py`, `deps.py` (`require_workspace`), `main.py`,
  `serialize.py`, `export.py` (workspace name; sources limited to the workspace). One unrelated lint fix in `export.py` (`.values()`).

Frontend
- New: `pages/Workspaces.tsx`, `layout/WorkspaceGate.tsx` (+ `HomeRedirect`), `state/workspace.tsx`.
- Changed: `main.tsx` (routes), `layout/Sidebar.tsx`, `chat/ChatPage.tsx`, `Composer.tsx`, `ScopeMenu.tsx`, `pages/Library.tsx`,
  `Conflicts.tsx`, `Amendments.tsx`, `lib/api.ts`, `lib/types.ts`, `lib/plain.ts`.

Tests
- Backend: new `tests/test_workspaces.py` (migration of a legacy database, same PDF in two workspaces, conflicts/amendments never cross,
  scope as hard boundary, empty workspace abstains, other-workspace chat cannot cite, endpoints require a workspace, picker validation,
  create/rename/limits, demo and busy workspaces cannot be deleted, deletion removes only its own data and files). Existing API,
  access and passive-health tests updated for the workspace parameter. Suite: 219 passed, ruff clean.
- Frontend: new tests for the Workspaces page, `WorkspaceGate`/`HomeRedirect` (including the create-then-open race), and the Sidebar;
  `ScopeMenu`, `Composer` and `plural` tests updated. 40 passed, `tsc` clean, production build OK.
- Browser (local app on a copy of the real data): redirect to the demo workspace, create a workspace, empty states, demo conflicts only in
  the demo. One bug found and fixed there (new workspace bounced back to the list before the list refetched).

## 7. Not done / open

- **Deleting a single document** is not available. Removing one document needs a conflict re-scan (its amendments change other facts'
  validity), and a re-scan with the LLM judge can hang a request while the GPU is asleep. A clean design: remove the document, then
  queue the re-scan on the ingest worker. Deleting a whole workspace is available.
- Not deployed. Modal's app migrates its restored `/state` database on start (everything goes into "Kestrel demo"); redeploy `docai-app`
  to ship this. `deploy/modal_app_ui.py` needed no change.
- No GPU/LLM run was done: the real-model eval was not re-run (retrieval/answering code paths are unchanged for the demo workspace
  apart from the scope list; the offline suite covers the boundary).
- Upload in a real browser against the model service was not exercised (the model service was not running).
- Per-workspace index files, per-workspace subject registry, and user accounts are intentionally out of scope.
