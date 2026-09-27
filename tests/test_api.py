"""The live API, end to end with a real browser against the local fixture pages."""

import time

import pytest
from fastapi.testclient import TestClient

from parity.api.app import RateLimiter, Settings, create_app
from parity.eval.fixture_server import serve_directory


@pytest.fixture(scope="module")
def base_url():
    with serve_directory() as base:
        yield base


def make_settings(tmp_path, **kw):
    s = Settings()
    s.allow_local = True
    s.data_dir = tmp_path
    s.use_vision = False
    s.scans_per_hour = kw.get("scans_per_hour", 10)
    s.asks_per_hour = kw.get("asks_per_hour", 10)
    s.max_queue = kw.get("max_queue", 5)
    return s


def wait_for(client, job_id, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/scans/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.5)
    raise AssertionError("scan did not finish")


def test_rate_limiter_window():
    rl = RateLimiter(per_hour=2)
    assert rl.check("a", now=0) == 0 and rl.check("a", now=1) == 0
    assert rl.check("a", now=2) == pytest.approx(3598)
    assert rl.check("b", now=2) == 0  # other visitors unaffected
    assert rl.check("a", now=3601) == 0  # window slid


def test_scan_end_to_end(base_url, tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        r = client.post("/api/scans", json={"url": f"{base_url}/broken/contrast_images.html"})
        assert r.status_code == 202 and r.json()["status"] in ("queued", "running")
        job = wait_for(client, r.json()["id"])
        assert job["status"] == "done", job["error"]
        report = job["report"]
        rules = {f["rule_id"] for f in report["findings"]}
        assert "contrast-over-image" in rules
        assert report["resolved"] and "aria_snapshot" not in report["snapshots"][0]
        shot = client.get(report["snapshots"][0]["screenshot_url"])
        assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"


def test_bot_protected_page_is_reported_as_blocked(base_url, tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        job = wait_for(client, client.post("/api/scans", json={"url": f"{base_url}/special/bot_challenge.html"}).json()["id"])
        assert job["status"] == "blocked" and "Cloudflare" in job["error"]


def test_internal_addresses_are_refused(tmp_path):
    settings = make_settings(tmp_path)
    settings.allow_local = False
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/scans", json={"url": "http://169.254.169.254/latest/meta-data"})
        assert r.status_code == 400 and "internal" in r.json()["detail"]


def test_per_visitor_scan_limit(base_url, tmp_path):
    with TestClient(create_app(make_settings(tmp_path, scans_per_hour=1))) as client:
        url = f"{base_url}/clean.html"
        assert client.post("/api/scans", json={"url": url}, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 202
        r = client.post("/api/scans", json={"url": url}, headers={"x-forwarded-for": "1.1.1.1"})
        assert r.status_code == 429 and "Retry-After" in r.headers
        assert client.post("/api/scans", json={"url": url}, headers={"x-forwarded-for": "2.2.2.2"}).status_code == 202


def test_busy_server_says_so_instead_of_falling_over(base_url, tmp_path):
    with TestClient(create_app(make_settings(tmp_path, max_queue=1))) as client:
        client.post("/api/scans", json={"url": f"{base_url}/clean.html"})
        r = client.post("/api/scans", json={"url": f"{base_url}/clean.html"})
        assert r.status_code == 503 and "busy" in r.json()["detail"]


def test_unknown_scan_is_404(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.get("/api/scans/nope").status_code == 404


class FakeLLM:
    name = "fake"

    def complete_json(self, system, user):
        return {"answerable": True, "answer": "Targets must be at least 24 by 24 CSS pixels.",
                "citations": [{"passage": "P1", "quote": "at least 24 by 24 CSS pixels"}]}


def test_ask_returns_verified_answer(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), llm_factory=FakeLLM)) as client:
        r = client.post("/api/ask", json={"question": "What does 2.5.8 require?"})
        assert r.status_code == 200
        body = r.json()
        assert body["grounded"] and body["citations"][0]["sc"] == "2.5.8"


def test_ask_without_key_is_a_clear_503(tmp_path):
    from parity.llm import LLMError

    def no_key():
        raise LLMError("GROQ_API_KEY is not set.")

    with TestClient(create_app(make_settings(tmp_path), llm_factory=no_key)) as client:
        r = client.post("/api/ask", json={"question": "What does 2.5.8 require?"})
        assert r.status_code == 503 and "unavailable" in r.json()["detail"]


def test_health(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.get("/api/health").json()["ok"] is True


def test_allowed_origins_forgive_trailing_slashes_and_spaces():
    from parity.api.app import parse_origins
    assert parse_origins(" https://parity.vercel.app/ ,https://b.com") == ["https://parity.vercel.app", "https://b.com"]
    assert parse_origins("") == ["*"]


def test_browser_preflight_from_the_website_is_allowed(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://parity.vercel.app/")
    from fastapi.testclient import TestClient
    from parity.api.app import Settings, create_app
    client = TestClient(create_app(Settings()))
    r = client.options("/api/ask", headers={"Origin": "https://parity.vercel.app",
                                            "Access-Control-Request-Method": "POST",
                                            "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://parity.vercel.app"


def test_wildcard_origins_cover_vercel_preview_addresses():
    from parity.api.app import cors_rules, origin_allowed
    exact, pattern = cors_rules(["https://parity-iota-puce.vercel.app", "https://parity-*.vercel.app"])
    assert origin_allowed("https://parity-iota-puce.vercel.app", exact, pattern)
    assert origin_allowed("https://parity-git-main-zain.vercel.app", exact, pattern)
    assert not origin_allowed("https://evil.example", exact, pattern)
    assert not origin_allowed("https://parity-x.vercel.app.evil.example", exact, pattern)


def test_refused_origin_is_named_in_the_logs(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://parity.vercel.app")
    from fastapi.testclient import TestClient
    from parity.api.app import Settings, create_app
    client = TestClient(create_app(Settings()))
    with caplog.at_level(logging.WARNING, logger="parity.api"):
        r = client.options("/api/scans", headers={"Origin": "https://other.vercel.app",
                                                  "Access-Control-Request-Method": "POST"})
    assert r.status_code == 400
    assert "https://other.vercel.app" in caplog.text
