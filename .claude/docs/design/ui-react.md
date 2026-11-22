# Design: React UI + HTTP API (replaces the Streamlit UI after parity)

Code: `api/` (FastAPI, thin wrapper over `core/`), `web/` (Vite + React + TypeScript + Tailwind).
Decision record: ADR-017. The UI holds no business logic; everything it shows comes from `core/` through the API.

## 1. Why, and what must be better than the Streamlit UI

The Streamlit UI was hard to understand. The causes, and the rules that fix them:

| Problem in Streamlit UI | Rule for the React UI |
|---|---|
| Jargon: "Faithfulness 100%", "drafted claims", "contradicted", "blocked claims", `numbers_ok`, `hhem` | Plain words (§3). Technical detail lives behind one "How we checked this" disclosure, never on the main surface. |
| Raw ids everywhere: `D2:table1.row2`, `D1 · p.4` | Human names: "Schedule of Charges, row: Late payment fee, page 1". Ids only in tooltips / the audit view. |
| The same fact repeated: claim, quote expander, disagreement card, explanation line | One idea, one place: the answer states it once; sources open in the side panel on demand. |
| Disagreement shown as three cards plus a long run-on sentence | A comparison table ("Document / What it says / Page") and one plain sentence above it. |
| Timeline with dates "2024-01-15 → 2025-04-01 · original" | "Until 31 Mar 2025: 4% (Loan Agreement)", "From 1 Apr 2025: 3% (Amendment No. 1)", "From 1 Jan 2026: nil (Amendment No. 2) <- applies today". |
| Evidence column always visible, mostly empty | Right panel opens on demand (citation click or "Sources" button). |

## 2. Layout (desktop; tablet/mobile collapse panels into drawers / bottom sheets)

```
┌────────────┬────────────────────────────────────────┬─────────────────────┐
│ sidebar    │ top bar: chat title · as-of date · ⋯   │ right panel (opens) │
│ (collapsi- │ message column (max ~720px, centred)  │ Sources | Page |    │
│  ble)      │ composer (sticky)                      │ How we checked      │
└────────────┴────────────────────────────────────────┴─────────────────────┘
```

- **Sidebar:** logo, "New chat", search, chats grouped Today / Yesterday / Previous 7 days / Older, rename + delete per chat,
  navigation (Library, Conflicts, Amendments), model status. Collapses to an icon rail; state persists in `localStorage`.
- **Chat:** empty state with 3-4 example questions; user bubble; assistant answer card; composer with the as-of date chip.
- **Right panel:** resizable, pushes the chat narrower (does not overlay on desktop). Tabs: **Sources** (numbered list of what the
  answer cites), **Page** (the PDF page image with the quote highlighted, page navigation), **How we checked** (per-statement checks).
  Opens when a citation chip is clicked or "Sources (N)" is pressed; closes with Esc or the close button.

## 3. Plain-language copy (single source of truth: `web/src/lib/plain.ts`)

| Internal | Shown to the user |
|---|---|
| `answered` | "Answer found" (green) |
| `partial` | "Partly answered" (amber) + what is missing |
| `conflict` | "Documents disagree" (orange) |
| `abstained` | "No proof found" (neutral slate, never red) + "I couldn't find proof for this in your documents." |
| faithfulness 100% | "All 2 statements were checked against the documents" / "2 of 3 statements were verified; 1 was left out" |
| claim `supported` | statement + citation chips `[1]`; a small "Verified" tick with a tooltip "Every number and quote was matched to the source text" |
| blocked claim + reason | "Left out because we couldn't verify it" + plain reason (§3.1) |
| `in_force` / `superseded` / `future` | "Applies today" / "Replaced on 1 Jan 2026" / "Starts on 1 Nov 2025" |
| chain | "How this rule changed" |
| as-of date | "Showing the rules as they applied on <date>" |

### 3.1 Reasons (map `VerifiedClaim.reason`)
- "<values> not found in cited text" -> "The figure <values> does not appear in the cited text."
- "quoted text doesn't match the source" -> "A quotation did not match the document."
- "cites evidence that wasn't retrieved" -> "It pointed at text that was not part of the evidence."
- "cites a superseded clause" -> "It relied on a rule that has since been replaced."
- "not entailed by the cited text (0.21)" -> "The cited text does not clearly support this statement."
- "could not be checked (model unavailable)" -> "The checking model was unavailable."

### 3.2 Document names
`display_name`: title-cased title (the corpus has all-caps titles); amendments are shortened to "Amendment No. 1"; circulars show
"Circular <ref no>". A secondary line shows type and reference ("Agreement · KF/PLA/2024"). Clause labels: "Clause 8.1",
"Table row: Late payment fee", "Paragraph 1". Dates: "1 Jan 2026". Money keeps the source formatting.

### 3.3 Disagreement sentence (built in the UI from structured sides, no LLM)
"The documents give different answers about **late payment fee**." Then a table, one row per document: *what it says* is
`"₹500 per instalment"` for an exact value, `"at most ₹600 per instalment"` for a cap (op `max`), `"at least ..."` for a minimum.

