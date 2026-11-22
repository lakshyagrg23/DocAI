# Design: Model service

Contract: architecture.md §Model service contract. Code: `model_service/{server.py, aux_models.py, llm_backend.py, local.py, modal_app.py}`.
Decision: ADR-011 (Ollama everywhere). vLLM is an optional later optimisation, not part of the plan.

## Shape: one small FastAPI app wherever there is a GPU

```
model_service (FastAPI, uvicorn :8080)              ← MODEL_BASE_URL points here
 ├─ POST /llm/chat   → llm_backend → Ollama (http://127.0.0.1:11434) with JSON-schema "format"
 ├─ POST /embed      → bge-m3            ┐
 ├─ POST /rerank     → bge-reranker-v2-m3 ├ aux_models (torch; device = AUX_DEVICE: cuda | cpu)
 ├─ POST /nli        → HHEM-2.1-open      ┘
 └─ GET  /health     → Ollama /api/tags has LLM_MODEL + aux models loaded
auth: Bearer MODEL_API_KEY on every route
```

The app (`core/llm/client.py`) only ever talks to `MODEL_BASE_URL`. Dev, Colab and Modal differ only in **where this
service runs** and whether it starts Ollama itself.

## LLM backend (`llm_backend.py`)

- Model: `LLM_MODEL` default `qwen2.5:7b-instruct` (Ollama tag; Q4_K_M, about 4.7 GB). Small-GPU fallback: `qwen2.5:3b-instruct`.
- Call Ollama's native API: `POST /api/chat` with
  `{"model": LLM_MODEL, "messages": [...], "stream": false, "format": <JSON schema or omitted>,
    "options": {"temperature": 0, "seed": 7, "num_ctx": 8192, "num_predict": max_tokens}}`.
  Ollama's `format` accepts a full JSON schema (structured outputs), so pass `PydanticModel.model_json_schema()`.
- `num_ctx` 8192 is required. Ollama's default context is much smaller and would silently truncate the evidence pack.
- Concurrency: start Ollama with `OLLAMA_NUM_PARALLEL=4` and `OLLAMA_KEEP_ALIVE=24h` so the model stays loaded.
- Endpoint: `POST /llm/chat {"messages": [...], "json_schema": {...} | null, "max_tokens": 900}` → `{"text": "...", "ms": 1234}`.

## Aux models (`aux_models.py`)

- Embed: `FlagEmbedding.BGEM3FlagModel("BAAI/bge-m3", use_fp16=(device=="cuda"))`, `.encode(texts, batch_size=32, max_length=1024)["dense_vecs"]`, then L2-normalise.
- Rerank: `FlagEmbedding.FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=...)`, `.compute_score(pairs, normalize=True)`.
- NLI: `AutoModelForSequenceClassification.from_pretrained("vectara/hallucination_evaluation_model", trust_remote_code=True)`,
  `.predict([(premise, hypothesis), ...])`. Follow the model card for the current tokenizer/loading code.
- `AUX_DEVICE=cpu` works (slower ingest, fine for dev). On GPU the three models need about 3 GB of VRAM in fp16.
- Load lazily on first call, then keep in memory.

## Where it runs

| Mode | Command | Who starts Ollama | Notes |
|---|---|---|---|
| **Local dev** (your machine) | `python -m model_service.local` | You (Ollama app/daemon already running) | `ollama pull qwen2.5:7b-instruct` once. `AUX_DEVICE=cuda` if VRAM ≥ ~9 GB total, else `cpu` |
| **Colab** (optional batch: pre-ingest, full eval) | notebook cell runs `model_service.local --start-ollama` in the background | the script (`curl -fsSL https://ollama.com/install.sh \| sh`, then `ollama serve &`) | localhost only. No tunnel, no public URL (ADR-002). App + scripts run in the same notebook |
| **Production** (Modal T4) | `modal deploy model_service/modal_app.py` | `@modal.enter()` starts `ollama serve`, pulls the model if absent | weights in a `modal.Volume` (`ollama-models` at `/root/.ollama`, `hf-cache` at `/root/.cache/huggingface`) |

`local.py` flags: `--start-ollama` (install check + `ollama serve` subprocess), `--port 8080`, `--host 127.0.0.1`.

## Modal app (`modal_app.py`)

- Image: `debian_slim(python 3.11)` + `apt_install("curl", "zstd")` + `run_commands("curl -fsSL https://ollama.com/install.sh | sh")`
  + `pip_install(fastapi, uvicorn, httpx, FlagEmbedding, transformers, torch)` + `add_local_python_source("model_service")`.
- `@app.cls(gpu="T4", volumes={...}, secrets=[modal.Secret.from_name("docai-token")], scaledown_window=900, timeout=3600)`.
  Use `min_containers=1` **only** during the judging window (redeploy with env `KEEP_WARM=1`).
- `@modal.enter()`: start `ollama serve` (with OLLAMA_NUM_PARALLEL / KEEP_ALIVE env), wait for :11434, `ollama pull` if
  the model is missing from the volume, warm it with a 1-token request, load the aux models on cuda.
- `@modal.asgi_app()` returns the FastAPI app from `server.py`. The printed URL is the production `MODEL_BASE_URL`.
- Cold start ≈ 1–3 min (the model is in the volume after the first run). Check current Modal API names
  (`scaledown_window`, `min_containers`, `asgi_app`, `add_local_python_source`) against Modal docs when implementing.

## Client (`core/llm/client.py`)

- `chat(messages, max_tokens) -> str` and `chat_json(messages, model_cls, max_tokens) -> model_cls`
  (sends `json_schema`, validates with Pydantic, 1 retry with the validation error appended).
- `embed(texts)`, `rerank(query, passages)`, `nli(pairs)`, `health()`; raise `ModelUnavailable` after retries.
- Timeouts: 180 s for `/llm/chat` (7B on a T4 ≈ 15–30 tokens/s), 60 s for the rest.
- max_tokens per prompt: draft 900, extract 1200, plan 300, judge 200, register 300.
