"""Image agent: is each image's text alternative actually right?

axe only checks that an alt attribute EXISTS. alt="banner" on an image of
"SPRING SALE 30% OFF" passes axe but tells a blind shopper nothing. This agent
works in two layers:

1. Rules (free, deterministic, no model): alt text that is a placeholder word
   or a file name is always a failure. W3C documents it as failure F30,
   "text alternatives that are not alternatives (e.g., filenames or
   placeholder text)". Confidence: auto-verified.

2. Vision (Gemini, optional): looks at the image with its context and judges
   whether the alt text conveys the same information; whether an image
   marked decorative (alt="") actually carries information; and proposes
   alt text. Confidence: ai-high-confidence at >= 0.8, otherwise needs-review.
   Every image also gets a suggested alt text, which the fixer (milestone 6)
   will turn into a code change.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from parity.gemini import GeminiError, GeminiVision
from parity.models import Confidence, Finding, Impact, NodeRef, Source

HIGH_CONFIDENCE = 0.8
MIN_SIZE_PX = 16
PLACEHOLDER_ALTS = {
    "image", "img", "photo", "picture", "pic", "graphic", "icon", "banner", "logo", "chart",
    "spacer", "placeholder", "untitled", "alt", "alt text", "image description", "thumbnail",
}
FILENAME_ALT = re.compile(r"^[\w\-. ]+\.(png|jpe?g|gif|svg|webp|avif|bmp|tiff?)$|^(img|dsc|image|screenshot)[_\- ]?\d+", re.I)

_COLLECT_JS = r"""
(minSize) => {
  const uniqueSelector = (el) => {
    if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      if (node.id && document.querySelectorAll('#' + CSS.escape(node.id)).length === 1) {
        parts.unshift('#' + CSS.escape(node.id)); break;
      }
      let i = 1, sib = node;
      while ((sib = sib.previousElementSibling)) if (sib.tagName === node.tagName) i++;
      parts.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'));
  const out = [];
  for (const img of document.querySelectorAll('img, input[type=image]')) {
    const r = img.getBoundingClientRect();
    const cs = getComputedStyle(img);
    if (r.width < minSize || r.height < minSize || cs.visibility === 'hidden' || cs.display === 'none') continue;
    const link = img.closest('a[href], button');
    let linkText = '';
    if (link) {
      const copy = link.cloneNode(true);
      copy.querySelectorAll('img').forEach(i => i.remove());
      linkText = clean(copy.textContent);
    }
    const fig = img.closest('figure');
    let heading = '';
    for (const h of headings) {
      if (h.compareDocumentPosition(img) & Node.DOCUMENT_POSITION_FOLLOWING) heading = clean(h.textContent);
    }
    const parent = img.parentElement;
    let nearby = '';
    if (parent) {
      const copy = parent.cloneNode(true);
      copy.querySelectorAll('img').forEach(i => i.remove());
      nearby = clean(copy.textContent).slice(0, 300);
    }
    out.push({
      selector: uniqueSelector(img),
      html: img.outerHTML.slice(0, 300),
      src: img.currentSrc || img.src || '',
      alt: img.hasAttribute('alt') ? img.getAttribute('alt') : null,
      role: img.getAttribute('role') || '',
      ariaLabel: img.getAttribute('aria-label') || '',
      ariaHidden: img.closest('[aria-hidden="true"]') !== null,
      inControl: link ? link.tagName.toLowerCase() : '',
      linkHref: link && link.href ? link.href : '',
      linkText,
      caption: fig ? clean((fig.querySelector('figcaption') || {}).textContent) : '',
      heading,
      nearby,
      width: Math.round(r.width), height: Math.round(r.height),
    });
  }
  return out;
}
"""


class ImageInfo(BaseModel):
    selector: str
    html: str
    src: str
    alt: str | None
    role: str = ""
    ariaLabel: str = ""
    ariaHidden: bool = False
    inControl: str = ""
    linkHref: str = ""
    linkText: str = ""
    caption: str = ""
    heading: str = ""
    nearby: str = ""
    width: int = 0
    height: int = 0

    @property
    def filename(self) -> str:
        return self.src.split("?")[0].rstrip("/").split("/")[-1]


def placeholder_problem(alt: str | None) -> str | None:
    """Why this alt text is not an alternative at all, or None if it might be fine."""
    if alt is None or not alt.strip():
        return None
    norm = re.sub(r"[^\w\s]", "", alt).strip().lower()
    if norm in PLACEHOLDER_ALTS:
        return f'the alt text "{alt}" is a placeholder word, not a description'
    if FILENAME_ALT.search(alt.strip()):
        return f'the alt text "{alt}" is a file name, not a description'
    return None


VISION_PROMPT = """You are an accessibility auditor checking one web image against WCAG 2.2 success criterion 1.1.1 Non-text Content.

The attached image appears on a web page. Its context:
- alt attribute: {alt}
- inside a {control}: {link}
- figure caption: {caption}
- nearest heading above it: {heading}
- text next to it: {nearby}
- file name: {filename}

Decide:
1. "role": one of
   "decorative" (adds no information; purely visual styling),
   "informative" (conveys information: a photo, illustration or logo),
   "text" (mainly an image of text),
   "complex" (chart, graph, diagram or map),
   "functional" (the only content of a link or button; its alt must say where it goes or what it does).
2. "visible_text": any text readable in the image, exactly as written, or "".
3. "description": one sentence describing what the image shows.
4. "alt_verdict": one of
   "good" (the alt conveys the same information or purpose; for a decorative image an empty alt is good; if the text next to the image already conveys its information, an empty alt is also good),
   "missing_needed" (alt is missing or empty, but the image conveys information not available in the surrounding text),
   "inadequate" (alt is present but too vague or incomplete, e.g. it omits the text shown in the image or a chart's key data),
   "wrong" (alt describes something different from what the image shows),
   "should_be_empty" (decorative image that has non-empty alt text).
5. "suggested_alt": the alt text you recommend ("" for decorative images). For images of text, include the text exactly. For charts, give the type and the key data in one or two sentences. For functional images, describe the destination or action.
6. "confidence": a number from 0 to 1 for how sure you are of alt_verdict.
7. "reason": one short sentence explaining the verdict, in plain language.

Reply with JSON only, with exactly these keys."""


def build_prompt(img: ImageInfo) -> str:
    def q(v: str) -> str:
        return f'"{v}"' if v else "(none)"

    alt = "MISSING (no alt attribute)" if img.alt is None else ('EMPTY (alt="", marked decorative)' if not img.alt.strip() else f'"{img.alt}"')
    control = img.inControl or "link or button"
    link = f"link text {q(img.linkText)}, destination {img.linkHref}" if img.inControl else "(not inside a link or button)"
    return VISION_PROMPT.format(alt=alt, control=control, link=link, caption=q(img.caption), heading=q(img.heading), nearby=q(img.nearby), filename=img.filename or "(unknown)")


@dataclass
class ImageAudit:
    findings: list[Finding] = field(default_factory=list)
    suggestions: dict[str, str] = field(default_factory=dict)  # selector -> suggested alt (for axe's image-alt nodes)
    judged: int = 0
    errors: list[str] = field(default_factory=list)


def _finding(rule_id: str, img: ImageInfo, help_text: str, description: str, confidence: Confidence, source: Source,
             evidence: str, suggestion: str, impact: Impact = Impact.serious) -> Finding:
    return Finding(
        rule_id=rule_id, description=description, help=help_text,
        help_url="https://www.w3.org/WAI/WCAG22/Techniques/failures/F30" if rule_id == "alt-text-uninformative" else
                 "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
        impact=impact, wcag_criteria=["1.1.1"], wcag_level="A", source=source, confidence=confidence,
        nodes=[NodeRef(target=img.selector, html=img.html, evidence=evidence, suggestion=suggestion)],
    )


def judge(img: ImageInfo, answer: dict | None) -> tuple[Finding | None, str]:
    """Turn rules + (optional) vision answer into at most one finding, plus a suggested alt."""
    suggestion = str((answer or {}).get("suggested_alt", "")).strip()
    rule_problem = placeholder_problem(img.alt)
    if rule_problem:
        reason = (answer or {}).get("reason", "")
        evidence = f"{rule_problem[0].upper()}{rule_problem[1:]} (W3C failure F30)." + (f" Vision check: {reason}" if reason else "")
        return _finding(
            "alt-text-uninformative", img, "Alt text must describe the image, not name it",
            "The image's text alternative is a placeholder or file name, so screen-reader users get no information.",
            Confidence.auto_verified, Source.parity_rules, evidence, suggestion,
        ), suggestion
    if not answer:
        return None, suggestion

    verdict = str(answer.get("alt_verdict", "")).strip().lower()
    role = str(answer.get("role", "")).strip().lower()
    try:
        confidence = float(answer.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    level = Confidence.ai_high if confidence >= HIGH_CONFIDENCE else Confidence.needs_review
    evidence = f"Vision model ({confidence:.0%} sure): {answer.get('reason', '').strip()} It sees: {answer.get('description', '').strip()}"
    has_alt = img.alt is not None and img.alt.strip() != ""

    if has_alt and verdict in ("inadequate", "wrong"):
        what = "describes something else" if verdict == "wrong" else "leaves out what the image communicates"
        return _finding(
            "alt-text-uninformative", img, "Alt text must convey the same information as the image",
            f"The image's text alternative {what}.", level, Source.vision_agent, evidence, suggestion,
        ), suggestion
    if img.alt is not None and not img.alt.strip() and not img.ariaLabel and verdict == "missing_needed" and role != "decorative":
        return _finding(
            "informative-image-hidden", img, "Informative images must not be marked decorative",
            'The image is marked decorative (alt="") but conveys information screen-reader users will miss.',
            level, Source.vision_agent, evidence, suggestion,
        ), suggestion
    return None, suggestion


async def collect_images(page) -> list[ImageInfo]:
    raw = await page.evaluate(_COLLECT_JS, MIN_SIZE_PX)
    return [ImageInfo.model_validate(r) for r in raw]


async def audit_images(page, vision: GeminiVision | None = None, max_images: int = 15) -> ImageAudit:
    audit = ImageAudit()
    images = [i for i in await collect_images(page) if not i.ariaHidden and i.role not in ("presentation", "none")]
    for n, img in enumerate(images):
        answer = None
        if vision is not None and n < max_images:
            try:
                shot = await page.locator(img.selector).first.screenshot(type="png", animations="disabled")
                answer, _ = await asyncio.to_thread(vision.judge_json, build_prompt(img), shot, "image/png")
                audit.judged += 1
            except GeminiError as exc:
                audit.errors.append(f"{img.selector}: {exc}")
            except Exception as exc:  # element vanished, screenshot failed, etc.
                audit.errors.append(f"{img.selector}: could not capture image ({exc.__class__.__name__})")
        finding, suggestion = judge(img, answer)
        if finding:
            audit.findings.append(finding)
        if suggestion:
            audit.suggestions[img.selector] = suggestion
    if vision is not None and len(images) > max_images:
        audit.errors.append(f"Checked the first {max_images} of {len(images)} images to protect your API quota.")
    return audit
