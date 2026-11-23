# Decisions (ADR log)

Append new entries at the bottom. Format: ID · date · decision · why · consequences. Never delete; supersede instead.

**ADR-001 · 2026-11-22 · Open-source models only, served by ourselves.** (LLM serving superseded by ADR-011)
LLM `Qwen/Qwen2.5-7B-Instruct-AWQ` on vLLM. Embeddings `BAAI/bge-m3`. Reranker `BAAI/bge-reranker-v2-m3`.
NLI verifier `vectara/hallucination_evaluation_model` (HHEM-2.1-open).
Why: the problem statement forbids paid AI APIs; documents are confidential. Qwen2.5-7B has reliable JSON output and
reasonable Hindi, and the AWQ build fits a 16 GB T4 next to the small models.
Fallback: Ollama `qwen2.5:7b-instruct-q4_K_M` behind the same OpenAI-compatible client.

**ADR-002 · 2026-11-22 · Colab is not a serving host.**
Colab's FAQ disallows web services and connecting to remote proxies on all runtimes, including paid.
Colab compute units are used for development and batch pre-ingest of the demo corpus only, with the model
service on localhost inside the notebook.

**ADR-003 · 2026-11-22 · Modal hosts both the GPU model service and the Streamlit UI.**
Supersedes the PRD's "UI on a Hugging Face Space". Why: one platform and one account; a `modal.Volume` gives persistent
uploads and chats; T4 is about $0.59/h. Keep `min_containers=1` on both only during the judging window.
Fallback: HF Space (Docker, CPU) for the UI.
Caveat: SQLite on a Modal Volume. Run a single UI container and call `volume.commit()` after writes (debounced, at most every 5 s).

**ADR-004 · 2026-11-22 · Three-level data model (clause / span / fact).** See data-model.md.

**ADR-005 · 2026-11-22 · Amendments and contradictions are computed at ingest.**
Queries do version lookups and a cheap re-check of facts among the retrieved clauses only.
Incremental: a new document re-runs amendment resolution and the conflict scan only for the subjects and version keys it touches.

**ADR-006 · 2026-11-22 · Extract-then-compose citations.**
The LLM cites span_ids; the UI renders stored span text. Quotes can't be misquoted by design.

**ADR-007 · 2026-11-22 · Streamlit UI** instead of React. Why: 24-hour budget, Python only. Highlights are drawn onto
PyMuPDF-rendered page PNGs, so no PDF.js is needed.

**ADR-008 · 2026-11-22 · PyMuPDF for parsing (not Docling)** for speed and exact word coordinates. `page.find_tables()` for tables.
Docling is a fallback only if table extraction fails on real user PDFs.

**ADR-009 · 2026-11-22 · Faithfulness definition.**
`passed / drafted × 100`, where passed = spans_valid ∧ numbers_ok ∧ quote_ok ∧ version_ok ∧ hhem ≥ τ.
Contradicted claims count as passed, because they are backed by a quote; they are shown in the disagreement card, not the body.
The answer body is 100% verified by construction; the score shows how much of the draft was blocked.

**ADR-010 · 2026-11-22 · Fictional demo corpus** (Kestrel Finance Ltd., Financial Conduct Board) with planted
conflicts, an amendment chain and a scanned FAQ, so every test has ground truth.

**ADR-011 · 2026-11-23 · Ollama serves the LLM in every environment (supersedes vLLM in ADR-001).**
Model `qwen2.5:7b-instruct` (Q4_K_M, Ollama tag) with JSON-schema structured output (`format`), `num_ctx` 8192, temperature 0.
Why: the developer already runs Ollama with a local GPU. The same backend in dev, Colab and Modal means identical
behaviour and prompts, and no vLLM version or T4 compatibility risk. Throughput is enough for a 6-document corpus.
The app talks only to our model service (`/llm/chat`), so swapping in vLLM later is a model-service-only change.

