import pytest
from playwright.async_api import async_playwright

from parity.agents.images import ImageInfo, audit_images, build_prompt, collect_images, judge, placeholder_problem
from parity.eval.fixture_server import serve_directory
from parity.gemini import GeminiError
from parity.models import Confidence, Source


@pytest.mark.parametrize("alt", ["image", "Image.", "banner", "logo", "photo", "chart_final_v2.png", "IMG_2034", "DSC-0042", "hero.JPG"])
def test_placeholder_and_filename_alts_are_failures(alt):
    assert placeholder_problem(alt)


@pytest.mark.parametrize("alt", [None, "", "Northwind home", "Pie chart of traffic sources", "Logo of Northwind Traders", "Photo of our team"])
def test_real_descriptions_are_not_flagged_by_rules(alt):
    assert placeholder_problem(alt) is None


def img(**kw):
    base = dict(selector="#x", html="<img>", src="https://s/x.png", alt="Photo of our team at the office")
    base.update(kw)
    return ImageInfo(**base)


def test_wrong_alt_with_high_confidence_is_an_ai_finding():
    f, suggestion = judge(img(), {"role": "complex", "alt_verdict": "wrong", "confidence": 0.93,
                                  "reason": "The image is a bar chart.", "description": "A bar chart of sales.",
                                  "suggested_alt": "Bar chart of sales by region"})
    assert f.rule_id == "alt-text-uninformative"
    assert f.confidence == Confidence.ai_high and f.source == Source.vision_agent
    assert f.nodes[0].suggestion == suggestion == "Bar chart of sales by region"
    assert "93%" in f.nodes[0].evidence


def test_low_confidence_goes_to_human_review():
    f, _ = judge(img(), {"alt_verdict": "inadequate", "confidence": 0.55, "reason": "unclear"})
    assert f.confidence == Confidence.needs_review


def test_decorative_image_hiding_information_is_flagged():
    f, _ = judge(img(alt=""), {"role": "text", "alt_verdict": "missing_needed", "confidence": 0.9, "suggested_alt": "Free shipping"})
    assert f.rule_id == "informative-image-hidden"


def test_truly_decorative_empty_alt_is_fine():
    f, _ = judge(img(alt=""), {"role": "decorative", "alt_verdict": "good", "confidence": 0.95})
    assert f is None


def test_missing_alt_is_left_to_axe_but_gets_a_suggestion():
    f, suggestion = judge(img(alt=None), {"role": "informative", "alt_verdict": "missing_needed", "confidence": 0.9, "suggested_alt": "Hero image"})
    assert f is None and suggestion == "Hero image"


def test_rule_finding_works_without_any_model_and_is_auto_verified():
    f, _ = judge(img(alt="banner"), None)
    assert f.confidence == Confidence.auto_verified and f.source == Source.parity_rules
    assert "F30" in f.nodes[0].evidence


def test_garbage_model_answer_does_not_crash():
    f, _ = judge(img(), {"alt_verdict": "wrong", "confidence": "very"})
    assert f.confidence == Confidence.needs_review  # unparseable confidence -> 0 -> human review


def test_prompt_carries_context():
    p = build_prompt(img(alt="", inControl="a", linkText="Offers", linkHref="https://s/offers", heading="Deals"))
    assert 'EMPTY (alt="", marked decorative)' in p
    assert 'link text "Offers", destination https://s/offers' in p
    assert 'nearest heading above it: "Deals"' in p


# ---------------------------------------------------------------- in a real browser


class ScriptedVision:
    name = "scripted"

    def __init__(self, answers, fail=False):
        self.answers, self.fail, self.seen = answers, fail, []

    def judge_json(self, prompt, image, mime):
        self.seen.append(prompt)
        if self.fail:
            raise GeminiError("503 overloaded")
        key = next(k for k in self.answers if f'"{k}"' in prompt or k in prompt)
        return self.answers[key], "scripted"


@pytest.fixture(scope="module")
def base_url():
    with serve_directory() as base:
        yield base


@pytest.fixture
async def page():
    async with async_playwright() as pw:
        try:
            b = await pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        p = await (await b.new_context(viewport={"width": 1366, "height": 900})).new_page()
        yield p
        await b.close()


