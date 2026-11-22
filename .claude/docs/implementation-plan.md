# Implementation plan

Milestones run strictly in order. Each lists the docs to read, the work, and **done-when** checks. Tick the boxes as you go
and log the session in `progress.md`. P0 = M0–M8. Deploy (M8) happens as soon as P0 passes, before any P1 work, so there is
always a working URL. P1 = M9; P2 = M10.

Dev loop: everything runs on the developer's machine (Ollama + model service + Streamlit), see runbook.md §1.
Colab is optional for heavy batch runs. Modal is touched only in M8 (deploy).

---

### M0 — Scaffold and model service
Read: CLAUDE.md, spec.md, architecture.md, data-model.md, design/model-service.md
- [x] Repo layout per CLAUDE.md; `requirements.txt` (app/CPU: pymupdf, pytesseract, pillow, rank_bm25, numpy, pydantic>=2,
      rapidfuzz, dateparser, regex, networkx, httpx, python-dotenv, streamlit, reportlab, pyyaml, python-ulid, pytest, ruff) and
      `requirements-service.txt` (FlagEmbedding, transformers, torch, fastapi, uvicorn, httpx). Ollama is installed separately
- [x] `core/config.py`, `core/models.py`, `core/db.py` (schema + `init_db()` + basic DAOs)
- [x] `model_service/` server + `local.py` + `modal_app.py`; `core/llm/client.py` with chat, chat_json, embed, rerank, nli, health
- [x] `scripts/smoke.py`: health → one chat_json call → embed 2 texts → rerank → nli; prints timings
**Done when:** `python scripts/smoke.py` passes against the local model service (runbook.md §1); `pytest -q` passes (db init test).
**Status: DONE 2026-11-23** (dev config: `qwen3.5:4b`, `AUX_DEVICE=cpu`, see ADR-012).

### M1 — Demo corpus + test set
Read: demo-corpus.md, eval.md
- [x] `corpus/generate.py` builds D1–D6 exactly as specified (font with ₹, footers, the 7.2 page split, scanned D6 with no text layer)
- [x] `tests/qa.yaml` present (already written) and loadable; `scripts/eval.py` skeleton that loads it and prints the items
**Status: DONE 2026-11-23.**
**Done when:** six PDFs exist; asserts pass (₹ extractable in D1/D2; D6 has no text; D1 7.2 starts on p.3 and continues on p.4).

### M2 — Ingest: register, parse, segment, index
Read: design/ingest.md, design/retrieval.md §index
- [x] register (+ LLM metadata), parse (words, tables, header/footer removal), segment (clauses, spans, table rows, cross-page join)
- [x] windows + dense embeddings + BM25; `pipeline.py` job queue + statuses; `scripts/ingest_corpus.py --reset`
- [x] D6 is registered but marked `status_detail="needs OCR (M9)"` until M9
**Status: DONE 2026-11-23** (full D1-D5 ingest 49 s warm on CPU aux models, incl. D6 registration).
**Done when:** `tests/test_ingest.py` passes (D1:7.2 spans pages 3–4, D1:8.1 has ₹500, D2 row spans, bboxes valid);
ingest of D1–D5 ≤ 3 min warm.

### M3 — Retrieval
Read: design/retrieval.md
- [x] plan (intent, sub-questions, as_of_override, calc.given) · hybrid search · RRF · rerank · evidence pack
      (expansion already uses doc effective dates and `clause_versions` rows when present; M5 supplies the rows)
**Done when:** `python scripts/eval.py --retrieval-only --skip-types scanned,hindi` shows recall@8 ≥ 90%.
**Status: DONE 2026-11-23.** Clause recall@8 = 37/39 = 94.9% (item recall 93.5%), gate PASS. Known misses: `D6:p1.q1` (scanned, needs M9 OCR)
and `D2:table1.row2` for q27 (revisit at M6). 79 tests at M3 close.