**ADR-012 · 2026-11-23 · Dev machine uses `qwen3.5:4b` (Ollama) with thinking disabled; dependency pins.**
Dev box has an RTX 4050 6 GB and already had `qwen3.5:4b` pulled, so `.env` sets `LLM_MODEL=qwen3.5:4b`, `AUX_DEVICE=cpu`.
The project default in `core/config.py` stays `qwen2.5:7b-instruct` (prod/Modal and the release eval). It is still an open-source model served by us (constraint 1 holds).
`llm_backend.py` always sends `"think": false`: Qwen3-series models think by default, which adds latency and breaks determinism and structured output.
Pins in `requirements-service.txt`: `transformers>=4.44,<5` (FlagEmbedding imports a module removed in v5) and `datasets<4` (newer needs a huggingface_hub that transformers 4.x forbids).
CPU torch installed from the pytorch CPU index in the dev venv. Consequences: prompts tuned on 4b must be re-checked with 7b before the M8 release eval (eval gates apply to the deployed model); smoke timings on dev are CPU-bound.

**ADR-013 · 2026-11-23 · Build the demo corpus first, guard against overfitting with a held-out set.**
The corpus and qa.yaml are ground truth for the M2-M6 done-when checks, so they are built in M1 (not after). Overfitting risk lives in code and prompts, so: no demo IDs, names or amounts in `core/` or prompts (unit tests use small synthetic fixtures); a held-out set of 2-3 differently formatted PDFs + Q&A is written but not developed against, and is run at M5, M6 and M8. A drop versus the demo corpus signals overfitting. Consequences: extra corpus work before M8; `/check-constraints` should grep `core/` for demo doc IDs.

**ADR-014 · 2026-11-23 · M4 answering decisions: HHEM threshold, relevance by prompt, normaliser pulled forward.**
1. `HHEM_THRESHOLD` stays **0.5**. Sweep over the 22 M4 items (single, multi, table, unanswerable; draft prompt v3, `qwen3.5:4b`): items passing are 22/22 for 0.2-0.5 and 21/22 for 0.6-0.8; the lowest legitimate claim scored 0.54, all others 0.89-0.99. Nothing in this set is separated by HHEM (the numbers/quote/span checks and the prompt do the blocking), so the sweep cannot justify moving it; re-run `scripts/eval.py --hhem-sweep` on the 7b release eval and on the held-out set (ADR-013).
2. Off-topic claims (answering a different question from the same evidence) are controlled by the draft prompt (v3 rules 2, 6, 11, 12), **not** by a relevance score. Measured on real answers: `/rerank` scores of correct multi-part claims (0.11) fall below wrong-topic claims (0.69), so a reranker gate would block good answers. Prompt iteration v1->v3 took the 22 M4 items from 14/22 to 22/22 (v1 invented "From X to Y" periods from the as-of date and header; v2 still answered adjacent topics; v3 added a scope-check rule). Risk: the prompt is tuned on 4b and on this corpus; the held-out set must confirm it.
3. `core/normalize.py` (planned for M5) was built in M4 because verify check (b) needs `parse_value`/number tokens; M5 reuses it for facts. Number words in the *source* (six) count as numbers; in the *claim* they do not.
4. Gate detail: the "No verified evidence for: <sub-question>" missing items are only generated when nothing was verified; with some supported claims, only the model's own `missing` list is used (no claim-to-sub-question mapping exists to do better).
5. Span ids copied with brackets (`[D1:6.1#s1]`) are normalised before check (a); the id must still be in the evidence pack.

