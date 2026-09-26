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
    assert "first 3 of 7" in audit.errors[-1]
