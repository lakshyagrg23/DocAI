"""Dev / Colab entry: python -m model_service.local [--start-ollama] [--port 8080] [--host 127.0.0.1]."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import time

import httpx
import uvicorn

from core import config


def start_ollama() -> subprocess.Popen | None:
    try:
        httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
        return None  # already running
    except httpx.HTTPError:
        pass
    if shutil.which("ollama") is None:
        subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True)
    proc = subprocess.Popen(["ollama", "serve"])
    for _ in range(60):
        try:
            httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
            break
        except httpx.HTTPError:
            time.sleep(1)
    subprocess.run(["ollama", "pull", config.LLM_MODEL], check=True)
    return proc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-ollama", action="store_true")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if args.start_ollama:
        start_ollama()
    from model_service.server import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
