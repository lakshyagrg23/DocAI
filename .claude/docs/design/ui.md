# Design: UI (Streamlit)

Covers FR-5, FR-7, FR-10, FR-11, FR-15, FR-17, FR-18, FR-19. Code: `app/main.py`, `app/pages/*.py`, `app/components/*.py`, `app/i18n.py`.
The UI holds no business logic. It calls `core.answer.assemble.answer`, `core.ingest.pipeline.enqueue` and read-only DB queries.

## Navigation

`st.navigation` with four pages: **Chat** (default), **Documents**, **Conflicts**, **Amendments**. `st.set_page_config(layout="wide")`.

## Sidebar (all pages)

- App name + one-line promise: "Answers only with proof."
- **Model status dot:** `client.health()` cached for 15 s → 🟢 Ready / 🟠 Warming up / 🔴 Offline.
- **Chats** (FR-15): "New chat" button; chat list (newest first, from the `chats` table) as buttons; the active chat is stored in
  `st.session_state.chat_id`, and in `st.query_params["chat"]` so a reload keeps it. Each item has a ⋯ popover with Rename and Delete.
- **Chat settings** (active chat): as-of date (`st.date_input`, default today; persisted to `chats.as_of_date`), language
  (Auto / English / हिन्दी), document scope multiselect (P2).

## Chat page

Layout: `col_chat, col_evidence = st.columns([3, 2])`.

**col_chat**
- History: for each message, `st.chat_message(role)`; assistant messages render the **answer card** from `answer_json`.
- Input: `st.chat_input("Ask about your documents…")`. On submit, `with st.status("Working…") as s:` and pass
  `on_stage=lambda name: s.update(label=name)` to `answer()`.

**Answer card** (`components/answer_card.py`), top to bottom:
1. Status chip: ✅ Answered · ◐ Partially answered · ⚠ Documents disagree · ⛔ I don't have proof. Abstention uses neutral
   styling, not error red; it's a deliberate outcome.
2. Faithfulness badge: `Faithfulness 83% · 5 of 6 drafted claims verified` (tooltip explains the definition) + as-of date.
3. Body: each supported claim as a line followed by citation pills. A pill is a small `st.button` labelled
   `D1 · p.4` (doc short title, page). Clicking it sets `st.session_state.evidence = span_id`.
   Under each claim, a collapsed expander "Quote" shows the verbatim span text (table rows rendered as a 2-row mini table).
4. **Documents disagree** cards: one per subject; `st.columns(n_sides)`; each side: doc title, clause, page, date range,
   status chip (in force / superseded), verbatim quote, pill. The explanation line goes under the cards.
5. **Rule in force** card: vertical timeline (markdown + small HTML/CSS): one row per step with date range, action, doc and quote;
   the in-force step highlighted.
6. **Calculation** card: formula (st.latex), inputs table (name, value, source pill or "from your question"), steps, bold result.
7. **What's missing** list (if any).
8. Expander **Blocked claims (N)**: claim text, reason, check values (numbers_ok, version_ok, hhem score).
9. Expander **Audit**: a `st.download_button` with the answer JSON (P2: also Markdown).

**col_evidence**: evidence viewer (`components/evidence.py`)
- Shows the page for `st.session_state.evidence` (default: the first citation of the latest answer).
- Header: doc title · page x/y · OCR badge with confidence if `is_ocr`.
- Image from `core/render/highlight.py: render(doc_id, page, highlight_bboxes, dpi=110) -> PNG bytes`:
  `pix = page.get_pixmap(dpi=dpi)`, then Pillow draws semi-transparent yellow rectangles (orange for OCR) scaled by `dpi/72`.
  Cache by (doc, page, bboxes) with `st.cache_data`.
- ◀ ▶ page navigation; "Open full clause" shows the clause text.

## Documents page

- `st.file_uploader(accept_multiple_files=True, type="pdf")` → save to `DATA_DIR/uploads/` → `enqueue()` each.
- Table (`st.dataframe`): title, type, ref no, issue, effective, pages, clauses, facts, OCR, status. Auto-refresh every 2 s
  (`st.fragment(run_every=2)`) while any doc is not Ready/Failed.
- Select a doc → clause outline (expanders by path; superseded clauses get a "superseded by D4:1 on 2026-01-01" chip)
  + page viewer reused from the evidence component.

## Conflicts page

- Filters: subject, type, "in force at [date]" (default today).
- One card per subject with all sides side by side (same component as the answer card's disagreement block) + explanation + severity.

## Amendments page

- Per version key with > 1 version: a timeline card (same component as "Rule in force") + "View as of" date control → in-force text.
- Unresolved edges list: "Amends X, which is not in the library."

## Copy and empty states

- Empty chat: three example question buttons (one per must-have: a conflict, an amendment, an unanswerable question).
- Model offline: the chat input stays enabled, but submitting shows "The model is warming up (≈ 2–3 min). Your documents and the Conflicts/Amendments pages are still available."

## Implementation notes (M7)

- Layout: `app/main.py` (page config, sidebar, `st.navigation`), `app/state.py` (cached DB connection, model client, retriever, model status), `app/i18n.py`, `app/components/{sidebar,answer_card,evidence,cards}.py`, `app/pages/{chat,documents,conflicts,amendments}.py`, `core/render/highlight.py` (page PNG + rectangles; `pdf_path` finds the original PDF from the latest ingest job, else `uploads/`, else `corpus/pdfs/`).
- Active chat lives in `st.session_state.chat_id` and `?chat=` so a reload keeps it; per-chat as-of date and language are stored with `db.update_chat_settings`. The as-of date passed to `assemble.answer` is the chat's date (a date stated inside the question still wins, per `plan.effective_as_of`).
- The Conflicts page lists conflicts in force at a chosen date (`disagree.active_conflict_ids`) with the same card component as the answer card; the Amendments page uses `versions.chains` and `versions.clause_in_force` for the timeline and "view as of".
- The model-offline case is handled before calling `answer()`: the chat shows the warming-up message and nothing is persisted.
- Citation pills are `st.button`s (`D1 · p.4`) that set `st.session_state.evidence`; the evidence column highlights the span's boxes (yellow, orange for OCR) and can page through the document.
- Testing: `tests/test_app.py` uses Streamlit `AppTest` (headless) on an ingested temp corpus: all four pages render, the chat page shows the conflict card and citation pills, the Conflicts and Amendments pages show C1/C2 and the D1 -> D3 -> D4 timeline, new/switch/delete chat keep separate histories. With `st.navigation`, AppTest re-runs only the page script after a click, so sidebar interactions are tested through a small script that renders `sidebar.render` alone.
- Calculation card and Hindi labels are implemented in the UI but their data arrives with M9 / M10.