**ADR-015 · 2026-11-23 · M5 decisions: two extraction calls, code-side recovery/validation, global version rebuild, planner date guard.**
1. Fact extraction and amendment-directive extraction are **separate LLM calls** (amendments.md §1 said one call): a 4B model returned empty/incomplete directives when asked for both. Facts are batched by 6 clauses; directives are requested only for amendment documents or clauses matching `AMEND_RX`.
2. The LLM proposes, code decides. Facts are dropped unless `value_raw` is in the span text and `parse_value` succeeds. Directives are dropped unless their evidence span exists and states the target clause (or supersession wording). A missing `target_path` is recovered from "Clause N" in the evidence only when exactly one distinct reference is present. This was needed on real output: `qwen3.5:4b` returned `target_path: null` for both substitutions.
3. `AMEND_RX` from the spec never matched "supersession"; fixed. Target resolution additionally requires the target clause to exist in the candidate document and prefers the longer matched name on ties (an amendment's title contains the agreement's reference number, and the schedule lists it as an alias).
4. `versions.rebuild_all` recomputes every timeline after each document's post-stages instead of per touched key. Corpus is small; ingest order independence is tested for three orders.
5. Planner guard (`plan.sanitise`): an `as_of_override` is dropped unless the question itself contains a year or month name. Measured failure: the 4B planner invented `2025-08-19` for "today" and the answer cited the superseded 3% rule.
6. Draft prompt v3 -> v6 (rules 13-15: name amendments with what they do and their date; stay close to the evidence wording; do not list an old value as missing when asked whether it still applies). Verification, not the prompt, is what guarantees safety: in every run unsupported displayed = 0.
7. Known flaky item: q32 ("interest rate for fixed-rate loans") sometimes yields a partial answer (a prepayment-charge claim plus a `missing` entry) instead of an abstention with the 4B model; abstention recall 5/6 to 6/6 across runs. Re-measure with the 7B model and the held-out set before tuning further (ADR-013).

**ADR-016 · 2026-11-23 · M6 decisions: conflict partners join the evidence; full re-scan; query-time logic in `disagree.py`.**
1. `disagree.add_partners` adds the spans of the clause on the other side of any conflict in effect to the evidence pack. Contradictions are computed at ingest (constraint 5), so surfacing the other side is a lookup, not a corpus scan. It fixed q27, where retrieval alone never finds `D2:table1.row2`. Risk: a conflicting partner can pull an off-topic claim into an answer; the draft prompt (rule 2) and `asserts_disputed` (only claims that state a disputed value become `contradicted`) limit this, and q28/q05 (negative controls) pass.
2. The ingest scan re-scans all subjects after every document (spec: only changed subjects). Version intervals of old facts change when a new amendment arrives, ids are deterministic, and the corpus is small.
3. Check (f) lives in `core/answer/disagree.py`, called by `assemble` after `verify_claims`, to keep `verify.py` free of DB access.
4. C3 is verified only with synthetic facts until M9 (the scanned FAQ). The milestone's "exactly C1, C2, C3 are stored" is therefore met live for C1, C2 and by unit test for C3.

**ADR-017 · 2026-11-23 · React + FastAPI UI replaces Streamlit after parity; plain-language presentation rules.**
Streamlit cannot give a resizable side panel, inline citation chips, stage progress or a polished sidebar, and its output was hard to understand (jargon, raw ids, repeated facts). We add `api/` (FastAPI over `core/`; no business logic) and `web/` (Vite, React, TypeScript, Tailwind). Streamlit (`app/`) stays until parity, then is removed. The M8 deploy targets one container serving the API and `web/dist` instead of Streamlit (architecture.md §Deployment to be updated at M8). Presentation rules (design/ui-react.md §1-§3): plain words, human names instead of ids, each fact shown once, technical checks behind a "How we checked" disclosure, abstention styled neutral, no token streaming (constraint 2: nothing is shown before verification; a stage stepper is shown instead). Demo example questions live in `api/examples.py` (app layer), not in `core/` or prompts (ADR-013).

**ADR-018 · 2026-11-23 · Streamlit UI removed; OCR (M9) is done before deploy (M8).**
The user approved the React UI, so `app/`, `tests/test_app.py` and the `streamlit` requirement are deleted. M9 (OCR + calculator) now runs before M8 so the deployed app is feature-complete for P0+P1; the M8 deploy image needs Tesseract (+ `hin`) and the built `web/dist`.

