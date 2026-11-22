# Progress log

Append one entry per session (newest at the bottom). Keep entries short: what was done, current state of eval gates,
what's next, and gotchas the next session must know (version pins, API quirks, thresholds chosen).

## 2026-11-22 — Planning complete
- Spec, architecture, data model, design docs, demo corpus spec, eval spec and implementation plan written in `.claude/docs/`.
- `tests/qa.yaml` (40 items) written.
- Next: M0 (scaffold + model service + smoke test).
- 2026-11-23: switched LLM serving to Ollama everywhere (ADR-011); added runbook.md. Modal account + `docai-token` secret needed only at M8.

## 2026-11-23 — M0 scaffold (DONE)
- Done: repo layout, requirements*, `core/{config,models,db}.py`, `core/llm/client.py` (chat, chat_json w/ 1 retry, embed, rerank, nli, health, `ModelUnavailable`),
  `model_service/{server,aux_models,llm_backend,local,modal_app}.py`, `scripts/smoke.py`. `pytest -q` 8 passed (db + service/client with stub backends); `ruff` clean.
- NOT yet done (M0 done-when): `python scripts/smoke.py` against the real service. Needs `pip install -r requirements-service.txt` (torch, FlagEmbedding),
  an Ollama LLM pull, and first-use downloads of bge-m3, bge-reranker-v2-m3, HHEM. `modal_app.py` is untested (modal not installed; M8).
- Machine: RTX 4050 6 GB -> use `AUX_DEVICE=cpu` and `LLM_MODEL=qwen2.5:3b-instruct` (runbook §1.1). Only `qwen3.5:4b` is currently pulled; Python 3.13 is default (3.11 also installed).
- Gotchas: model service `/health` reports llm=ready only when `LLM_MODEL` is in Ollama tags. Bash heredocs choke on non-ASCII (§) on this Windows box; use the Write tool.
- Next: finish M0 smoke, then M1.
- Update (later same session): M0 COMPLETE. `scripts/smoke.py` passes against the live service (health, chat_json, embed, rerank, nli) with `LLM_MODEL=qwen3.5:4b`, `AUX_DEVICE=cpu`; `pytest -q` and `ruff` clean.
- Deviations (ADR-012): dev LLM is qwen3.5:4b with `think:false` sent by the backend; `transformers<5` and `datasets<4` pinned in requirements-service.txt. Defaults in config.py unchanged.
- Gotchas: a model service process may still be running on :8080 (stop it before restarting); 4b output quality must be re-validated on 7b before M8 eval; `.venv/`, `.env`, `svc.log` are local-only.
- Next: M1 (demo corpus + test set): read demo-corpus.md and eval.md, build `corpus/generate.py`.

## 2026-11-23 — M1 demo corpus + test set (DONE)
- Done: `corpus/generate.py` (+ `corpus/texts.py` exact text, `corpus/fonts.py` rupee-safe font finder) builds D1-D6 into `corpus/pdfs/` (git-ignored; regenerate any time, output is deterministic apart from PDF metadata). `scripts/eval.py` skeleton loads `tests/qa.yaml` (fills per-item `as_of`, supports `--only/--type/--skip-types`), scoring comes in M3/M4.
- Gate: `generate.py` asserts D1 = 6 pages, rupee extractable in D1/D2, 7.2 starts p.3 and continues p.4, footers on every digital page, D6 has no text layer. `tests/test_corpus.py` repeats these and checks qa.yaml (40 items, 6 abstain). `pytest -q` 15 passed; ruff clean.
- Font: Segoe UI on this Windows box (DejaVu/Noto looked up first on Linux/Colab). If no candidate has U+20B9 generation fails loudly rather than writing "Rs.".
- Gotchas: use `import pymupdf` (the `fitz` alias warns). Windows consoles are cp1252: scripts that print the rupee sign must `sys.stdout.reconfigure(encoding="utf-8")`. `--skip-types scanned,hindi` leaves 37 of 40 items.
- Agreed (not yet in plan): build a held-out set of 2-3 differently formatted PDFs + Q&A before the M8 eval to detect overfitting to the demo corpus; keep demo IDs/strings out of `core/` and prompts.
- Next: M2 (ingest: register, parse, segment, index). Read design/ingest.md and design/retrieval.md §index first.

