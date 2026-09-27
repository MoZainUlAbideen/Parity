"""Parity's live API.

    POST /api/scans            {"url": "..."}   -> queue a scan, returns {id, status, position}
    GET  /api/scans/{id}                        -> status, and the report when done
    GET  /api/scans/{id}/screenshot/{viewport}  -> annotated-report screenshot (PNG)
    POST /api/ask              {"question": "..."} -> grounded WCAG answer with verified quotes
    GET  /api/health

Built for a small free server (Render free tier, 512 MB):
  - ONE scan at a time through a queue (a real browser is heavy); a short queue
    beyond that returns "busy" instead of falling over
  - per-visitor rate limits protect the Groq/Gemini quotas
  - URLs go through the same SSRF guard as the CLI
  - results and screenshots expire after an hour

Run locally:  uv run uvicorn parity.api.app:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def parse_origins(raw: str) -> list[str]:
    """ "https://site.vercel.app/ , https://b.com" -> ["https://site.vercel.app", "https://b.com"].

    Browsers send Origin without a trailing slash or path, and CORS compares exactly, so
    the natural copy-paste "https://site.vercel.app/" silently blocked every request.
    """
    out = []
    for o in raw.replace(";", ",").split(","):
        o = o.strip().strip('"').strip("'").rstrip("/")
        if o:
            out.append(o)
    return out or ["*"]


# Stage timings ("scan <url> [desktop] rules=4.1s images=22.0s ...") appear in the server logs.
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s %(message)s")


log = logging.getLogger("parity.api")


def cors_rules(origins: list[str]) -> tuple[list[str], str | None]:
    """Exact origins, plus one regex for wildcard entries like https://parity-*.vercel.app
    (Vercel gives every preview deployment its own address)."""
    import re
    exact = [o for o in origins if "*" not in o or o == "*"]
    wild = [o for o in origins if "*" in o and o != "*"]
    pattern = "|".join(re.escape(o).replace(r"\*", "[a-z0-9-]+") for o in wild) or None
    return exact, (f"^(?:{pattern})$" if pattern else None)


def origin_allowed(origin: str, exact: list[str], pattern: str | None) -> bool:
    import re
    return "*" in exact or origin in exact or bool(pattern and re.match(pattern, origin))


class Settings:
    def __init__(self):
        self.allowed_origins = parse_origins(os.environ.get("ALLOWED_ORIGINS", "*"))
        self.scans_per_hour = _env_int("PARITY_SCANS_PER_HOUR", 3)
        self.asks_per_hour = _env_int("PARITY_ASKS_PER_HOUR", 20)
        self.max_queue = _env_int("PARITY_MAX_QUEUE", 5)
        self.max_images = _env_int("PARITY_MAX_IMAGES", 8)
        self.scan_timeout = _env_int("PARITY_SCAN_TIMEOUT", 240)
        self.job_ttl = _env_int("PARITY_JOB_TTL", 3600)
        self.allow_local = os.environ.get("PARITY_ALLOW_LOCAL") == "1"  # tests / local dev only
        self.data_dir = Path(os.environ.get("PARITY_DATA_DIR", "/tmp/parity-scans"))
        self.use_vision = os.environ.get("PARITY_VISION", "1") == "1"


# ---------------------------------------------------------------- rate limiting


class RateLimiter:
    """Sliding one-hour window per visitor, in memory (fine for one small server)."""

    def __init__(self, per_hour: int, window: float = 3600.0):
        self.per_hour, self.window = per_hour, window
        self.hits: dict[str, deque[float]] = {}

    def check(self, key: str, now: float | None = None) -> float:
        """0 if allowed (and recorded), else seconds until the next slot frees up."""
        now = time.monotonic() if now is None else now
        q = self.hits.setdefault(key, deque())
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.per_hour:
            return self.window - (now - q[0])
        q.append(now)
        return 0.0


def client_key(request: Request) -> str:
    # Render (like most hosts) sits behind a proxy; the visitor is the first forwarded address.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


# ---------------------------------------------------------------- jobs


@dataclass
class Job:
    id: str
    url: str
    status: str = "queued"  # queued | running | done | failed | blocked
    created: float = field(default_factory=time.time)
    finished: float | None = None
    report: dict | None = None
    error: str | None = None
    stage: str = ""  # what the scanner is actually doing now (shown on the progress page)


class ScanRequest(BaseModel):
    url: str = Field(min_length=3, max_length=2048)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def public_report(report, job_id: str) -> dict:
    """Report as the website needs it: screenshots as API URLs, heavy internals dropped."""
    data = report.model_dump(mode="json")
    for snap in data["snapshots"]:
        snap.pop("aria_snapshot", None)
        snap["screenshot_url"] = f"/api/scans/{job_id}/screenshot/{snap['viewport']}" if snap.get("screenshot_path") else None
        snap.pop("screenshot_path", None)
    return data


# ---------------------------------------------------------------- app


def create_app(settings: Settings | None = None, vision_factory=None, llm_factory=None, retriever_factory=None) -> FastAPI:
    settings = settings or Settings()
    jobs: dict[str, Job] = {}
    queue: asyncio.Queue[str] = asyncio.Queue()
    scan_limiter = RateLimiter(settings.scans_per_hour)
    ask_limiter = RateLimiter(settings.asks_per_hour)
    state: dict = {"browser": None, "pw": None, "retriever": None}

    def default_vision():
        if not settings.use_vision:
            return None
        from parity.gemini import GeminiError, GeminiVision

        try:
            return GeminiVision(cache_dir=settings.data_dir / "cache")
        except GeminiError:
            return None

    def default_llm():
        from parity.llm import GroqLLM

        return GroqLLM()

    def default_retriever():
        from parity.kb.retriever import Retriever

        return Retriever()  # keyword search + exact lookup: no model download on a small server

    vision_factory = vision_factory or default_vision
    llm_factory = llm_factory or default_llm
    retriever_factory = retriever_factory or default_retriever

    async def get_browser():
        from playwright.async_api import async_playwright

        b = state["browser"]
        if b is None or not b.is_connected():
            if state["pw"] is None:
                state["pw"] = await async_playwright().start()
            state["browser"] = await state["pw"].chromium.launch()
        return state["browser"]

    async def run_job(job: Job) -> None:
        from playwright.async_api import Error as PlaywrightError

        from parity.scanner import AgentOptions, ScanBlockedError, scan_url
        from parity.url_safety import UnsafeURLError

        job.status = "running"
        out_dir = settings.data_dir / job.id
        try:
            browser = await get_browser()
            # Optional checks stop at 55% of the limit, leaving time for the second screen size
            # and the report, so a slow server returns a labelled partial report, not an error.
            options = AgentOptions(vision=vision_factory(), max_images=settings.max_images,
                                   deadline=time.monotonic() + settings.scan_timeout * 0.55,
                                   on_stage=lambda name: setattr(job, "stage", name))
            report = await asyncio.wait_for(
                scan_url(job.url, out_dir=out_dir, allow_private=settings.allow_local, browser=browser, agents=options),
                timeout=settings.scan_timeout,
            )
            job.report, job.status = public_report(report, job.id), "done"
        except ScanBlockedError as exc:
            job.status, job.error = "blocked", str(exc)
        except UnsafeURLError as exc:
            job.status, job.error = "failed", str(exc)
        except asyncio.TimeoutError:
            job.status, job.error = "failed", f"The page took longer than {settings.scan_timeout} seconds to scan."
        except PlaywrightError as exc:
            job.status, job.error = "failed", f"Could not load the page: {str(exc).splitlines()[0][:200]}"
        except Exception as exc:  # never let one bad page kill the worker
            job.status, job.error = "failed", f"Scan failed: {exc.__class__.__name__}"
        finally:
            job.finished = time.time()

    async def worker() -> None:
        while True:
            job_id = await queue.get()
            job = jobs.get(job_id)
            if job is not None:
                await run_job(job)
            queue.task_done()

    async def janitor() -> None:
        while True:
            await asyncio.sleep(300)
            cutoff = time.time() - settings.job_ttl
            for job_id in [j.id for j in jobs.values() if j.finished and j.finished < cutoff]:
                jobs.pop(job_id, None)
                shutil.rmtree(settings.data_dir / job_id, ignore_errors=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        tasks = [asyncio.create_task(worker()), asyncio.create_task(janitor())]
        yield
        for t in tasks:
            t.cancel()
        if state["browser"] is not None:
            await state["browser"].close()
        if state["pw"] is not None:
            await state["pw"].stop()

    app = FastAPI(title="Parity API", version="1.0", lifespan=lifespan)
    exact, pattern = cors_rules(settings.allowed_origins)
    app.add_middleware(CORSMiddleware, allow_origins=exact, allow_origin_regex=pattern,
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.middleware("http")
    async def explain_rejected_origins(request: Request, call_next):
        # Found live (2026-09-27): the browser only says "failed to fetch" and the server log
        # only "OPTIONS /api/scans 400". Say which address was refused and what is allowed.
        origin = request.headers.get("origin")
        if origin and not origin_allowed(origin, exact, pattern):
            log.warning("CORS: refused requests from %s; ALLOWED_ORIGINS allows %s", origin, settings.allowed_origins)
        return await call_next(request)

    def position(job_id: str) -> int:
        waiting = [j.id for j in sorted(jobs.values(), key=lambda j: j.created) if j.status == "queued"]
        return waiting.index(job_id) + 1 if job_id in waiting else 0

    def job_view(job: Job) -> dict:
        return {"id": job.id, "url": job.url, "status": job.status, "position": position(job.id),
                "stage": job.stage, "report": job.report, "error": job.error}

    @app.get("/api/health")
    async def health():
        return {"ok": True, "queued": sum(1 for j in jobs.values() if j.status == "queued"),
                "running": any(j.status == "running" for j in jobs.values())}

    @app.post("/api/scans", status_code=202)
    async def create_scan(body: ScanRequest, request: Request):
        from parity.url_safety import UnsafeURLError, validate_target_url

        try:
            url = await asyncio.to_thread(validate_target_url, body.url, allow_private=settings.allow_local)
        except UnsafeURLError as exc:
            raise HTTPException(400, str(exc))
        waiting = sum(1 for j in jobs.values() if j.status in ("queued", "running"))
        if waiting >= settings.max_queue:
            raise HTTPException(503, "Parity is busy scanning other pages. Please try again in a few minutes.")
        wait = scan_limiter.check(client_key(request))
        if wait:
            raise HTTPException(429, f"You've used this demo's {settings.scans_per_hour} scans for the hour. Try again in {int(wait // 60) + 1} minutes.",
                                headers={"Retry-After": str(int(wait))})
        job = Job(id=uuid.uuid4().hex[:12], url=url)
        jobs[job.id] = job
        await queue.put(job.id)
        return job_view(job)

    @app.get("/api/scans/{job_id}")
    async def get_scan(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Scan not found (results are kept for one hour).")
        return job_view(job)

    @app.get("/api/scans/{job_id}/screenshot/{viewport}")
    async def screenshot(job_id: str, viewport: str):
        job = jobs.get(job_id)
        if job is None or job.report is None or viewport not in ("desktop", "mobile"):
            raise HTTPException(404, "Not found")
        files = list((settings.data_dir / job_id).glob(f"*-{viewport}.png"))
        if not files:
            raise HTTPException(404, "Not found")
        return FileResponse(files[0], media_type="image/png")

    @app.post("/api/ask")
    async def ask_question(body: AskRequest, request: Request):
        from parity.ask import ask
        from parity.llm import LLMError

        wait = ask_limiter.check(client_key(request))
        if wait:
            raise HTTPException(429, f"Too many questions for now. Try again in {int(wait // 60) + 1} minutes.")
        try:
            if state["retriever"] is None:
                state["retriever"] = await asyncio.to_thread(retriever_factory)
            llm = llm_factory()
            answer = await asyncio.to_thread(ask, body.question, state["retriever"], llm)
        except LLMError as exc:
            raise HTTPException(503, f"The assistant is unavailable right now: {exc}")
        return answer.model_dump(mode="json")

    return app


app = create_app()
