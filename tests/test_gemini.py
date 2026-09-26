"""GeminiVision against a fake Gemini server: overloads, fallbacks, cache. No network, no key."""

import json

import httpx
import pytest

from parity.gemini import GeminiError, GeminiVision

ANSWER = {"role": "complex", "alt_verdict": "wrong", "confidence": 0.9}


def ok(body=ANSWER, fenced=False, with_thought=False):
    text = json.dumps(body)
    if fenced:
        text = f"```json\n{text}\n```"
    parts = ([{"text": "thinking...", "thought": True}] if with_thought else []) + [{"text": text}]
    return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})


class FakeGemini:
    """Replies from a per-model script of responses; records every request."""

    def __init__(self, script):
        self.script = {m: list(rs) for m, rs in script.items()}
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            ]})
        model = request.url.path.split("/models/")[1].split(":")[0]
        return self.script[model].pop(0)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def vision(fake, models=("m1",), **kw):
    sleeps = []
    v = GeminiVision(models=list(models), api_key="key", client=fake.client(), min_interval=0, sleep=sleeps.append, **kw)
    return v, sleeps


def test_request_shape():
    fake = FakeGemini({"m1": [ok()]})
    v, _ = vision(fake)
    answer, model = v.judge_json("prompt", b"\x89PNG", "image/png")
    assert answer == ANSWER and model == "m1"
    req = fake.requests[0]
    assert req.url.path.endswith("/models/m1:generateContent")
    assert req.headers["x-goog-api-key"] == "key"
    body = json.loads(req.content)
    assert body["generationConfig"] == {"temperature": 0, "responseMimeType": "application/json"}
    parts = body["contents"][0]["parts"]
    assert parts[0]["text"] == "prompt" and parts[1]["inlineData"]["mimeType"] == "image/png"


def test_code_fences_and_thought_parts_are_handled():
    fake = FakeGemini({"m1": [ok(fenced=True, with_thought=True)]})
    v, _ = vision(fake)
    assert v.judge_json("p", b"img")[0] == ANSWER


def test_overloaded_model_is_retried_with_backoff():
    fake = FakeGemini({"m1": [httpx.Response(503), httpx.Response(429), ok()]})
    v, sleeps = vision(fake, backoff_seconds=2.0)
    assert v.judge_json("p", b"img")[0] == ANSWER
    assert sleeps == [2.0, 4.0]  # exponential backoff
    assert v.calls == 3


def test_falls_back_to_next_model_when_one_stays_busy():
    fake = FakeGemini({"m1": [httpx.Response(503)] * 4, "m2": [ok()]})
    v, _ = vision(fake, models=("m1", "m2"))
    answer, model = v.judge_json("p", b"img")
    assert model == "m2"


def test_all_busy_gives_actionable_error():
    fake = FakeGemini({"m1": [httpx.Response(503)] * 4})
    v, _ = vision(fake)
    with pytest.raises(GeminiError, match="busy or rate-limited") as exc:
        v.judge_json("p", b"img")
    assert "PARITY_VISION_MODELS" in str(exc.value)


def test_unknown_model_error_lists_usable_models():
    fake = FakeGemini({"gemini-9-ultra": [httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})]})
    v, _ = vision(fake, models=("gemini-9-ultra",))
    with pytest.raises(GeminiError) as exc:
        v.judge_json("p", b"img")
    msg = str(exc.value)
    assert "not found: gemini-9-ultra" in msg
    assert "gemini-3.1-flash-lite" in msg and "text-embedding" not in msg


def test_cache_means_the_same_image_is_never_paid_for_twice(tmp_path):
    fake = FakeGemini({"m1": [ok()]})
    v, _ = vision(fake, cache_dir=tmp_path)
    v.judge_json("p", b"img")
    v2, _ = vision(FakeGemini({"m1": []}), cache_dir=tmp_path)  # would fail if it hit the network
    assert v2.judge_json("p", b"img")[0] == ANSWER
    assert v2.calls == 0
    # a different image is a different question
    with pytest.raises(IndexError):
        v2.judge_json("p", b"other image")


def test_non_json_answer_is_a_clear_error():
    fake = FakeGemini({"m1": [httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "It is a chart."}]}}]})]})
    v, _ = vision(fake)
    with pytest.raises(GeminiError, match="valid JSON"):
        v.judge_json("p", b"img")


def test_missing_key(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("parity.gemini.load_dotenv", lambda: None)
    with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
        GeminiVision()


def test_models_from_env(monkeypatch):
    monkeypatch.setenv("PARITY_VISION_MODELS", "a-model, b-model")
    assert GeminiVision(api_key="k").models == ["a-model", "b-model"]


def test_default_model_is_the_one_that_worked_for_rehnuma(monkeypatch):
    monkeypatch.delenv("PARITY_VISION_MODELS", raising=False)
    assert GeminiVision(api_key="k").models == ["gemini-3.1-flash-lite"]
