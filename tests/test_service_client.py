"""Offline tests: the FastAPI service with stub backends, driven through the real client via ASGI-less TestClient."""
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from core.llm.client import ModelClient, ModelUnavailable
from model_service.server import create_app


class StubLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, json_schema, max_tokens):
        self.calls.append((messages, json_schema))
        return self.replies.pop(0), 5

    def status(self):
        return "ready"


class StubAux:
    def __init__(self):
        self.loaded = ["stub"]

    def embed(self, texts, batch_size=32):
        return [[1.0, 0.0] for _ in texts]

    def rerank(self, query, passages):
        return [float(len(p)) for p in passages]

    def nli(self, pairs):
        return [0.9 if p == h else 0.1 for p, h in pairs]


class Out(BaseModel):
    n: int


class _Transport(httpx.BaseTransport):
    """Route client requests into the FastAPI TestClient."""

    def __init__(self, tc: TestClient):
        self.tc = tc

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        r = self.tc.request(request.method, request.url.path, content=request.content, headers=request.headers)
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})


def make(llm, key="k"):
    tc = TestClient(create_app(llm=llm, aux=StubAux(), api_key="k"))
    return ModelClient(base_url="http://svc", api_key=key, transport=_Transport(tc), backoff_s=0)


def test_all_endpoints():
    c = make(StubLLM(["hi"]))
    assert c.health()["llm"] == "ready"
    assert c.chat([{"role": "user", "content": "x"}]) == "hi"
    assert c.embed(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert c.rerank("q", ["aa", "a"]) == [2.0, 1.0]
    assert c.nli([("x", "x"), ("x", "y")]) == [0.9, 0.1]


def test_bad_token_is_rejected():
    with pytest.raises(ModelUnavailable):
        make(StubLLM([]), key="wrong").embed(["a"])


def test_chat_json_retries_once_with_error_then_succeeds():
    llm = StubLLM(["not json", '{"n": 3}'])
    out = make(llm).chat_json([{"role": "user", "content": "x"}], Out)
    assert out.n == 3
    assert llm.calls[0][1] == Out.model_json_schema()
    assert "invalid" in llm.calls[1][0][-1]["content"]


def test_chat_json_gives_up_after_retry():
    with pytest.raises(ModelUnavailable):
        make(StubLLM(["bad", "still bad"])).chat_json([{"role": "user", "content": "x"}], Out)


def test_unreachable_service_raises_model_unavailable():
    class Boom(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ConnectError("down")

    c = ModelClient(base_url="http://svc", api_key="k", transport=Boom(), backoff_s=0)
    with pytest.raises(ModelUnavailable):
        c.health()
    with pytest.raises(ModelUnavailable):
        c.embed(["a"])


def test_nli_accepts_gpu_tensor_like_scores():
    """HHEM returns a torch tensor; on CUDA it must be moved to the CPU before NumPy sees it (found on Modal)."""
    import numpy as np

    from model_service.aux_models import AuxModels

    class FakeTensor:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.array([0.9, 0.1], dtype=np.float32)

        def __array__(self, *a, **k):
            raise TypeError("can't convert cuda:0 device type tensor to numpy")

    class FakeNli:
        def predict(self, pairs):
            return FakeTensor()

    m = AuxModels(device="cpu")
    m._nli = FakeNli()
    assert [round(x, 1) for x in m.nli([("a", "b"), ("c", "d")])] == [0.9, 0.1]
