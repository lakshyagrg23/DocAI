"""The app on Modal (CPU): FastAPI + the built React UI + Tesseract, one container. ADR-017, ADR-018, ADR-020.

Why this shape:
  * One container (max_containers=1): the app keeps a SQLite database, which must have a single writer.
  * SQLite runs on the container's LOCAL disk (WAL mode needs a local filesystem). The Modal Volume is only durable storage:
    on start the data is copied from the Volume to local disk (/state, else the /seed bundle), and a background thread
    copies changes back and calls volume.commit() every SYNC_SECONDS and once more at shutdown.
  * The model service is a separate GPU app (model_service/modal_app.py); this app only needs MODEL_BASE_URL + MODEL_API_KEY,
    which come from the Modal secret `docai-ui`.

Deploy:  cd web && npm run build, then  modal deploy deploy/modal_app_ui.py     (KEEP_WARM=1 keeps one container warm)
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path

import modal

KEEP_WARM = os.environ.get("KEEP_WARM") == "1"
ROOT = Path(__file__).resolve().parents[1]
VOL = "/vol"
LOCAL_DATA = "/tmp/data"
SYNC_SECONDS = 45

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("tesseract-ocr", "tesseract-ocr-hin")
    # keep in sync with requirements.txt (without the dev-only packages)
    .pip_install("pymupdf", "pytesseract", "pillow", "rank_bm25", "numpy", "pydantic>=2", "rapidfuzz", "dateparser",
                 "regex", "networkx", "httpx", "python-dotenv", "python-ulid", "pyyaml", "fastapi", "uvicorn",
                 "python-multipart")
    .env({"DATA_DIR": LOCAL_DATA, "PYTHONUNBUFFERED": "1", "HEALTH_PASSIVE": "1"})  # the health check must not wake the GPU
    .add_local_python_source("core", "api")
    .add_local_dir(str(ROOT / "core" / "llm" / "prompts"), "/root/core/llm/prompts")  # .md files: not shipped as "python source"
    .add_local_dir(str(ROOT / "web" / "dist"), "/root/web/dist")
)
app = modal.App("docai-app", image=image)
data_vol = modal.Volume.from_name("docai-data", create_if_missing=True)


def _stamp(root: Path) -> float:
    """Newest modification time under `root` (0 when empty): a cheap 'did anything change' test."""
    newest = 0.0
    for dirpath, _, files in os.walk(root):
        for f in files:
            try:
                newest = max(newest, os.stat(os.path.join(dirpath, f)).st_mtime)
            except OSError:
                continue
    return newest


def restore() -> str:
    """Volume -> local disk. Prefers the live state over the seed bundle. Returns which one was used."""
    data_vol.reload()
    state, seed = Path(VOL) / "state", Path(VOL) / "seed"
    src = state if (state / "corpus.db").exists() else seed
    shutil.copytree(src, LOCAL_DATA, dirs_exist_ok=True)
    return src.name


def push() -> None:
    """Local disk -> Volume: a consistent copy of the database (SQLite backup API), the other files, then commit."""
    state = Path(VOL) / "state"
    state.mkdir(parents=True, exist_ok=True)
    local = Path(LOCAL_DATA)
    if (local / "corpus.db").exists():
        tmp = state / "corpus.db.tmp"
        src, dst = sqlite3.connect(local / "corpus.db"), sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        os.replace(tmp, state / "corpus.db")
    for item in local.iterdir():
        if item.name.startswith("corpus.db"):
            continue
        if item.is_dir():
            shutil.copytree(item, state / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, state / item.name)
    data_vol.commit()


@app.cls(
    secrets=[modal.Secret.from_name("docai-ui")],
    volumes={VOL: data_vol},
    max_containers=1,
    min_containers=1 if KEEP_WARM else 0,
    scaledown_window=900,
    timeout=3600,
    cpu=2.0,
    memory=3072,
)
@modal.concurrent(max_inputs=32)
class Web:
    @modal.enter()
    def start(self) -> None:
        print("restored from", restore(), flush=True)
        self.proc = subprocess.Popen(["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"],
                                     cwd="/root")
        self.stop_sync = threading.Event()
        self.last = _stamp(Path(LOCAL_DATA))

        def loop() -> None:
            while not self.stop_sync.wait(SYNC_SECONDS):
                now = _stamp(Path(LOCAL_DATA))
                if now > self.last:
                    try:
                        push()
                        self.last = now
                    except Exception as e:  # noqa: BLE001 - keep serving; the next tick retries
                        print("volume sync failed:", repr(e), flush=True)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    @modal.web_server(8000, startup_timeout=180)
    def serve(self) -> None:
        pass  # uvicorn was started in start(); Modal only waits for the port

    @modal.exit()
    def stop(self) -> None:
        self.stop_sync.set()
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        try:
            push()
        except Exception as e:  # noqa: BLE001
            print("final volume sync failed:", repr(e), flush=True)
