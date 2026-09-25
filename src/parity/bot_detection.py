"""Notice when a site's bot protection answered instead of the real page.

Services like Cloudflare show headless browsers a "checking your browser"
page. If we audited that page, we'd hand the customer a confident report
about the wrong page. Parity never tries to get past bot protection; it
detects the challenge and says so. (The fix for a real customer is to
allowlist Parity's scanner on their own site.)

Detection uses strong, specific signals only, so a normal article that
merely mentions Cloudflare is never flagged.
"""

from __future__ import annotations

from dataclasses import dataclass

# (vendor, lowercase marker)
_TITLE_MARKERS = [
    ("Cloudflare", "just a moment..."),
    ("Cloudflare", "attention required! | cloudflare"),
    ("Cloudflare", "access denied | cloudflare"),
    ("Imperva", "pardon our interruption"),
]
_TEXT_MARKERS = [
    ("Cloudflare", "performing security verification"),
    ("Cloudflare", "checking your browser before accessing"),
    ("Cloudflare", "verify you are human by completing the action below"),
    ("DataDome", "please enable js and disable any ad blocker"),
]
_SCRIPT_MARKERS = [
    ("Cloudflare", "challenges.cloudflare.com/cdn-cgi/challenge-platform"),
    ("Cloudflare", "/cdn-cgi/challenge-platform/"),
    ("DataDome", "captcha-delivery.com"),
    ("HUMAN (PerimeterX)", "px-captcha"),
]


@dataclass(frozen=True)
class Challenge:
    vendor: str
    signal: str


def detect_bot_challenge(title: str, body_text: str, script_srcs: list[str]) -> Challenge | None:
    t = (title or "").strip().lower()
    for vendor, marker in _TITLE_MARKERS:
        if t == marker or t.startswith(marker):
            return Challenge(vendor, f"page title '{title.strip()}'")

    text = (body_text or "").lower()[:5000]  # challenge text sits near the top
    for vendor, marker in _TEXT_MARKERS:
        if marker in text:
            return Challenge(vendor, f"page text '{marker}'")

    for src in script_srcs:
        s = src.lower()
        for vendor, marker in _SCRIPT_MARKERS:
            if marker in s:
                return Challenge(vendor, f"challenge script {marker}")
    return None