## 2026-11-23 — M2 ingest: register, parse, segment, index (DONE)
- Done: `core/ingest/{register,parse,spans,segment,store,pipeline}.py`, `core/retrieval/index.py`, `core/llm/prompt_loader.py` + `prompts/register_meta.md` (v1), `scripts/ingest_corpus.py`. Pipeline has a SQLite job queue + worker thread; `POST_STAGES` is the hook where M5/M6 add facts, amendments, conflicts.
- Gate: `pytest -q` 59 passed (offline: fake embeddings, no model service), ruff clean. `python scripts/ingest_corpus.py --reset` against the live service: D1-D5 Ready in ~44 s, total 49.5 s (limit 3 min). D1 27 clauses, D2 9 (5 data rows), D3 3, D4 3, D5 6; 7.2 spans p3-4; D6 parked "needs OCR (M9)".
- Real LLM metadata (qwen3.5:4b) got titles, ref numbers and effective dates right for all five digital docs (D5 title came out as the subject line, harmless).
- Deviations from ingest.md are listed at the bottom of design/ingest.md ("Implementation notes (M2)").
- Gotchas: `import pymupdf` not `fitz`; PyMuPDF `find_tables().extract()` drops spaces, so rebuild cells from words; `get_text("words")` boxes are font-size tall (line pitch 15 vs box 10.5) so paragraph gaps are measured relative to font size; clause kinds are heuristic, do not rely on them for logic; the preamble paragraphs (`D1:p1.1`...) exist as clauses and will be retrieved, M5 must not treat them as rules.
- Next: M3 retrieval (plan, hybrid search, RRF, rerank, evidence pack; expansion stub). Read design/retrieval.md; `scripts/eval.py --retrieval-only` must reach recall@8 >= 90% (needs the query planner prompt and scoring in eval.py).

## 2026-11-23 — M3 retrieval (DONE)
- Done: `core/answer/plan.py` (planner + `sanitise` + `search_queries`), `core/retrieval/{bm25,hybrid,expand,evidence}.py`, `prompts/plan.md` (v1), `scripts/eval_retrieval.py`, `scripts/eval.py --retrieval-only`.
  Hybrid = dense + BM25 -> RRF(k=60) -> rerank top 30 -> keep 8 per query, union over queries (best score per window). Evidence pack = whole in-force clauses, capped at 40 spans / 3500 tokens; other versions go to `context_spans`.
- Gate: clause recall@8 37/39 = 94.9% (>= 90%), item recall 93.5%. Misses: q26 `D6:p1.q1` (scanned, M9) and q27 `D2:table1.row2` (sub-question dropped the schedule-of-charges side; the original question is now also searched but row2 still ranks outside the top 8 -> revisit at M6 if the conflict item needs it).
- Deviations (see design/retrieval.md "Implementation notes (M3)"): original question also searched; rerank sent in chunks of 10 (`RERANK_CHUNK`) because a CPU service timed out on 30 passages; `expand.py` already implements real status logic; plan cache for eval.
- Gotchas: always use `.venv/Scripts/python.exe` (global Python lacks pymupdf); never run two evals at once (they share the CPU model service and timed out); redirect eval output to a file, piping buffers it; planner latency ~20-100 s/item on this CPU box.

## 2026-11-23 — M4 answering core (DONE)
- Done: `core/normalize.py`, `core/answer/{draft,verify,gate,assemble}.py`, `prompts/draft.md` (v3), `AnswerJSON`, `scripts/eval_answers.py` (per-item scoring, independent re-check, `--hhem-sweep`), `tests/test_verify.py`. Full suite 111 passed; ruff clean.
- Gate: 22/22 M4 items on `qwen3.5:4b`; 0 unsupported displayed; abstention 6/6; false abstain 0/16; HHEM 0.5 kept (ADR-014).
- Gotchas: v1 prompt got 14/22 (invented "From X to Y" periods; adjacent-topic answers; spurious `missing`) -> v3 rules; reranker cannot judge claim relevance; unsupported-displayed re-check must include the doc header.
- Next: M5 facts, subjects, amendments, versions (reuse `core/normalize.py`; chains and real `version_ok`).

