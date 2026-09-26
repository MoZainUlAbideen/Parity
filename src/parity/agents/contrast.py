"""Measure contrast of text over background images, from real pixels.

axe-core cannot compute contrast when text sits on a background image or
gradient, so it marks those cases "needs review". Real sites have many (the
Deque Mars demo had 86). A vision model could guess, but here a measurement
is cheaper, deterministic and explainable:

  1. render the element with its text made transparent (background only)
  2. screenshot the element and crop to exactly the area the text covers
  3. compare the text's real color against every background pixel
  4. judge on the worst 5% of the background (the hardest-to-read part),
     against WCAG's threshold: 4.5:1, or 3:1 for large text

Text shadows and outlines can make text readable on busy images in ways a
single ratio can't capture, so those stay "needs review" (with the number).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image

HIDE_STYLE_ID = "parity-hide-text-style"
HIDE_CSS = (
    "[data-parity-hide], [data-parity-hide] * {"
    " color: transparent !important; -webkit-text-fill-color: transparent !important;"
    " text-shadow: none !important; -webkit-text-stroke: 0 !important; caret-color: transparent !important; }"
)
WORST_FRACTION = 0.05
MAX_SAMPLES = 40_000

_INSPECT_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const range = document.createRange();
  range.selectNodeContents(el);
  const t = range.getBoundingClientRect();
  const e = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  return {
    el: {x: e.x, y: e.y, width: e.width, height: e.height},
    text: {x: t.x, y: t.y, width: t.width, height: t.height},
    visible: cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0,
    color: cs.color, fontSize: parseFloat(cs.fontSize), fontWeight: parseInt(cs.fontWeight, 10) || 400,
    textShadow: cs.textShadow, textStroke: cs.webkitTextStrokeWidth || '0px',
  };
}
"""

_HIDE_JS = """
([sel, css, styleId]) => {
  if (!document.getElementById(styleId)) {
    const s = document.createElement('style'); s.id = styleId; s.textContent = css;
    document.head.appendChild(s);
  }
  document.querySelector(sel).setAttribute('data-parity-hide', '');
}
"""

_UNHIDE_JS = """
(sel) => { const el = document.querySelector(sel); if (el) el.removeAttribute('data-parity-hide'); }
"""


def parse_css_color(value: str) -> tuple[float, float, float, float] | None:
    """'rgb(1, 2, 3)' / 'rgba(1, 2, 3, 0.5)' -> (r, g, b, a) with r,g,b in 0..255."""
    m = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)", value or "")
    if not m:
        return None
    a = m.group(4)
    alpha = 1.0 if a is None else (float(a[:-1]) / 100 if a.endswith("%") else float(a))
    return float(m.group(1)), float(m.group(2)), float(m.group(3)), alpha


