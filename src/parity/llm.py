"""Minimal chat client for Groq's OpenAI-compatible API.

Reads GROQ_API_KEY from the environment or a .env file in the project root.
The model is configurable with PARITY_LLM_MODEL. Groq retires and renames
models often, so if the configured model is gone, the error lists the models
your key CAN use (also available via `parity models`).

Anything with a `complete_json(system, user) -> dict` method can stand in
for this class (tests use a fake), so Parity never depends on one vendor.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import httpx
from dotenv import load_dotenv

GROQ_BASE = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"  # confirmed available on 2026-09-26
# Models that can't do chat answers (speech, moderation); hidden from suggestions.
NON_CHAT_HINTS = ("whisper", "tts", "guard", "playai", "distil", "orpheus")


class LLMError(RuntimeError):
    pass


class JsonLLM(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict: ...


class GroqLLM:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 60,
        client: httpx.Client | None = None,
    ):
        load_dotenv()
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise LLMError("GROQ_API_KEY is not set. Add it to a .env file in the project folder: GROQ_API_KEY=your_key")
        self.name = model or os.environ.get("PARITY_LLM_MODEL") or DEFAULT_MODEL
        self.client = client or httpx.Client(timeout=timeout)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def list_models(self) -> list[str]:
        """Chat models this API key can use, sorted by name."""
        try:
            r = self.client.get(f"{GROQ_BASE}/models", headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach Groq: {exc}") from exc
        if r.status_code != 200:
            raise LLMError(f"Groq returned {r.status_code} listing models: {r.text[:200]}")
        ids = [m["id"] for m in r.json().get("data", []) if m.get("active", True)]
        return sorted(i for i in ids if not any(h in i.lower() for h in NON_CHAT_HINTS))

    def _model_missing_error(self) -> LLMError:
        try:
            available = self.list_models()
        except LLMError:
            available = []
        hint = f" Models your key can use: {', '.join(available)}." if available else ""
        return LLMError(
            f"Groq has no model '{self.name}' for your key.{hint} "
            f"Pick one and add it to .env as PARITY_LLM_MODEL=<model> (see: uv run parity models)."
        )

    def complete_json(self, system: str, user: str) -> dict:
        payload = {
            "model": self.name,
            "temperature": 0,  # same question, same answer: needed for evals
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            r = self.client.post(f"{GROQ_BASE}/chat/completions", json=payload, headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach Groq: {exc}") from exc
        if r.status_code == 404 and "model_not_found" in r.text:
            raise self._model_missing_error()
        if r.status_code != 200:
            raise LLMError(f"Groq returned {r.status_code}: {r.text[:300]}")
        content = r.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model did not return valid JSON: {content[:200]}") from exc