async def test_collects_images_with_context(base_url, page):
    await page.goto(f"{base_url}/broken/images_quality.html")
    images = {i.selector: i for i in await collect_images(page)}
    assert set(images) == {"#logo2", "#sale-banner", "#promo-text", "#divider", "#visitors-chart", "#sales-bars", "#pie"}
    assert images["#logo2"].inControl == "a" and images["#logo2"].alt == "Northwind home"
    assert images["#promo-text"].alt == ""
    assert images["#sales-bars"].heading == "How we did"
    assert images["#visitors-chart"].filename == "visitors-line.png"


async def test_rules_alone_catch_placeholder_and_filename_alts(base_url, page):
    await page.goto(f"{base_url}/broken/images_quality.html")
    audit = await audit_images(page, vision=None)
    flagged = {n.target for f in audit.findings for n in f.nodes}
    assert flagged == {"#sale-banner", "#visitors-chart"}


async def test_vision_findings_and_suggestions(base_url, page):
    await page.goto(f"{base_url}/broken/images_quality.html")
    good = {"role": "informative", "alt_verdict": "good", "confidence": 0.95, "suggested_alt": ""}
    vision = ScriptedVision({
        "Photo of our team": {"role": "complex", "alt_verdict": "wrong", "confidence": 0.95, "suggested_alt": "Bar chart of sales by region"},
        "promo-text.png": {"role": "text", "alt_verdict": "missing_needed", "confidence": 0.9, "suggested_alt": "Free shipping on orders over $50"},
        "banner": {"role": "text", "alt_verdict": "inadequate", "confidence": 0.9, "suggested_alt": "Spring sale: 30% off"},
        "chart_final_v2.png": {"role": "complex", "alt_verdict": "inadequate", "confidence": 0.9, "suggested_alt": "Line chart of visitors"},
        "Northwind home": good, "divider.png": {"role": "decorative", "alt_verdict": "good", "confidence": 0.95, "suggested_alt": ""},
        "Pie chart": good,
    })
    audit = await audit_images(page, vision=vision)
    by_target = {n.target: (f.rule_id, f.confidence, n.suggestion) for f in audit.findings for n in f.nodes}
    assert by_target["#sales-bars"] == ("alt-text-uninformative", Confidence.ai_high, "Bar chart of sales by region")
    assert by_target["#promo-text"][0] == "informative-image-hidden"
    assert by_target["#sale-banner"][1] == Confidence.auto_verified  # rules decide, vision adds the suggestion
    assert by_target["#sale-banner"][2] == "Spring sale: 30% off"
    assert "#pie" not in by_target and "#divider" not in by_target and "#logo2" not in by_target
    assert audit.judged == 7


async def test_vision_outage_keeps_rule_findings_and_reports_the_problem(base_url, page):
    await page.goto(f"{base_url}/broken/images_quality.html")
    audit = await audit_images(page, vision=ScriptedVision({}, fail=True))
    assert {n.target for f in audit.findings for n in f.nodes} == {"#sale-banner", "#visitors-chart"}
    assert len(audit.errors) == 7 and "overloaded" in audit.errors[0]


async def test_image_cap_protects_quota(base_url, page):
    await page.goto(f"{base_url}/broken/images_quality.html")
    vision = ScriptedVision({"": {"alt_verdict": "good", "confidence": 1}})
    audit = await audit_images(page, vision=vision, max_images=3)
    assert audit.judged == 3
    assert "first 3 of 7 different images" in audit.errors[-1]


# ---------------------------------------------------------------- consistency checks
# Regression (2026-09-27): real gemini-3.1-flash-lite answers that produced 5 false alarms.


def test_self_contradicting_verdict_is_dropped():
    # Gemini: "inadequate" ... reason: "'Northwind home' is appropriate", suggestion identical.
    f, _ = judge(img(alt="Northwind home", inControl="a"), {"role": "functional", "alt_verdict": "inadequate", "confidence": 0.9,
                 "reason": "'Northwind home' is appropriate for a logo link", "suggested_alt": "Northwind home"})
    assert f is None


def test_suggestion_already_inside_current_alt_is_dropped():
    f, _ = judge(img(alt="Northwind Traders logo"), {"role": "informative", "alt_verdict": "inadequate", "confidence": 0.9,
                 "suggested_alt": "Northwind Traders"})
    assert f is None


