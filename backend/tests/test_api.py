"""HTTP-level tests. Requires: pip install -r requirements-dev.txt

StubService below is a TEST DOUBLE. It only lets us check HTTP/WAV plumbing,
validation, limits and cleanup. It says nothing about real OmniVoice inference,
which can only be verified on a machine with the model installed."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model_service import GenerationFailed, ModelService, ModelUnavailable


class StubService(ModelService):
    def __init__(self, settings, state="ready", fail=False):
        super().__init__(settings)
        self._state, self.fail = state, fail
        self._detail = "stub unavailable" if state == "unavailable" else None
        self.calls = []

    def load(self):  # never touches torch / omnivoice
        pass

    def generate(self, text, **kw):
        self.calls.append((text, kw))
        if self._state != "ready":
            raise ModelUnavailable(self._detail)
        if self.fail:
            raise GenerationFailed("boom")
        return 0.1 * np.sin(np.linspace(0, 200, 24000)).astype(np.float32), 24000


def make_client(tmp_path, state="ready", fail=False, **overrides):
    settings = Settings(output_dir=tmp_path / "out", load_on_startup=False,
                        rate_limit_per_min=overrides.pop("rate", 100), **overrides)
    svc = StubService(settings, state, fail)
    return TestClient(create_app(settings, svc)), svc, settings


def test_health_reports_unavailable_model(tmp_path):
    client, _, _ = make_client(tmp_path, state="unavailable")
    body = client.get("/api/health").json()
    assert body["status"] == "unavailable"
    assert body["model"]["detail"] == "stub unavailable"
    assert body["capabilities"]["voice_cloning"] is False
    assert "gender" in body["design_options"]


def test_health_ready(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/api/health").json()["status"] == "ready"


def test_generate_503_when_model_unavailable(tmp_path):
    client, _, _ = make_client(tmp_path, state="unavailable")
    r = client.post("/api/generate", json={"text": "hello"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "model_unavailable"


@pytest.mark.parametrize("payload,code", [
    ({"text": "   "}, "text_empty"),
    ({"text": "x" * 1001}, "text_too_long"),
    ({"text": "hi", "speed": 5}, "validation_error"),
    ({"text": "hi", "num_step": 1}, "validation_error"),
    ({"text": "hi", "mode": "design", "design": {"gender": "robot"}}, "validation_error"),
    ({"text": "hi", "evil": 1}, "validation_error"),
    ({}, "validation_error"),
])
def test_validation_errors(tmp_path, payload, code):
    client, svc, _ = make_client(tmp_path)
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == code
    assert svc.calls == []


def test_generate_returns_wav_and_cleans_up(tmp_path):
    client, svc, settings = make_client(tmp_path)
    r = client.post("/api/generate", json={
        "text": "hello", "mode": "design", "speed": 1.2,
        "design": {"gender": "female", "accent": "british accent"}})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    assert float(r.headers["x-audio-duration"]) == pytest.approx(1.0, abs=0.01)
    assert svc.calls[0][1]["instruct"] == "female, british accent"
    assert list(settings.output_dir.glob("*.wav")) == []  # temp file removed after response


def test_generation_failure_hides_details(tmp_path):
    client, _, _ = make_client(tmp_path, fail=True)
    r = client.post("/api/generate", json={"text": "hello"})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "generation_failed"
    assert "boom" not in r.text


def test_rate_limit(tmp_path):
    client, _, _ = make_client(tmp_path, rate=2)
    codes = [client.post("/api/generate", json={"text": "hi"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_body_too_large_and_unknown_route(tmp_path):
    client, _, _ = make_client(tmp_path)
    r = client.post("/api/generate", content=b"{" + b" " * 70000 + b"}",
                    headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert client.get("/api/nope").status_code == 404


def test_cloning_disabled_by_default(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert client.post("/api/generate-clone", data={"text": "x"}).status_code in (404, 405)