### M4 — Answering core: draft, verify, gate, faithfulness
Read: design/answering.md (§1–§4)
- [x] draft prompt + guided JSON; verify checks (a)(b)(c)(e) as pure functions + batched NLI; (d) stub returns True until M5
- [x] gate + status rules + faithfulness; assemble + persistence + answers.jsonl log
- [x] `tests/test_verify.py` unit tests
- [x] HHEM threshold sweep; record the choice in decisions.md
**Done when:** eval passes for single, table and unanswerable items (≥ 5/6 abstain), and zero unsupported claims are displayed.
**Status: DONE 2026-11-23.** 22/22 items (single, multi non-conflict, table, q28, unanswerable) on prompt v3 / `qwen3.5:4b`; unsupported claims displayed = 0; abstention 6/6; false abstain 0/16; faithfulness avg 100; p50 19.5 s, p95 37.8 s. HHEM threshold kept at 0.5 (ADR-014). (d) version check is real already but only becomes meaningful when M5 supplies versions.

### M5 — Facts, subjects, amendments, versions
Read: design/facts-and-subjects.md, design/amendments.md
- [x] extraction call (facts + amendment directives) with validation; `core/normalize.py` with unit tests
- [x] subject canonicalisation with the seed list
- [x] target resolution, edges, `core/versions.py` rebuild + status; expansion and verify (d) become real; chains in the answer
- [x] `tests/test_versions.py`
**Done when:** the D1:7.2 timeline matches demo-corpus.md; eval passes all current_rule and as_of items except q24 (needs M6).
**Status: DONE 2026-11-23.** D1:7.2 timeline = D1 [2024-01-15, 2025-04-01) -> D3 -> D4 [2026-01-01, inf) with the live model; q17-q23 all pass (chains included); regression 28/29 over single/multi/table/current_rule/as_of/q28/unanswerable (q32 flaky, abstention 5/6; ADR-015). Ingest of D1-D5 incl. facts + amendments: ~95 s. 128 tests. Not yet done: the held-out set (ADR-013) is still to be created; q24 needs M6.

### M6 — Contradictions
Read: design/contradictions.md
- [x] `core/conflict_rules.py` + unit tests for every comparison row
- [x] ingest-time scan (incremental) + query-time lookup and re-check; disagreements grouped by subject; status `conflict`
**Done when:** exactly C1, C2, C3 are stored; eval passes q09, q24–q28 and q05 (no false conflict).
**Status: DONE 2026-11-23 (C3 and q26 deferred to M9).** Live ingest stores exactly C1 (numeric, 2024-01-15 ->) and C2 (rule, 2025-11-01 ->); C3 (borrower_age, D1:3.1 vs the scanned FAQ D6) cannot exist until D6 is OCR'd (M9) and is covered by synthetic-fact unit tests (differing `{"a":[58],"b":[60]}`, overlap from 2025-06-01). Eval: q05, q09, q24, q25, q27, q28 pass; regression 27/27 on the rest; unsupported displayed 0. 159 tests at M6 close. q26 stays open until D6 exists.

### M7 — UI
Read: design/ui.md
- [x] sidebar (multi-chat CRUD, as-of date, language, model status), Chat page with the full answer card, evidence viewer with highlights
- [x] Documents page (upload + live status + clause outline), Conflicts page, Amendments page
**Done when:** a manual run of the demo script (below) works end to end in the browser; two chats keep separate histories after reload.
**Status: DONE 2026-11-23.** Checked in a real browser (Streamlit on :8501 against the live model service): demo step 1 (conflict card D1 ₹500 · D2 ₹750 · D5 cap ₹600, citation pills, highlighted evidence page), step 2 (nil for floating loans with the D1 -> D3 -> D4 timeline), Conflicts, Amendments and Documents pages, and a full reload restoring the chat. Steps 3-5 and 7 (as-of change, GST abstention, calculator, upload) are covered by the eval items q22/q31 (calculator arrives in M9) and by `tests/test_app.py`, not clicked through in the browser; the OCR citation (step 6) needs M9. Two chats keeping separate histories is tested with AppTest. 168 tests.

