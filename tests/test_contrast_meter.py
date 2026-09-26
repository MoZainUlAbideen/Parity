import io
import math

import pytest
from PIL import Image
from playwright.async_api import async_playwright

from parity.agents.contrast import (
    contrast_ratio,
    is_large_text,
    luminance,
    measure_pixels,
    measure_text_over_image,
    parse_css_color,
)
from parity.eval.fixture_server import serve_directory


def png(colors_by_half):
    img = Image.new("RGB", (100, 10))
    for x in range(100):
        for y in range(10):
            img.putpixel((x, y), colors_by_half[0] if x < 50 else colors_by_half[1])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_parse_css_color():
    assert parse_css_color("rgb(255, 0, 10)") == (255, 0, 10, 1.0)
    assert parse_css_color("rgba(0, 0, 0, 0.5)") == (0, 0, 0, 0.5)
    assert parse_css_color("rgb(1 2 3 / 50%)") == (1, 2, 3, 0.5)
    assert parse_css_color("transparent") is None


def test_wcag_contrast_reference_values():
    white, black = luminance((255, 255, 255)), luminance((0, 0, 0))
    assert math.isclose(contrast_ratio(white, black), 21.0)
    # #767676 on white is the classic "just passes 4.5:1" grey
    assert contrast_ratio(luminance((0x76, 0x76, 0x76)), white) == pytest.approx(4.54, abs=0.01)


def test_large_text_thresholds():
    assert is_large_text(24, 400)
    assert is_large_text(18.7, 700)
    assert not is_large_text(18.7, 400)
    assert not is_large_text(16, 700)


def test_worst_part_of_background_decides():
    # White text: left half black background (21:1), right half light grey (1.1:1).
    worst, median = measure_pixels(png([(0, 0, 0), (240, 240, 240)]), (255, 255, 255, 1.0))
    assert worst < 1.2  # the unreadable half is what counts
    assert median > 1.0


def test_semi_transparent_text_is_blended_with_background():
    # 50%-transparent white over black renders as mid grey, not white.
    worst, _ = measure_pixels(png([(0, 0, 0), (0, 0, 0)]), (255, 255, 255, 0.5))
    assert 4 < worst < 6  # ~5.3:1, far below the 21:1 of solid white


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


async def test_dark_text_on_dark_photo_fails_and_light_text_passes(base_url, page):
    await page.goto(f"{base_url}/broken/contrast_images.html")
    dark = await measure_text_over_image(page, "#dark-on-dark")
    light = await measure_text_over_image(page, "#light-on-dark")
    assert dark.verdict == "fail" and dark.worst < 2.5 and dark.required == 4.5
    assert light.verdict == "pass" and light.worst > 10
    assert "WCAG requires 4.5:1" in dark.evidence


async def test_text_is_restored_after_measuring(base_url, page):
    await page.goto(f"{base_url}/broken/contrast_images.html")
    await measure_text_over_image(page, "#light-on-dark")
    color = await page.evaluate("getComputedStyle(document.querySelector('#light-on-dark')).color")
    assert color == "rgb(255, 255, 255)"


async def test_text_shadow_makes_it_a_human_call(base_url, page):
    await page.goto(f"{base_url}/special/contrast_shadow.html")
    m = await measure_text_over_image(page, "#shadowed")
    assert m.verdict == "inconclusive"
    assert "shadow" in m.evidence


async def test_missing_element_returns_none(base_url, page):
    await page.goto(f"{base_url}/broken/contrast_images.html")
    assert await measure_text_over_image(page, "#does-not-exist") is None


def test_crop_box_uses_proportions_so_zoom_does_not_matter():
    from parity.agents.contrast import text_crop_box

    el = {"x": 100, "y": 200, "width": 400, "height": 100}
    text = {"x": 150, "y": 220, "width": 200, "height": 40}
    assert text_crop_box(el, text, 400, 100) == (50, 20, 250, 60)  # 1:1
    assert text_crop_box(el, text, 160, 40) == (20, 8, 100, 24)  # page zoomed to 0.4
    assert text_crop_box(el, {"x": 0, "y": 0, "width": 0, "height": 0}, 400, 100) is None


async def test_zoomed_out_mobile_page_is_measured_not_crashed(base_url):
    """Regression (2026-09-26, Deque Mars): no viewport meta tag -> phones lay the page out
    ~980px wide at ~0.4x zoom; the old crop landed outside the screenshot and crashed the scan."""
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        await page.goto(f"{base_url}/special/no_meta_viewport.html")
        assert await page.evaluate("visualViewport.scale") < 0.5  # really zoomed out
        dark = await measure_text_over_image(page, "#right-dark-text")
        light = await measure_text_over_image(page, "#right-light-text")
        far = await measure_text_over_image(page, "#far-down-text")
        await b.close()
    assert dark.verdict == "fail" and light.verdict == "pass" and far.verdict == "fail"
