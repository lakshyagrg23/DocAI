"""Smoke test against the model service: health -> chat_json -> embed -> rerank -> nli, with timings."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel

from core import config
from core.llm.client import ModelUnavailable, get_client


class Pong(BaseModel):
    answer: int


def step(name: str, fn):
    t0 = time.perf_counter()
    out = fn()
    print(f"[ok] {name:<10} {(time.perf_counter() - t0) * 1000:8.0f} ms")
    return out


def main() -> int:
    c = get_client()
    print(f"model service: {config.MODEL_BASE_URL}  LLM_MODEL={config.LLM_MODEL}")
    try:
        deadline = time.time() + 300
        while True:
            h = step("health", c.health)
            if h.get("llm") == "ready":
                break
            if time.time() > deadline:
                print("LLM never became ready (is the model pulled? `ollama pull " + config.LLM_MODEL + "`)")
                return 1
            print("   llm loading, waiting...")
            time.sleep(5)

        r = step("chat_json", lambda: c.chat_json(
            [{"role": "user", "content": 'What is 2+3? Reply as JSON {"answer": <int>}.'}], Pong, max_tokens=50))
        assert r.answer == 5, f"unexpected chat answer: {r}"

        vecs = step("embed", lambda: c.embed(["late payment fee", "prepayment charge"]))
        assert len(vecs) == 2 and len(vecs[0]) == config.EMBED_DIM, "bad embedding shape"

        scores = step("rerank", lambda: c.rerank("late fee", ["Late fee is Rs 500.", "The sky is blue."]))
        assert scores[0] > scores[1], f"rerank order wrong: {scores}"

        nli = step("nli", lambda: c.nli([
            ("The late fee is Rs 500 per instalment.", "The late fee is Rs 500."),
            ("The late fee is Rs 500 per instalment.", "The late fee is Rs 900."),
        ]))
        assert nli[0] > nli[1], f"nli order wrong: {nli}"
    except ModelUnavailable as e:
        print(f"[FAIL] model service unavailable: {e}")
        return 1
    except AssertionError as e:
        print(f"[FAIL] {e}")
        return 1
    print("smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