## 4. Answer card anatomy (top to bottom)
1. Status chip + one line ("Showing the rules as they applied on 23 Nov 2026").
2. The statements: each a short paragraph with citation chips; hovering a chip shows the document, clause, page and the exact quote.
3. Disagreement block (sentence + comparison table) when present.
4. "How this rule changed" stepper when present; the step that applies on the as-of date is highlighted.
5. Calculation card when present (formula, inputs with sources, steps, result).
6. "What's missing" list when present.
7. Footer: "Sources (N)" button (opens the panel), "How we checked" disclosure (counts, left-out statements with reasons), copy / download JSON.

No token streaming: nothing may be shown before verification (constraint 2). While working, a stage stepper shows
Planning, Finding passages, Writing, Checking, Comparing documents (SSE `stage` events).

## 5. API (`/api`, JSON; SSE for asking)

| Method + path | Purpose |
|---|---|
| `GET /api/health` | `{state: ready|warming|offline}` |
| `GET /api/examples` | example questions |
| `GET/POST /api/chats`, `PATCH/DELETE /api/chats/{id}` | chat CRUD (title, as_of_date, language) |
| `GET /api/chats/{id}/messages` | messages; assistant ones carry the enriched answer |
| `POST /api/chats/{id}/ask` | SSE: `stage` events then one `answer` (or `error`); answers are serialised (one at a time) |
| `GET /api/documents`, `POST /api/documents` | list with ingest status; multipart upload |
| `GET /api/documents/{id}/outline` | clauses with "replaced by ..." info |
| `GET /api/documents/{id}/pages/{n}/image` | PNG of a page (no highlights; the UI overlays boxes) |
| `GET /api/spans/{span_id}` | one source (same shape as the answer's `sources` entries) |
| `GET /api/conflicts?as_of=` | disagreement cards in force on a date |
| `GET /api/amendments?as_of=` | version timelines + unresolved amendments |

**Enriched answer:** the stored `AnswerJSON` plus `sources` (`span_id` -> `{n, doc_id, doc_name, doc_sub, clause_label, page, page_width,
page_height, bboxes, text, row, ocr, status, effective}`) and `citations` (span ids in citation order). Citation numbers are stable per answer.

## 6. Stack and structure
Vite, React 18, TypeScript, Tailwind 3, Radix primitives (tooltip, popover, dropdown, dialog, tabs), TanStack Query, lucide icons,
Inter (self-hosted). Highlights are CSS overlays on the page image using the span's boxes (PDF points scaled by image width).
Dev: Vite proxies `/api` to FastAPI (:8000). Prod: FastAPI serves `web/dist`.

## 7. Phases
1. API layer + tests. 2. Scaffold, design system, sidebar, chat shell. 3. Answer card, sources panel, page viewer.
4. Library, Conflicts, Amendments. 5. Polish (dark mode, responsive, a11y, empty/error states) and browser checks.

## Tests
API: pytest + FastAPI `TestClient` on an ingested temp corpus (CRUD, SSE ask with a scripted model, enrichment, page image, conflicts,
amendments, upload). Web: Vitest + Testing Library for `plain.ts`, formatting and the main components; manual browser checks
with screenshots at 1440px, 1024px and 390px, light and dark.

## Implementation notes (built 2026-11-23)

- API: `api/main.py` (app factory, serves `web/dist` and falls back to `index.html` for client routes), `api/deps.py` (per-request SQLite connection, one model client,
  one retriever, an answer lock), `api/serialize.py` (display names, plain clause labels, `source_info`, `enrich_answer`), `api/routes/{chats,documents,knowledge}.py`.
  Answers run on a worker thread and are streamed as SSE `stage` events followed by one `answer` (or `error`). `enrich_answer` also gives every disagreement side its
  readable name, clause label and page geometry, so the UI never shows ids or ALL-CAPS titles.
- Web: `web/src/lib/plain.ts` is the only place with user-facing wording (tested); `chat/{AnswerCard,blocks,CitationChip,StageProgress,Composer,ChatPage}.tsx`,
  `panel/{SourcesPanel,PageViewer}.tsx`, `layout/{Sidebar,AppShell,PageShell}.tsx`, `pages/{Library,Conflicts,Amendments}.tsx`, `state/ui.tsx` (sidebar, theme, panel).
- Facts already shown in a disagreement table are not repeated as separate statements; the comparison table is the single place the figures appear.
- The date is the user's local calendar day (UTC "today" was off by one near midnight and made the date chip look changed).
- Dev: `uvicorn api.main:app --port 8000` and `cd web && npm run dev` (http://localhost:5173). One process: `npm run build`, then open http://localhost:8000.
- Gotcha: the Bash tool turns `\\b` into a backspace inside heredocs; write regexes with the Write/Edit tools (ruff and tsc do not always catch it in TypeScript).
