import pytest
from playwright.async_api import async_playwright

from parity.agents.interaction import audit_interaction, keyboard_walk
from parity.eval.fixture_server import serve_directory
from parity.models import Confidence


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


def found(audit):
    return {(f.rule_id, n.target, f.confidence) for f in audit.findings for n in f.nodes}


async def test_keyboard_walk_visits_focusable_elements_in_order(base_url, page):
    await page.goto(f"{base_url}/clean.html")
    stops = await keyboard_walk(page)
    assert stops[0].endswith("nav:nth-of-type(1) > ul:nth-of-type(1) > li:nth-of-type(1) > a:nth-of-type(1)")
    assert stops[1].endswith("li:nth-of-type(2) > a:nth-of-type(1)")
    assert "#name" in stops and "#msg" in stops


async def test_clickable_div_unreachable_by_keyboard(base_url, page):
    await page.goto(f"{base_url}/broken/links_aria.html")
    audit = await audit_interaction(page)
    assert ("keyboard-inaccessible", "#click-div", Confidence.auto_verified) in found(audit)
    f = next(f for f in audit.findings if f.rule_id == "keyboard-inaccessible")
    assert "never received focus" in f.nodes[0].evidence and f.wcag_criteria == ["2.1.1"]


async def test_identical_read_more_links_to_different_pages(base_url, page):
    await page.goto(f"{base_url}/broken/links_aria.html")
    targets = {t for r, t, _ in found(await audit_interaction(page)) if r == "link-purpose-unclear"}
    assert targets == {"#read-more-1", "#read-more-2"}


async def test_placeholder_only_label(base_url, page):
    await page.goto(f"{base_url}/broken/forms.html")
    assert ("placeholder-as-label", "#phone", Confidence.auto_verified) in found(await audit_interaction(page))


@pytest.mark.parametrize("fixture", ["fixed/links_aria.html", "fixed/forms.html", "clean.html", "fixed/images_quality.html"])
async def test_no_false_alarms_on_correct_pages(base_url, page, fixture):
    await page.goto(f"{base_url}/{fixture}")
    assert (await audit_interaction(page)).findings == []


async def test_same_text_same_destination_is_fine(page):
    await page.set_content('<a href="/a">Read more</a><p>x</p><a href="/a#top">Read more</a>')
    assert (await audit_interaction(page)).findings == []


async def test_descriptive_duplicate_names_go_to_human_review(page):
    await page.set_content('<a href="/a">Pricing</a><a href="/b">Pricing</a>')
    confidences = {f.confidence for f in (await audit_interaction(page)).findings}
    assert confidences == {Confidence.needs_review}


async def test_button_inside_clickable_div_is_not_flagged(page):
    await page.set_content('<div onclick="1"><button>Buy</button></div><div style="cursor:pointer"><a href="/x">Go</a></div>')
    assert (await audit_interaction(page)).findings == []


async def test_malformed_href_does_not_break_the_agent(page):
    await page.set_content('<a href="http://[bad">Read more</a><a href="/b">Read more</a><div onclick="x()">Open</div>')
    rules = {f.rule_id for f in (await audit_interaction(page)).findings}
    assert "keyboard-inaccessible" in rules  # the rest of the page was still audited
