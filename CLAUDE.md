# CLAUDE.md — Verifiable Document AI ("Zero-Guessing DocAI")

A web app that answers questions across multiple PDFs **only with verified evidence**. It cites doc + page + verbatim quote,
flags contradicting clauses side by side, resolves amendment chains to the rule in force, and answers
"I don't have proof" instead of guessing. It runs **entirely on open-source models**. Deadline: a deployed prototype within ~24 h of 2026-11-22.

## Non-negotiable constraints (read before every task)

1. **No paid or external AI APIs.** No OpenAI, Anthropic or Gemini calls. The only model endpoint is our own service at `MODEL_BASE_URL`
   (Ollama LLM + embed/rerank/NLI). No other model endpoint, no cloud LLM SDKs.
2. **Never display an unverified claim.** Every sentence shown in an answer body must have passed `core/answer/verify.py`.
   Anything else goes to "Blocked claims". If nothing passes → abstain ("I don't have proof" + what's missing).
3. **Quotes are copied from stored spans, never generated.** The LLM references `span_id`s; the UI renders `Span.text`.
4. **Arithmetic is done in Python**, never by the LLM. The LLM only extracts inputs (each with a span_id).
5. **Amendments and contradictions are computed at ingest time** and stored. Queries only do lookups plus a cheap
   re-check on retrieved clauses. Never scan the whole corpus per query.
6. **Determinism:** temperature 0, versioned prompts in `core/llm/prompts/`, thresholds only in `core/config.py`.
7. **Colab is never a serving host.** Colab's terms forbid web services and proxies on all runtimes. Colab is for
   development and batch pre-ingest only (localhost model service inside the notebook is fine).
8. Demo corpus uses only **fictional** organisations (Kestrel Finance Ltd., Financial Conduct Board). Never imitate a real bank or regulator.

## Docs — read the relevant ones before coding a feature

| File | Read when |
|---|---|
| `.claude/docs/spec.md` | Always first in a new session: scope, FRs, acceptance criteria |
| `.claude/docs/architecture.md` | Touching deployment, config, the model service contract, module boundaries |
| `.claude/docs/data-model.md` | Touching storage, Pydantic models, IDs, answer JSON |
| `.claude/docs/design/ingest.md` | Parsing, OCR, clause segmentation, spans, tables |
| `.claude/docs/design/retrieval.md` | Indexing, hybrid search, reranking, query planning |
| `.claude/docs/design/facts-and-subjects.md` | Fact extraction, subject canonicalisation |
| `.claude/docs/design/amendments.md` | Amendment extraction, version graph, as-of resolution |
| `.claude/docs/design/contradictions.md` | Conflict detection at ingest and at query time |
| `.claude/docs/design/answering.md` | Drafting, verification, gate, faithfulness, calculator, Hindi |
| `.claude/docs/design/model-service.md` | Ollama + aux models service (local / Colab / Modal) |
| `.claude/docs/runbook.md` | How to run in dev, on Colab, and how to deploy |
| `.claude/docs/design/ui.md` | (legacy Streamlit design; the live UI is design/ui-react.md) |
| `.claude/docs/demo-corpus.md` | Generating the 6 demo PDFs (exact text) and `tests/qa.yaml` |
| `.claude/docs/eval.md` | Metrics, `scripts/eval.py`, release gates |
| `.claude/docs/implementation-plan.md` | **Which milestone is next and its done-when checks** |
| `.claude/docs/decisions.md` | Why things are the way they are (ADRs). Add an entry when you deviate |
| `.claude/docs/progress.md` | Session log — **read at start, append at end of every session** |

If a doc and the code disagree, the doc wins unless `decisions.md` records a later decision. If you must deviate,
add an ADR to `decisions.md` and update the affected doc in the same change.

## Repo layout (target)

```
api/                     FastAPI over core/ (chats, SSE ask, documents, sources, conflicts, amendments)
web/                     React UI (Vite + TypeScript + Tailwind); `npm run build` -> web/dist, served by api/
core/
  config.py              all thresholds, paths, env vars
  db.py                  SQLite schema + data access
  models.py              Pydantic models (see data-model.md)
  llm/client.py          OpenAI-compatible client → MODEL_BASE_URL; embed/rerank/nli helpers
  llm/prompts/*.md       versioned prompt templates
  ingest/                register, parse, ocr, segment, extract, subjects, amendments, conflicts, pipeline
  retrieval/             index (dense .npy), bm25, hybrid (RRF + rerank), expand (version graph)
  answer/                plan, draft, verify, gate, calc, translate, assemble
  render/highlight.py    page PNG + highlight rectangles
model_service/           FastAPI: /llm/chat (→ Ollama), /embed, /rerank, /nli; local.py (dev/Colab); modal_app.py (prod)
corpus/generate.py       builds demo PDFs into corpus/pdfs/
scripts/                 ingest_corpus.py, eval.py, smoke.py
tests/                   qa.yaml + pytest unit tests
notebooks/colab_preingest.ipynb
deploy/modal_app_ui.py   FastAPI + built React UI on Modal (CPU) with Volume
```

## Commands (keep these working; update here if they change)

```bash
pip install -r requirements.txt            # app deps (CPU)
python corpus/generate.py                   # → corpus/pdfs/D1..D6.pdf
ollama pull qwen2.5:7b-instruct            # once, on the dev machine
python -m model_service.local              # dev: model service on localhost:8080 (uses your running Ollama)
modal deploy model_service/modal_app.py    # GPU model service on Modal T4
python scripts/ingest_corpus.py --reset    # ingest corpus/pdfs → DATA_DIR
uvicorn api.main:app --port 8000           # API (+ built React UI from web/dist on the same port)
cd web && npm install && npm run dev       # React dev server on :5173 (proxies /api to :8000)
cd web && npm run build && npm test        # production build, front-end tests
python scripts/eval.py                     # run tests/qa.yaml, print metrics + gate pass/fail
pytest -q                                  # unit tests
modal deploy deploy/modal_app_ui.py        # deploy the UI
```

Env vars: `MODEL_BASE_URL`, `MODEL_API_KEY`, `DATA_DIR` (default `./data`), `LLM_MODEL` (default `qwen2.5:7b-instruct`), `AUX_DEVICE` (`cuda`|`cpu`, model service only). Dev values live in `.env` (see runbook.md).

## Coding conventions

- Python 3.11, type hints everywhere, Pydantic v2 models for every LLM input/output and DB row, `ruff` clean.
- Each verification check is a **pure function** with a unit test (numbers, dates, quote match, version status).
- LLM calls go only through `core/llm/client.py`. JSON output uses guided decoding + Pydantic validation + 1 retry.
- Log every answer's full JSON (claims, checks, scores, prompt version) to `DATA_DIR/logs/answers.jsonl`.
- Small modules (< ~300 lines). No notebooks in core logic.
- Tests for a milestone must pass before starting the next one (see implementation-plan.md).

## Workflow per session

1. Read `progress.md` and `implementation-plan.md`; pick the first unchecked milestone.
2. Read the design docs it lists. Implement. Write and run its tests and its done-when checks.
3. Tick the milestone's boxes in `implementation-plan.md` and append a dated entry to `progress.md`
   (what was done, what's left, any gotchas).
