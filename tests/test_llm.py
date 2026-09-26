"""GroqLLM against a fake Groq server (httpx MockTransport): no network, no key needed."""

import json

import httpx
import pytest

from parity.llm import GroqLLM, LLMError

MODELS = {"data": [
    {"id": "openai/gpt-oss-120b", "active": True},
    {"id": "whisper-large-v3", "active": True},       # speech: hidden
    {"id": "canopylabs/orpheus-v1-english", "active": True},  # text-to-speech: hidden (seen on user's key)
    {"id": "meta-llama/llama-guard-4-12b", "active": True},  # moderation: hidden
    {"id": "qwen/qwen3-32b", "active": True},
    {"id": "old-retired-model", "active": False},     # inactive: hidden
]}


def fake_groq(chat_status=200, chat_body=None, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        if chat_status == 404:
            return httpx.Response(404, json={"error": {"code": "model_not_found", "message": "does not exist"}})
        body = chat_body or {"choices": [{"message": {"content": json.dumps({"answer": "hi"})}}]}
        return httpx.Response(chat_status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_missing_key_gives_clear_setup_message(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("parity.llm.load_dotenv", lambda: None)
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        GroqLLM()


def test_default_model_is_one_the_user_has(monkeypatch):
    monkeypatch.delenv("PARITY_LLM_MODEL", raising=False)
    monkeypatch.setattr("parity.llm.load_dotenv", lambda: None)
    assert GroqLLM(api_key="k", client=fake_groq()).name == "openai/gpt-oss-120b"


def test_model_from_env_overrides_default(monkeypatch):
    monkeypatch.setenv("PARITY_LLM_MODEL", "qwen/qwen3-32b")
    assert GroqLLM(api_key="k", client=fake_groq()).name == "qwen/qwen3-32b"


def test_list_models_hides_speech_moderation_and_inactive():
    llm = GroqLLM(api_key="k", model="x", client=fake_groq())
    assert llm.list_models() == ["openai/gpt-oss-120b", "qwen/qwen3-32b"]


def test_retired_model_error_lists_models_you_can_use():
    # Regression: 'llama-3.3-70b-versatile' was not available on the user's key (2026-09-26).
    llm = GroqLLM(api_key="k", model="llama-3.3-70b-versatile", client=fake_groq(chat_status=404))
    with pytest.raises(LLMError) as exc:
        llm.complete_json("sys", "user")
    msg = str(exc.value)
    assert "llama-3.3-70b-versatile" in msg
    assert "openai/gpt-oss-120b, qwen/qwen3-32b" in msg
    assert "PARITY_LLM_MODEL" in msg


def test_successful_call_sends_json_mode_and_temperature_zero():
    seen = []
    llm = GroqLLM(api_key="secret", model="qwen/qwen3-32b", client=fake_groq(seen=seen))
    assert llm.complete_json("sys", "user") == {"answer": "hi"}
    body = json.loads(seen[0].content)
    assert body["model"] == "qwen/qwen3-32b"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert seen[0].headers["Authorization"] == "Bearer secret"


def test_non_json_model_output_is_an_llm_error():
    bad = {"choices": [{"message": {"content": "Sure! Here is the answer..."}}]}
    llm = GroqLLM(api_key="k", model="m", client=fake_groq(chat_body=bad))
    with pytest.raises(LLMError, match="valid JSON"):
        llm.complete_json("sys", "user")