def _channel(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG relative luminance."""
    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(l1: float, l2: float) -> float:
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def is_large_text(font_size_px: float, font_weight: int) -> bool:
    # WCAG: 18pt (24px) regular, or 14pt (~18.66px) bold
    return font_size_px >= 24 or (font_size_px >= 18.66 and font_weight >= 700)


@dataclass
class ContrastMeasurement:
    target: str
    worst: float  # contrast at the worst 5% of the background
    median: float
    required: float
    verdict: str  # "fail" | "pass" | "inconclusive"
    note: str = ""

    @property
    def evidence(self) -> str:
        text = (
            f"Measured {self.worst:.2f}:1 against the background image (hardest-to-read 5% of the area; "
            f"median {self.median:.2f}:1). WCAG requires {self.required:g}:1 for this text size."
        )
        return f"{text} {self.note}".strip()


def measure_pixels(png: bytes, text_rgba: tuple[float, float, float, float]) -> tuple[float, float]:
    """Contrast between a text color and every pixel of a background-only image.

    Returns (worst-5% ratio, median ratio). Semi-transparent text is blended
    with each pixel, as the browser would draw it.
    """
    img = Image.open(io.BytesIO(png)).convert("RGB")
    # get_flattened_data() replaces getdata(), which Pillow 14 removes; older Pillow only has getdata().
    pixels = list(img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata())
    step = max(1, len(pixels) // MAX_SAMPLES)
    tr, tg, tb, ta = text_rgba
    ratios = []
    for r, g, b in pixels[::step]:
        text_rgb = (ta * tr + (1 - ta) * r, ta * tg + (1 - ta) * g, ta * tb + (1 - ta) * b)
        ratios.append(contrast_ratio(luminance(text_rgb), luminance((r, g, b))))
    ratios.sort()
    worst = ratios[min(len(ratios) - 1, int(len(ratios) * WORST_FRACTION))]
    return worst, ratios[len(ratios) // 2]


def text_crop_box(el: dict, text: dict, img_w: int, img_h: int) -> tuple[int, int, int, int] | None:
    """Where the text sits inside a screenshot of its element, in image pixels.

    Works from PROPORTIONS of the element box, so it stays right at any zoom.
    Regression (2026-09-26, Deque Mars on mobile): pages without a viewport meta
    tag are laid out ~980px wide and zoomed out on phones; cropping the screen by
    CSS coordinates landed outside the 390px screenshot and crashed the scan.
    """
    if el["width"] <= 0 or el["height"] <= 0 or text["width"] <= 0 or text["height"] <= 0:
        return None
    sx, sy = img_w / el["width"], img_h / el["height"]
    left = max(0, round((text["x"] - el["x"]) * sx))
    top = max(0, round((text["y"] - el["y"]) * sy))
    right = min(img_w, round((text["x"] + text["width"] - el["x"]) * sx))
    bottom = min(img_h, round((text["y"] + text["height"] - el["y"]) * sy))
    if right - left < 1 or bottom - top < 1:
        return None
    return left, top, right, bottom


async def measure_text_over_image(page, selector: str, timeout_ms: int = 5000) -> ContrastMeasurement | None:
    """Measure one element. None if it can't be located or has no visible text box."""
    if ">>>" in selector or "|" in selector:  # shadow DOM / iframe targets: not supported yet
        return None
    info = await page.evaluate(_INSPECT_JS, selector)
    if not info or not info["visible"] or info["el"]["width"] < 1 or info["text"]["width"] < 1:
        return None
    color = parse_css_color(info["color"])
    if color is None:
        return None

    await page.evaluate(_HIDE_JS, [selector, HIDE_CSS, HIDE_STYLE_ID])
    try:
        # The element screenshot lets the browser handle scrolling and zoom.
        shot = await page.locator(f"css={selector}").first.screenshot(animations="disabled", timeout=timeout_ms)
        # Positions are read again AFTER scrolling into view, from the same layout the
        # screenshot shows. Only positions: while hidden, styles like text-shadow read
        # as "none" (regression caught by test_text_shadow_makes_it_a_human_call).
        again = await page.evaluate(_INSPECT_JS, selector)
        if again:
            info = {**info, "el": again["el"], "text": again["text"]}
    finally:
        await page.evaluate(_UNHIDE_JS, selector)

    img = Image.open(io.BytesIO(shot))
    box = text_crop_box(info["el"], info["text"], img.width, img.height)
    if box is None:
        return None
    buf = io.BytesIO()
    img.crop(box).save(buf, format="PNG")

    worst, median = measure_pixels(buf.getvalue(), color)
    required = 3.0 if is_large_text(info["fontSize"], info["fontWeight"]) else 4.5
    has_effects = info["textShadow"] not in ("none", "") or info["textStroke"] not in ("0px", "0", "")
    if has_effects:
        verdict, note = "inconclusive", "The text has a shadow or outline, which can make it readable anyway; a human should check."
    else:
        verdict, note = ("pass" if worst >= required else "fail"), ""
    return ContrastMeasurement(target=selector, worst=worst, median=median, required=required, verdict=verdict, note=note)
