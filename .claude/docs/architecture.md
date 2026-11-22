# Architecture

## Components

```
Browser ──► UI app (Streamlit, CPU)  ──HTTP(S)──►  Model service (GPU)
            ├─ app/ pages                         ├─ /llm/chat → Ollama: qwen2.5:7b-instruct
            ├─ core/ingest   (background thread)  ├─ /embed   bge-m3
            ├─ core/retrieval                     ├─ /rerank  bge-reranker-v2-m3
            ├─ core/answer                        └─ /nli     HHEM-2.1-open
            └─ DATA_DIR: SQLite, .npy, page PNGs, uploads, logs
```

- **UI app**: one Python process. Streamlit front end; ingest runs in a background `threading.Thread` with a
  job queue in SQLite (`ingest_jobs`). Everything except model inference runs here: PyMuPDF, Tesseract, BM25,
  NumPy search, verification logic, version and conflict logic.
- **Model service**: a small FastAPI app wherever the GPU is. It exposes `/llm/chat` (forwarded to Ollama on
  localhost:11434 with JSON-schema structured output), `/embed`, `/rerank`, `/nli` and `/health`. So there is one base URL and one token.
  The same code runs on your machine, in Colab, and on Modal (ADR-011).

## Environments (step-by-step commands: runbook.md)

| Environment | Model service (+ Ollama) runs on | UI app runs on | Data |
|---|---|---|---|
| **Local dev (default)** | your machine: Ollama you already have + `python -m model_service.local` → `http://localhost:8080` | your machine: `streamlit run app/main.py` | `./data` |
| **Colab (optional batch)** | inside the notebook, localhost only | not run (scripts only: ingest, eval) | `/content/.../data` → zip → download |
| **Production / judging** | Modal T4 (`model_service/modal_app.py`) | Modal CPU container running Streamlit (`deploy/modal_app_ui.py`) | `modal.Volume` "docai-data" mounted at `/data` |

Rules: Colab never serves a public URL (ADR-002). The UI app never needs a GPU. Switching environments = changing `MODEL_BASE_URL`
(+ `MODEL_API_KEY`), nothing else.
Fallback UI host if Modal web serving gives trouble: Hugging Face Space (Docker, CPU) with the demo corpus baked into the image.

## Configuration (`core/config.py`, env-overridable)

```python
MODEL_BASE_URL = env("MODEL_BASE_URL", "http://localhost:8080")
MODEL_API_KEY  = env("MODEL_API_KEY", "dev-token")
LLM_MODEL      = env("LLM_MODEL", "qwen2.5:7b-instruct")   # Ollama tag; small GPU: qwen2.5:3b-instruct
AUX_DEVICE     = env("AUX_DEVICE", "cuda")                  # model service only: cuda | cpu
DATA_DIR       = Path(env("DATA_DIR", "./data"))

# retrieval
WINDOW_TOKENS = 350; WINDOW_OVERLAP = 50
TOPK_DENSE = 30; TOPK_BM25 = 30; RRF_K = 60; RERANK_KEEP = 8
EVIDENCE_MAX_SPANS = 40; EVIDENCE_MAX_TOKENS = 3500
# verification
HHEM_THRESHOLD = 0.5          # tune on tests/qa.yaml; record the chosen value in decisions.md
QUOTE_FUZZ_MIN = 95           # rapidfuzz partial_ratio for quoted text inside a claim
# facts / subjects / conflicts
SUBJECT_SIM_MIN = 0.85
OCR_MIN_CHARS = 50            # page text chars below this + has image → OCR
OCR_DPI = 300; OCR_LANG = "eng+hin"
LLM_TEMPERATURE = 0.0; LLM_MAX_RETRIES = 1
```

## Model service contract

All requests carry `Authorization: Bearer $MODEL_API_KEY`.

| Method + path | Request | Response |
|---|---|---|
| `GET /health` | — | `{"status":"ok","llm":"ready"|"loading","models":[...]}` |
| `POST /llm/chat` | `{"messages":[...], "json_schema":{...}\|null, "max_tokens":900}` | `{"text":str, "ms":int}` (text is JSON when a schema was sent) |
| `POST /embed` | `{"texts":[str], "batch_size":32}` | `{"dense":[[float]]}` (L2-normalised, dim 1024) |
| `POST /rerank` | `{"query":str, "passages":[str]}` | `{"scores":[float]}` (higher = more relevant) |
| `POST /nli` | `{"pairs":[{"premise":str,"hypothesis":str}]}` | `{"scores":[float]}` (HHEM consistency 0–1) |

`core/llm/client.py` wraps these with retries (3 attempts, exponential backoff, 180 s timeout for LLM, 60 s for others)
and a `ModelUnavailable` exception that the UI turns into the amber "warming up" state.

## Module boundaries

- `core/ingest/*` writes to the DB; nothing else writes documents, clauses, spans, facts, edges or conflicts.
- `core/retrieval/*` is read-only on the DB plus the `.npy` and BM25 pickle in `DATA_DIR/index/`.
- `core/answer/*` is read-only on the corpus and writes only `messages`.
- `app/*` calls `core.ingest.pipeline.enqueue(path)` and `core.answer.assemble.answer(chat_id, question)`. No business logic in the UI.

## Request flows

Ingest (detail: design/ingest.md, facts-and-subjects.md, amendments.md, contradictions.md):
`register → parse (+OCR) → segment → index → extract facts + amendment directives → canonicalise subjects →
resolve amendments + rebuild version timelines → conflict scan (affected subjects) → Ready`

Query (detail: design/retrieval.md, answering.md):
`context (as-of, scope, lang) → plan → retrieve per sub-question → expand versions → filter in force →
draft (claims + span_ids) → verify → gate → attach conflicts / chains / calc → faithfulness → save`