**ADR-019 · 2026-11-23 · M9 choices: one-pass Tesseract OCR, repairs of known confusions, calculator sourcing rules.**
1. OCR uses `pytesseract.image_to_data` (words + confidence in one pass) instead of PyMuPDF's OCR textpage; deskew is skipped. `ocr_conf` is 0–100.
2. Two narrow, documented repairs of Tesseract errors are applied (capital I; ₹ read as 2 before lakh/crore, only at low confidence). A wrong amount shown as verified is worse than a clumsy rule; the rest is left as read.
3. `normalize_text` replaced `rs`/`inr` only as whole words. The old substring rule turned "years " into "yea₹", which silently dropped every age-range fact and so hid conflict C3 (this affected digital documents too).
4. `parse_value` reads "not less than A … not more than B" as a range. Extract prompt v2: an age limit of who may borrow is always subject "borrower age".
5. Calculator: inputs only from the question (verified against its literal numbers) or from verified claims; conflicting document values are all shown with no single result.

**ADR-020 · 2026-11-23 · Modal deployment decisions and held-out fixes.**
1. The deployed LLM is `qwen3.5:4b` (what everything was tuned on). Comparison with `qwen2.5:7b-instruct` is deferred until after analysis.
2. The app is one container with SQLite on its LOCAL disk. The Volume `docai-data` holds `/seed` (initial bundle) and `/state` (synced every 45 s when something changed, and at shutdown, via the SQLite backup API plus `volume.commit()`). SQLite WAL on a network volume is unsafe, and Modal volumes need explicit commits.
3. Modal answers a cold start with a 303; `ModelClient` follows redirects. The first start of the GPU app needs minutes (GPU wait + model load); `scripts/smoke.py` now waits for `/health`.
4. GPU-only bug found: HHEM returns a CUDA tensor; `AuxModels.nli` moves it to the CPU first.
5. Prompts and `.md` files must be shipped explicitly (`add_local_dir`): Modal's Python source mount only carries `.py` files.
6. Held-out set (`corpus/heldout.py`, `tests/heldout.yaml`, ids `H1..H3`): it exposed three generic gaps, fixed once and not tuned further: "Section 1.01 Text" numbering (segment), amendments phrased "is revised to" (extract_amendments v3), duplicate directives (de-duplicated at ingest). Because it was used for diagnosis it is no longer a clean held-out set; a new one is needed for any further generalisation claim.
7. Eval gained the missing P0 "quote exactness" gate (`scripts/quote_check.py`): stored span text must equal the PDF words in the span's boxes (OCR spans are skipped).
8. Draft prompt v8 fixes q20 ("not listing the status of the older rule as missing"); the unanswerable item q33 stays flaky on the 4B model (it sometimes answers a credit-card question with loan fees), so abstention is 5/6 or 6/6 between runs.

**ADR-021 · 2026-11-23 · Access gate and spend limits for the public app.**
Anyone with the URL (or an open tab polling `/api/health`) could wake the paid GPU. `api/access.py`: a shared access code (env `ACCESS_CODE`, Modal secret `docai-ui`; unset = open, for local dev and tests) checked by a dependency on every `/api` router except `/api/login` and `/api/session`; the cookie holds an HMAC of the code (HttpOnly, SameSite=Lax, 7 days), so changing the code signs everyone out. Limits (in memory, valid because the app is one container): 30 questions per visitor per hour, 300 per day overall, 10 uploaded files per visitor per hour, 8 wrong codes per 10 minutes, 15 MB per upload. The visitor is the first `X-Forwarded-For` entry. The React `AccessGate` shows a login card only when the server requires a code. The code lives in the git-ignored local file `.access_code` and in the secret, never in `.env` (that would close the local API and its tests).

**ADR-022 · 2026-11-23 · Passive health on Modal: the status check must not wake the GPU.**
The UI polls `/api/health` every 15 s and the route called the model service, so any open tab kept the paid GPU awake. With `HEALTH_PASSIVE=1` (set in `deploy/modal_app_ui.py`) `/api/health` answers from `deps.MODEL_STATUS` (last real model call: `ready` for `MODEL_IDLE_S`=840 s, `offline` for 60 s after a failure, else `asleep`) and never contacts the model. A question calls `deps.wake_model()` first: it polls the model's `/health` (up to `MODEL_WAKE_DEADLINE_S`=420 s) and the UI shows the stage "Waking the model". Local development keeps the active health check. `asleep` does not block the composer.

