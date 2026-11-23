"""All thresholds, paths and env vars. Thresholds live only here (CLAUDE.md constraint 6)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


MODEL_BASE_URL = env("MODEL_BASE_URL", "http://localhost:8080")
MODEL_API_KEY = env("MODEL_API_KEY", "dev-token")
LLM_MODEL = env("LLM_MODEL", "qwen2.5:7b-instruct")  # Ollama tag; small GPU: qwen2.5:3b-instruct
AUX_DEVICE = env("AUX_DEVICE", "cuda")  # model service only: cuda | cpu
OLLAMA_URL = env("OLLAMA_URL", "http://127.0.0.1:11434")
DATA_DIR = Path(env("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "corpus.db"

# retrieval
WINDOW_TOKENS = 350
WINDOW_OVERLAP = 50
TOPK_DENSE = 30
TOPK_BM25 = 30
RRF_K = 60
RERANK_KEEP = 8
EVIDENCE_MAX_SPANS = 40
EVIDENCE_MAX_TOKENS = 3500

# verification
HHEM_THRESHOLD = 0.5  # tune on tests/qa.yaml; record the chosen value in decisions.md
QUOTE_FUZZ_MIN = 95  # rapidfuzz partial_ratio for quoted text inside a claim

# facts / subjects / conflicts
SUBJECT_SIM_MIN = 0.85
SUBJECT_FUZZ_MIN = 90  # rapidfuzz token_set_ratio against a subject alias
TARGET_MATCH_MIN = 85  # rapidfuzz partial_ratio of an amendment's target_ref against a document
EXTRACT_BATCH = 6  # clauses per fact-extraction call
EXTRACT_WORKERS = 2  # parallel extraction calls (Ollama serves a few requests at once)
OCR_MIN_CHARS = 50  # page text chars below this + has image -> OCR
OCR_DPI = 300
OCR_LANG = "eng+hin"
OCR_RUPEE_FIX_CONF = 85  # below this word confidence, "2<digits> lakh/crore" is read as a rupee amount

# llm
LLM_TEMPERATURE = 0.0
LLM_MAX_RETRIES = 1
LLM_SEED = 7
LLM_NUM_CTX = 8192
LLM_TIMEOUT_S = 180
AUX_TIMEOUT_S = 60
CLIENT_ATTEMPTS = 3
EMBED_DIM = 1024

# ingest
RERANK_CHUNK = 10  # passages per /rerank request
EMBED_CHUNK = 8  # texts per /embed request (CPU model service must answer within AUX_TIMEOUT_S)
HEADER_FOOTER_ZONE = 0.08  # top/bottom fraction of the page scanned for running headers/footers
HEADER_FOOTER_REPEAT = 0.6  # a line repeated on >= this share of pages (min 2 pages) is a header/footer
PARA_GAP_FONT_RATIO = 0.7  # vertical gap between lines > ratio x font size starts a new paragraph
REGISTER_PAGE_CHARS = 2500