def test_chart_missing_only_data_points_goes_to_human_review():
    alt = "Line chart of monthly website visitors, January to June 2026, rising from 1,200 to 3,100."
    f, _ = judge(img(alt=alt), {"role": "complex", "alt_verdict": "inadequate", "confidence": 0.95,
                 "suggested_alt": "Line chart of monthly website visitors from January to June 2026: Jan 1,200; Feb 1,500; "
                                  "Mar 1,400; Apr 2,100; May 2,600; Jun 3,100."})
    assert f.confidence == Confidence.needs_review
    assert "W3C allows a short summary" in f.nodes[0].evidence


def test_real_problems_survive_the_checks():
    # Real Mars answers: alt describes something else entirely.
    f, _ = judge(img(alt="Beautiful baboon, blowing bubbles, biking backward", inControl="a"),
                 {"role": "functional", "alt_verdict": "wrong", "confidence": 1, "suggested_alt": "Special Offers"})
    assert f.confidence == Confidence.ai_high
    f, _ = judge(img(alt="Photo of our team at the office"),
                 {"role": "complex", "alt_verdict": "wrong", "confidence": 1,
                  "suggested_alt": "Bar chart showing 2026 sales units by region: North (120), South (80), East (150), West (95)"})
    assert f.confidence == Confidence.ai_high


def test_coverage():
    from parity.agents.images import coverage

    assert coverage("Northwind home", "Northwind home") == 1.0
    assert coverage("banner", "SPRING SALE 30% OFF") == 0.0
    assert coverage("anything", "") == 1.0


def test_prompt_states_w3c_chart_and_link_guidance():
    p = build_prompt(img())
    assert "Listing every data point is NOT required" in p
    assert "identifies the destination is \"good\"" in p


# ---------------------------------------------------------------- real-site regressions
# Found on Deque's Mars demo (2026-09-27): a vertical carousel clones its slides and clips
# them with overflow:hidden. Screenshots of the clipped clones showed whatever sat at their
# position instead (a "1" badge), so the model judged the wrong picture ("It sees: a circle
# with the number 1") and the same image got different suggested alt text on each copy.

class RecordingVision:
    name = "recording"

    def __init__(self):
        self.calls: list[tuple[str, bytes, str]] = []

    def judge_json(self, prompt, image, mime):
        self.calls.append((prompt, image, mime))
        return {"role": "informative", "alt_verdict": "good", "confidence": 0.95, "suggested_alt": ""}, self.name


async def test_clipped_images_are_judged_from_their_own_pixels(base_url, page):
    from parity.eval.fixture_server import FIXTURES_DIR
    await page.goto(f"{base_url}/special/clipped_carousel.html")
    vision = RecordingVision()
    await audit_images(page, vision=vision, allow_private=True)  # fixtures are served from 127.0.0.1
    sent = {prompt.split("file name: ")[1].split()[0]: image for prompt, image, _ in vision.calls}
    assert sent["pie.png"] == (FIXTURES_DIR / "assets" / "pie.png").read_bytes()
    assert sent["sales-bars.png"] == (FIXTURES_DIR / "assets" / "sales-bars.png").read_bytes()


async def test_repeated_images_are_judged_once_and_share_one_answer(base_url, page):
    await page.goto(f"{base_url}/special/clipped_carousel.html")
    vision = RecordingVision()
    audit = await audit_images(page, vision=vision)
    assert len(vision.calls) == 2  # pie.png appears twice with the same alt and link: one call
    assert audit.judged == 2


async def test_rendered_fallback_also_shows_the_image_not_its_cover(base_url, page):
    # SVGs and images we may not fetch directly are drawn by the browser on top of the page.
    import io
    from PIL import Image
    await page.goto(f"{base_url}/special/clipped_carousel.html")
    vision = RecordingVision()
    await audit_images(page, vision=vision, allow_private=False)  # 127.0.0.1 may not be fetched directly
    for _, image, mime in vision.calls:
        assert mime == "image/png"
        r, g, b = Image.open(io.BytesIO(image)).convert("RGB").resize((1, 1)).getpixel((0, 0))
        assert not (r > 180 and g < 60 and b < 60), "captured the red banner covering the image"