**ADR-023 · 2026-11-23 · Per-chat document scope and Markdown export (M10, part 1).**
A chat can be limited to chosen documents (`chats.doc_scope`, set with `PATCH /api/chats/{id}` `{doc_scope: [...]}`; `[]` clears it; unknown ids are a 422). Scope is applied in four places so nothing outside it can be cited: retrieval (already filtered), `evidence.restrict` on the pack (amendment versions can live in other documents, so a scoped rule may have no in-force text and the answer abstains: honest), conflict partners, and conflict lookups (`conflicts_in_effect`: a conflict counts only when both sides are in scope). Export: `GET /api/chats/{id}/export` returns Markdown built from the stored answers (`api/export.py`): questions, status, statements with citation numbers, calculation, disagreements, rule history, missing items and a Sources list with the stored quotes. No model is involved. UI: a "documents" menu in the composer and an Export link in the chat header.

**ADR-024 · 2026-11-23 · Workspaces: documents and chats are grouped, and nothing crosses a group.**
The app had one global document pool: every chat searched everything, and the Conflicts/Amendments pages and ingest-time scans compared documents of unrelated matters. Chosen: a `workspace` (UI word; code `workspace_id`) owns documents and chats, modelled on ChatGPT/Claude projects. (1) `documents.workspace_id` and `chats.workspace_id`; `sha256` is unique per workspace so the same PDF can live in two; uploads get a workspace-dependent id. (2) A chat's allowed documents are its workspace's, narrowed by the existing per-chat picker (ADR-023, kept); an empty list is a hard boundary, not "everything" (`is None` checks in retrieval, evidence and conflict lookups). (3) Ingest isolates conflict scans and amendment-target resolution per workspace; the subject registry stays global (vocabulary, not evidence) and so does the search index (filtered at query time). (4) Old databases migrate in place: everything goes into the default workspace "Kestrel demo", which cannot be deleted through the API; trusted local ingest and tests use it. (5) Workspaces are an organisation boundary, not a security boundary (no accounts; ADR-021's single code still gates the app). (6) Blocked claims keep model-written span ids, so `enrich_answer` drops ids outside the chat's workspace. (7) Deleting a workspace is allowed (not while documents are being ingested); deleting a single document is deferred because it needs a re-scan (design/workspaces.md §7). Details, API and change log: design/workspaces.md.

**ADR-025 · 2026-11-23 · Hindi (M10 part 2): translate at the edges, never inside the verified pipeline (branch `feature-testing`).**
1. The pipeline stays English: HHEM, the number/quote checks and the documents are English. Hindi is a thin layer at both ends, so no check is weakened.
2. Question -> English costs **no extra model call**: the planner (prompt v2) returns `question_en`. English questions are never rewritten by the model (`plan.english_question`); Devanagari digits are normalised in code (`i18n.to_ascii_digits`). Retrieval searches the English question and the Hindi original (bge-m3 is cross-lingual).
3. Answer -> Hindi is one batched call after the gate (`core/answer/translate.py`, prompt `translate` v1), only for shown claims and missing items. Each translation is kept only if it contains Devanagari and `i18n.same_numbers` holds (the number guard); otherwise the English sentence is shown. The Hindi sits beside the verified English (`VerifiedClaim.text_local`, `AnswerJSON.missing_local`); it never replaces it.
4. Everything fixed is a dictionary, not a model call: abstain text, calculator labels/formulas (`i18n.HI_CALC`), UI strings (`web/src/lib/i18n.ts`, English sentence as key, no library). Quotes and document names are never translated.
5. Answer language = chat `language` (`en`/`hi`) else the question's language. The UI language toggle (EN/हि, localStorage `docai.lang`) sets the chat to `hi` when asking; English UI uses `auto`.
6. Limits: Hindi *documents* are only supported through OCR (HHEM is English-only, so Hindi source text is not entailment-checked). Not yet translated in the UI: Library, Conflicts, Amendments, Workspaces, Sources panel and AccessGate pages (they fall back to English). Not run: no tests, eval or browser check has been done for this change.