## 2026-11-23 — M5 facts, subjects, amendments, versions (DONE)
- Done: `core/ingest/{extract,amendments}.py`, `core/subjects.py`, `core/subjects_seed.py`, `core/versions.py`, prompts `extract_facts` v1 / `extract_amendments` v2 / `same_subject` v1, chains in `assemble.answer`, `expand` skips deletion markers, `tests/test_versions.py`. Pipeline POST_STAGES: Extracting facts -> Resolving amendments.
- Gate: live D1:7.2 timeline correct; q17-q23 pass; regression 28/29 (q32 flaky); unsupported displayed 0; 128 tests, ruff clean. Details: ADR-015 and amendments.md "Implementation notes (M5)".
- Gotchas: **the Bash tool collapses `\` to `\` inside heredocs, turning `"\b"` into a backspace character**: write regexes with the Write/Edit tools (ruff PLE2510 catches it). `ingest_corpus.py --reset` guards unknown folders (added `cache`). `enqueue()` dedupes by sha, so a forced re-run needs a new `ingest_jobs` row. A `D2` alias list contains the agreement's ref number: never resolve targets by name alone.
- Open: held-out generalisation set (ADR-013) not created yet; do it before M8 (M6/M7 don't depend on it). Planner/drafter tuned on `qwen3.5:4b`.
- Next: M6 contradictions (read design/contradictions.md): `core/conflict_rules.py`, ingest-time scan, query-time lookup, `conflict` status.

## 2026-11-23 — M6 contradictions (DONE, C3/q26 deferred to M9)
- Done: `core/conflict_rules.py` (pure rules, every table row tested), `core/ingest/conflicts.py` (scan, stage "Checking conflicts"), `core/answer/disagree.py` (lookup, `asserts_disputed`, cards, partner expansion, recheck), `prompts/judge_conflict.md` v1, `AnswerJSON.disagreements` filled, `tests/test_conflicts.py` (31 tests).
- Gate: live corpus stores exactly C1 and C2; q05, q09, q24, q25, q27, q28 pass; regression 27/27; abstention 6/6; unsupported displayed 0. ADR-016.
- Gotchas: a `max` vs `eq` pair must be normalised and the `differing` sides swapped back; a merged range fact carries the min fact's id; AppTest after a click re-runs only the page script when `st.navigation` is used.
- Next: M7 UI.

## 2026-11-23 — M7 UI (DONE)
- Done: `app/main.py`, `app/state.py`, `app/i18n.py`, `app/components/{sidebar,answer_card,evidence,cards}.py`, `app/pages/{chat,documents,conflicts,amendments}.py`, `core/render/highlight.py`, `db.update_chat_settings`, `versions.clause_in_force`, `disagree.{active_conflict_ids,cards_from_ids}`, `tests/test_app.py` (9 AppTest/render tests). Run: `streamlit run app/main.py`.
- Gate: browser walk-through against the live model service (see the plan's M7 status); 168 tests passing, ruff clean.
- Gotchas: Python 3.11 f-strings cannot reuse the outer quote; `use_container_width` is deprecated (use `width="stretch"`); AppTest after a click re-runs only the page script when `st.navigation` is used, so the sidebar is tested through its own tiny script; the Chrome tool needs the app on `localhost` and ~40 s per live answer on this CPU box.
- Not done / open: demo steps 3, 4, 5, 7 were not clicked through in the browser (as-of/GST covered by eval and AppTest; calculator is M9; upload not exercised); held-out generalisation set (ADR-013) still to be created before M8; C3 / q26 / q35-q39 wait for M9; Hindi is M10; deploy is M8.
- Next (outside the autonomy window): M8 deploy to Modal needs the user's Modal account and secret (runbook §3).

## 2026-11-23 — M7b React UI + API (DONE; user request)
- Done: ADR-017, `design/ui-react.md`, `api/` (FastAPI, 11 endpoints, SSE ask), `tests/test_api.py` (11), `web/` (Vite, React 18, TypeScript, Tailwind, Radix, TanStack Query): collapsible sidebar with grouped/searchable chat history, chat window with stage stepper and plain-language answer cards, citation chips, right-hand panel (Sources / Page with highlighted PDF page / How we checked), Documents, Conflicts, Amendments pages, light and dark themes. Vitest: 19 tests.
- Readability rules (the user's main concern): plain words only (`plain.ts`), human names instead of ids, each fact once, checks behind "How we checked", abstention in neutral slate, no token streaming. Details in design/ui-react.md.
- Gate: 179 backend + 19 front-end tests; browser-verified (see plan). Run: `uvicorn api.main:app --port 8000` + `cd web && npm run dev`, or `npm run build` and open :8000.
- Open: mobile widths, upload through the UI, Hindi labels in React, removing `app/` (Streamlit) once the user approves, and retargeting the M8 deploy at FastAPI + `web/dist` (ADR-017). The held-out generalisation set (ADR-013) is still not created.