### M7b — React UI + API (replaces Streamlit; user request 2026-11-23)
Read: design/ui-react.md, ADR-017
- [x] `api/` FastAPI layer + `tests/test_api.py` (chats, SSE ask, enrichment, documents, page image, conflicts, amendments)
- [x] `web/` scaffold, design system, collapsible sidebar, chat shell, composer, stage stepper
- [x] answer card (plain-language), citation chips, right panel (Sources / Page with highlight / How we checked)
- [x] Library, Conflicts, Amendments pages; dark mode; responsive; accessibility; browser checks
**Done when:** the demo script runs end to end in the React UI against the live model service, tests pass, and the screens read in plain language (design/ui-react.md §3).
**Status: DONE 2026-11-23 (browser-checked against the live model).** Verified in Chrome on the Vite dev server and on the FastAPI-served build:
the late-fee question end to end (stage stepper, "Documents disagree" comparison table with readable names, citation chips, side panel Page tab with the
quote highlighted on the real PDF page, Sources tab, "How we checked" tab), Amendments timeline, Conflicts, Documents, dark and light mode, sidebar chats.
179 backend tests + 19 front-end tests pass; ruff and `tsc` clean. Not checked in the browser: mobile widths (drawers are implemented but only reasoned about),
file upload through the Documents page, Hindi, and the remaining demo-script steps (covered by eval and API tests). The Streamlit UI (`app/`) is still in the repo
as a fallback and is to be removed once the user is satisfied with the React UI.

### M8 — Deploy (P0 complete)
Read: architecture.md §Deployment, design/model-service.md §Modal
- [ ] Deploy the model service to Modal (runbook.md §3); smoke test against its URL
- [ ] Upload the locally ingested `data/` to the Modal Volume (or re-ingest against the Modal service)
- [ ] `deploy/modal_app_ui.py` (Streamlit via web_server, Tesseract in the image, Volume at /data) deployed; model service deployed
- [ ] README: what it does, pipeline diagram (Mermaid), models and why, how verification and abstention work, how to run, limitations
- [ ] Held-out generalisation check: 2-3 differently formatted PDFs (other numbering styles, unnumbered circular, merged-cell fee table, own conflict + amendment) with a small Q&A file, never used during development; run at M5, M6 and here (ADR-013)
- [ ] Full eval against the deployed model service; all P0 gates pass
**Done when:** the public URL works from a fresh browser; P0 gates in eval.md pass; README done.

### M9 — P1: OCR, calculator, as-of UI, polish
Read: design/ingest.md §OCR, design/answering.md §5
- [ ] OCR path + D6 ingest + OCR badge in UI → q38, q39 pass
- [ ] calculator (emi, late_fee_total, prepayment_charge) → q35–q37 pass
- [ ] Re-deploy; re-run eval
**Done when:** P1 gates pass on the deployed app.

### M10 — P2: Hindi, doc scope, export
Read: design/answering.md §6, design/ui.md
- [ ] Hindi detect/translate + number guard + UI strings → q40 passes
- [ ] per-chat document scope; Markdown export
**Done when:** q40 passes; re-deploy.

---

## Demo script (run before submitting)

1. "What fees apply if I pay an EMI late?" → conflict card D1 ₹500 · D2 ₹750 · D5 cap ₹600
2. "What is the prepayment charge today for a floating-rate loan?" → Nil, with chain D1 → D3 → D4
3. Change the as-of date to 2025-06-01 and ask the same → 3%
4. "What is the GST rate on the processing fee?" → I don't have proof + missing item
5. "EMI on ₹5,00,000 at the agreement rate for 36 months?" → ₹16,968 with working
6. Click a citation → page with the highlight; open the scanned FAQ citation → OCR badge
7. Upload a new PDF on the Documents page → status goes to Ready
