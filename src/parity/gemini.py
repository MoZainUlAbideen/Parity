"""Gemini vision client, built for a crowded free tier.

Google's free Gemini models are often overloaded (HTTP 503) or rate-limited
(HTTP 429). This client:
  - retries busy responses with exponential backoff
  - falls back through a list of models (PARITY_VISION_MODELS, comma-separated)
  - spaces calls out (PARITY_VISION_MIN_INTERVAL seconds) to respect rate limits
  - caches every answer on disk, keyed by model + prompt + image bytes, so the
    same image is never paid for twice (re-scans and evals are free)
  - lists the models your key can use when a configured model doesn't exist

Reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment or .env.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import httpx
from dotenv import load_dotenv

API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODELS = ["gemini-3.1-flash-lite"]  # the one that worked reliably for Rehnuma (2026-09-26)
BUSY_STATUSES = {429, 500, 502, 503, 504}


class GeminiError(RuntimeError):
    pass


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


class GeminiVision:
    def __init__(
        self,
        models: list[str] | None = None,
        api_key: str | None = None,
        cache_dir: Path | None = None,
        client: httpx.Client | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        min_interval: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        load_dotenv()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY is not set. Add it to .env in the project folder: GEMINI_API_KEY=your_key")
        env_models = [m.strip() for m in os.environ.get("PARITY_VISION_MODELS", "").split(",") if m.strip()]
        self.models = models or env_models or list(DEFAULT_MODELS)
        self.cache_dir = cache_dir
        self.client = client or httpx.Client(timeout=90)
        self.max_retries = max_retries
        self.backoff = backoff_seconds
        self.min_interval = float(os.environ.get("PARITY_VISION_MIN_INTERVAL", 2.0)) if min_interval is None else min_interval
        self.sleep = sleep
        self._last_call = 0.0
        self.calls = 0  # network calls actually made (cache hits don't count)

    @property
    def name(self) -> str:
        return self.models[0]

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    # ------------------------------------------------------------------ cache

    def _cache_path(self, model: str, prompt: str, image: bytes) -> Path | None:
        if not self.cache_dir:
            return None
        key = hashlib.sha256(model.encode() + b"\0" + prompt.encode("utf-8") + b"\0" + image).hexdigest()[:24]
        return self.cache_dir / "vision" / f"{key}.json"

    # ------------------------------------------------------------------ API

    def list_models(self) -> list[str]:
        """Models your key can use for generateContent, e.g. 'gemini-3.1-flash-lite'."""
        try:
            r = self.client.get(f"{API}/models", params={"pageSize": 1000}, headers=self._headers)
        except httpx.HTTPError as exc:
            raise GeminiError(f"Could not reach Gemini: {exc}") from exc
        if r.status_code != 200:
            raise GeminiError(f"Gemini returned {r.status_code} listing models: {r.text[:200]}")
        names = []
        for m in r.json().get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(m["name"].removeprefix("models/"))
        return sorted(names)

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            self.sleep(wait)
        self._last_call = time.monotonic()

    def _call(self, model: str, prompt: str, image: bytes, mime: str) -> httpx.Response:
        body = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": mime, "data": base64.b64encode(image).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        self._throttle()
        self.calls += 1
        try:
            return self.client.post(f"{API}/models/{model}:generateContent", json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise GeminiError(f"Could not reach Gemini: {exc}") from exc

    @staticmethod
    def _parse(resp: httpx.Response) -> dict:
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise GeminiError(f"Gemini returned no answer ({reason})")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            return json.loads(_strip_fences(text))
        except json.JSONDecodeError as exc:
            raise GeminiError(f"Gemini did not return valid JSON: {text[:200]}") from exc

    def judge_json(self, prompt: str, image: bytes, mime: str = "image/png") -> tuple[dict, str]:
        """Ask about one image. Returns (parsed JSON answer, model that answered)."""
        for model in self.models:  # a cached answer from any configured model is reused
            path = self._cache_path(model, prompt, image)
            if path and path.exists():
                return json.loads(path.read_text(encoding="utf-8")), model

        missing, busy = [], []
        for model in self.models:
            for attempt in range(self.max_retries + 1):
                resp = self._call(model, prompt, image, mime)
                if resp.status_code == 200:
                    answer = self._parse(resp)
                    path = self._cache_path(model, prompt, image)
                    if path:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(answer), encoding="utf-8")
                    return answer, model
                if resp.status_code == 404:
                    missing.append(model)
                    break
                if resp.status_code in BUSY_STATUSES:
                    if attempt < self.max_retries:
                        self.sleep(self.backoff * 2**attempt)
                        continue
                    busy.append(model)
                    break
                raise GeminiError(f"Gemini returned {resp.status_code} for {model}: {resp.text[:300]}")

        parts = []
        if busy:
            parts.append(f"busy or rate-limited after {self.max_retries} retries: {', '.join(busy)}")
        if missing:
            try:
                available = self.list_models()
            except GeminiError:
                available = []
            hint = f" Models your key can use: {', '.join(available)}." if available else ""
            parts.append(f"not found: {', '.join(missing)}.{hint}")
        raise GeminiError(
            "No Gemini model answered (" + "; ".join(parts) + "). Set PARITY_VISION_MODELS in .env to one or more "
            "models, comma-separated, most preferred first (see: uv run parity models --provider gemini)."
        )
