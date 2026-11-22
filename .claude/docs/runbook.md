# Runbook — how to run it in dev, on Colab, and in production

## 0. The mental model: three processes

| # | Process | What it does | Needs GPU? |
|---|---|---|---|
| 1 | **Ollama** | Runs the LLM (`qwen2.5:7b-instruct`) on `localhost:11434` | Yes (or slow on CPU) |
| 2 | **Model service** (`model_service/`, FastAPI on `:8080`) | One gateway for all model calls: `/llm/chat` (forwards to Ollama), `/embed`, `/rerank`, `/nli` (loads bge-m3, bge-reranker, HHEM itself) | Preferably |
| 3 | **App** (`app/` + `core/`, Streamlit on `:8501`) | UI, ingest, retrieval, verification, conflicts, versions, SQLite | No |

The app only knows `MODEL_BASE_URL`. **Dev and production run the same three processes; only the machine changes.**

| Environment | 1 Ollama | 2 Model service | 3 App | `MODEL_BASE_URL` |
|---|---|---|---|---|
| Local dev | your machine | your machine | your machine | `http://localhost:8080` |
| Colab (optional) | notebook | notebook | scripts only (ingest/eval) | `http://localhost:8080` (inside Colab) |
| Production | Modal T4 container | same Modal container | Modal CPU container | `https://<you>--docai-model-....modal.run` |

---

## 1. Local development (daily work)

### 1.1 One-time setup

1. Check the GPU: `nvidia-smi` (note the VRAM), and choose settings:

   | VRAM | `LLM_MODEL` | `AUX_DEVICE` |
   |---|---|---|
   | ≥ 10 GB | `qwen2.5:7b-instruct` | `cuda` |
   | 6–9 GB | `qwen2.5:7b-instruct` | `cpu` (aux models are small; ingest just gets slower) |
   | < 6 GB | `qwen2.5:3b-instruct` for daily work; run the full eval with 7B on Colab (§2) | `cpu` |

2. `ollama pull qwen2.5:7b-instruct` (and/or `qwen2.5:3b-instruct`). Make sure Ollama is running (`ollama list` works).
3. Tesseract with Hindi data (needed only from M9):
   Ubuntu `sudo apt install tesseract-ocr tesseract-ocr-hin` · macOS `brew install tesseract tesseract-lang` ·
   Windows: UB-Mannheim installer, tick Hindi, add it to PATH.
4. Python 3.11 venv:
   ```bash
   python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements.txt -r requirements-service.txt
   ```
   For `AUX_DEVICE=cuda`, install the CUDA build of torch that matches your driver (pytorch.org selector) *before* the requirements.
5. Create `.env` (git-ignored; `core/config.py` and `model_service` load it with python-dotenv):
   ```
   MODEL_BASE_URL=http://localhost:8080
   MODEL_API_KEY=dev-token
   LLM_MODEL=qwen2.5:7b-instruct
   AUX_DEVICE=cuda
   DATA_DIR=./data
   OLLAMA_URL=http://127.0.0.1:11434
   ```
6. Optional, to let Ollama handle parallel requests: set `OLLAMA_NUM_PARALLEL=4` and `OLLAMA_KEEP_ALIVE=24h` in Ollama's
   environment and restart it (Linux: `systemctl edit ollama`; macOS/Windows: env var + restart the app). If VRAM is tight, use `OLLAMA_NUM_PARALLEL=2`.

### 1.2 Every day

```bash
# terminal 1 — model service (leave running)
python -m model_service.local                      # → http://localhost:8080 ; uses your running Ollama

# terminal 2 — work
python scripts/smoke.py                            # health + 1 LLM call + embed + rerank + nli
python corpus/generate.py                          # only when corpus spec changes
python scripts/ingest_corpus.py --reset            # rebuild ./data from corpus/pdfs
streamlit run app/main.py                          # http://localhost:8501
python scripts/eval.py --skip-types scanned,hindi  # acceptance tests
pytest -q
```

Claude Code runs on the same machine and uses these same commands.

---

## 2. Colab (optional, for heavy runs)

Use it when the local GPU is too small or slow for the **7B** full eval or a full corpus re-ingest. It is batch compute only:
nothing is exposed to the internet (ADR-002).

