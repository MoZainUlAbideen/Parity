from parity.bot_detection import detect_bot_challenge

NORMAL_TEXT = "Welcome to Northwind. We ship worldwide."


def test_cloudflare_just_a_moment_title():
    c = detect_bot_challenge("Just a moment...", "", [])
    assert c and c.vendor == "Cloudflare"


def test_real_w3c_challenge_text_we_saw():
    # Exactly what the W3C scan returned on 2026-09-25.
    text = "www.w3.org\nPerforming security verification\nThis website uses a security service to protect against malicious bots."
    c = detect_bot_challenge("Some other title", text, [])
    assert c and c.vendor == "Cloudflare"


def test_challenge_script_detected():
    c = detect_bot_challenge("Loading", NORMAL_TEXT, ["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/orchestrate/x"])
    assert c and c.vendor == "Cloudflare"


def test_datadome_script_detected():
    c = detect_bot_challenge("Loading", NORMAL_TEXT, ["https://geo.captcha-delivery.com/captcha/?x=1"])
    assert c and c.vendor == "DataDome"


def test_normal_page_not_flagged():
    assert detect_bot_challenge("Northwind - Home", NORMAL_TEXT, ["https://cdn.jsdelivr.net/npm/x.js"]) is None


def test_article_that_mentions_cloudflare_not_flagged():
    text = "How we moved our DNS to Cloudflare and cut costs. Cloudflare's dashboard is great."
    assert detect_bot_challenge("Our move to Cloudflare", text, ["https://cdnjs.cloudflare.com/ajax/libs/x.js"]) is None


def test_ordinary_just_a_moment_phrase_in_body_not_flagged():
    # Only the exact title is a signal, not the phrase inside page text.
    assert detect_bot_challenge("Recipes", "Just a moment of patience makes great bread.", []) is None
