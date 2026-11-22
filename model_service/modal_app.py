"""Production model service on Modal T4 (design/model-service.md). Deployed only in M8.

Verify Modal API names (scaledown_window, min_containers, asgi_app, add_local_python_source) against current docs.
"""
from __future__ import annotations

import os
import subprocess
import time

import modal

KEEP_WARM = os.environ.get("KEEP_WARM") == "1"
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("curl", "zstd")
    .run_commands("curl -fsSL https://ollama.com/install.sh | sh")
    .pip_install("fastapi", "uvicorn", "httpx", "python-dotenv", "numpy", "FlagEmbedding", "transformers", "torch")
    .env({"OLLAMA_NUM_PARALLEL": "4", "OLLAMA_KEEP_ALIVE": "24h", "AUX_DEVICE": "cuda", "LLM_MODEL": LLM_MODEL})
    .add_local_python_source("model_service", "core")
)
app = modal.App("docai-model", image=image)
ollama_vol = modal.Volume.from_name("ollama-models", create_if_missing=True)
hf_vol = modal.Volume.from_name("hf-cache", create_if_missing=True)


@app.cls(
    gpu="T4",
    volumes={"/root/.ollama": ollama_vol, "/root/.cache/huggingface": hf_vol},
    secrets=[modal.Secret.from_name("docai-token")],
    scaledown_window=900,
    timeout=3600,
    min_containers=1 if KEEP_WARM else 0,
)
class ModelService:
    @modal.enter()
    def start(self) -> None:
        import httpx

        subprocess.Popen(["ollama", "serve"])
        for _ in range(120):
            try:
                httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
                break
            except httpx.HTTPError:
                time.sleep(1)
        have = subprocess.run(["ollama", "list"], check=False, capture_output=True, text=True).stdout
        if LLM_MODEL.split(":")[0] not in have:
            subprocess.run(["ollama", "pull", LLM_MODEL], check=True)
            ollama_vol.commit()
        httpx.post("http://127.0.0.1:11434/api/chat", timeout=300, json={
            "model": LLM_MODEL, "stream": False, "messages": [{"role": "user", "content": "hi"}],
            "options": {"num_predict": 1, "num_ctx": 8192}})
        from model_service.aux_models import AuxModels
        from model_service.server import create_app

        aux = AuxModels(device="cuda")
        aux.embed(["warm"])
        aux.rerank("q", ["p"])
        aux.nli([("a", "a")])
        self.web = create_app(aux=aux)

    @modal.asgi_app()
    def serve(self):
        return self.web