Notebook `notebooks/colab_preingest.ipynb` (T4 runtime):
```bash
!git clone <your repo> && cd verifiable-doc-ai
!apt-get -qq install tesseract-ocr tesseract-ocr-hin zstd
!curl -fsSL https://ollama.com/install.sh | sh
!pip -q install -r requirements.txt -r requirements-service.txt
# start Ollama + model service in the background (localhost only)
!nohup python -m model_service.local --start-ollama > svc.log 2>&1 &
!python scripts/smoke.py                       # waits for health; first run pulls the model (~2–4 min)
!python corpus/generate.py && python scripts/ingest_corpus.py --reset
!python scripts/eval.py
!zip -qr data.zip data/                        # download, or copy to Drive
```
Unzip `data.zip` locally (or upload it straight to the Modal Volume, §3.3).

---

## 3. Deploy to production (Modal) — milestone M8

### 3.1 One-time

```bash
pip install modal && modal setup                  # browser login
# optional: add a payment method in Modal to raise free credit from $5 to $30/month
modal secret create docai-token MODEL_API_KEY=<long-random-string>
modal volume create docai-data
```

### 3.2 Model service on a T4

```bash
modal deploy model_service/modal_app.py            # prints https://<you>--docai-model-...modal.run
MODEL_BASE_URL=<that url> MODEL_API_KEY=<the secret> python scripts/smoke.py
```
The first start pulls `qwen2.5:7b-instruct` into the `ollama-models` volume (a few minutes). Later cold starts take ~1–3 min.

### 3.3 Data

Either upload what you ingested locally (fastest):
```bash
modal volume put docai-data ./data /                # check `modal volume put --help` for the exact path syntax
```
or ingest once against the deployed model service:
`MODEL_BASE_URL=<url> DATA_DIR=./data_prod python scripts/ingest_corpus.py --reset`, then upload `data_prod`.

### 3.4 UI on Modal (CPU)

```bash
modal secret create docai-ui MODEL_BASE_URL=<model url> MODEL_API_KEY=<the secret>
modal deploy deploy/modal_app_ui.py                # prints the public app URL → share this
```
`deploy/modal_app_ui.py`: debian_slim + `apt_install("tesseract-ocr","tesseract-ocr-hin")` + `requirements.txt`;
Volume `docai-data` at `/data` (`DATA_DIR=/data`); runs `streamlit run app/main.py --server.port 8000 --server.address 0.0.0.0
--server.headless true` under `@modal.web_server(8000)`; a single container (`max_containers=1`, because SQLite).

### 3.5 Judging window and cost control

- Before judging: `KEEP_WARM=1 modal deploy model_service/modal_app.py` and the same for the UI (sets `min_containers=1`),
  then open the app once so everything is warm.
- After judging: redeploy without `KEEP_WARM` so the containers scale to zero.
- Cost: T4 ≈ $0.59/h while running; the UI container costs cents per hour. A 24 h warm window ≈ $15.

---

## 4. Which mode when

| Task | Where |
|---|---|
| Writing code with Claude Code, unit tests, quick evals | Local (§1) |
| Full 40-question eval with 7B when the local GPU is small | Colab (§2) |
| Re-ingesting the corpus after big ingest changes, if local is slow | Colab (§2) or local overnight |
| Anything a judge or teammate opens via a URL | Modal (§3) only |

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| JSON output cut off or invalid | `num_ctx` must be 8192 in the Ollama request options; raise `max_tokens` for that prompt |
| Ollama out of memory / very slow | Lower `OLLAMA_NUM_PARALLEL`; use `AUX_DEVICE=cpu`; or switch to `qwen2.5:3b-instruct` locally |
| `/health` says the LLM is loading | First request after a cold start loads the model; wait ~1 min. The UI shows the amber dot meanwhile |
| Modal app works but is slow on first click | Cold start: use KEEP_WARM during judging |
| Tesseract not found (Windows) | Set `pytesseract.pytesseract.tesseract_cmd` via env `TESSERACT_CMD` |

## 6. Dev machine notes (this repo's author, 2026-11-23)

- Windows, Python 3.11 venv at `.venv` (`.venv\Scripts\python.exe`), CPU torch: `pip install torch --index-url https://download.pytorch.org/whl/cpu` before `requirements-service.txt`.
- `.env`: `LLM_MODEL=qwen3.5:4b`, `AUX_DEVICE=cpu` (ADR-012). First call to embed/rerank/nli downloads bge-m3, bge-reranker-v2-m3 and HHEM (several minutes); later calls are fast.
- Start the service: `.venv\Scripts\python.exe -m model_service.local` (log it to `svc.log`, which is git-ignored if you add it). Then `.venv\Scripts\python.exe scripts\smoke.py`.
- Bash heredocs with non-ASCII characters fail in Claude Code's Git Bash here; write such files with the Write tool.
