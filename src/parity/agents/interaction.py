"""Interaction agent: use the page the way a keyboard user would.

No AI needed; these are behaviours, so we test them directly:

1. Keyboard walk: press Tab through the whole page and record every stop,
   exactly as someone who can't use a mouse would move through it.
2. Clickable but unreachable (WCAG 2.1.1 Keyboard): elements with a click
   handler that are not links, buttons or form controls and never received
   focus during the walk. Mouse users can use them; keyboard users can't.
3. Ambiguous links (WCAG 2.4.4 Link Purpose): the same generic text ("Read
   more", "Click here") leading to different pages. A screen-reader user
   listing the page's links hears identical names.
4. Placeholder as the only label (WCAG 3.3.2 Labels or Instructions): the
   hint vanishes as soon as you type, so you forget what the field was for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parity.models import Confidence, Finding, Impact, NodeRef, Source

MAX_TAB_STOPS = 200
GENERIC_LINK_TEXT = {
    "read more", "more", "click here", "here", "learn more", "details", "more info", "more information",
    "link", "this link", "continue", "go", "see more", "view more", "find out more",
}

_SELECTOR_JS = r"""
window.__paritySelector = (el) => {
  if (!el || el.nodeType !== 1) return '';
  if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) return '#' + CSS.escape(el.id);
  const parts = [];
  let node = el;
  while (node && node.nodeType === 1 && node !== document.documentElement) {
    if (node.id && document.querySelectorAll('#' + CSS.escape(node.id)).length === 1) { parts.unshift('#' + CSS.escape(node.id)); break; }
    let i = 1, sib = node;
    while ((sib = sib.previousElementSibling)) if (sib.tagName === node.tagName) i++;
    parts.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
    node = node.parentElement;
  }
  return parts.join(' > ');
};
"""

_ACTIVE_JS = "() => { const a = document.activeElement; return (!a || a === document.body) ? '' : window.__paritySelector(a); }"

_CANDIDATES_JS = r"""
() => {
  const NATIVE = 'a[href],button,input,select,textarea,summary,label,option,iframe,[contenteditable=""],[contenteditable="true"]';
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const out = {clickables: [], links: [], placeholders: []};

  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || el.matches(NATIVE) || el.closest(NATIVE) || el.querySelector(NATIVE)) continue;
    const hasOnclick = el.hasAttribute('onclick');
    const cs = getComputedStyle(el), parentCursor = el.parentElement ? getComputedStyle(el.parentElement).cursor : 'auto';
    const ownPointer = cs.cursor === 'pointer' && parentCursor !== 'pointer';
    if (!hasOnclick && !ownPointer) continue;
    out.clickables.push({selector: window.__paritySelector(el), html: el.outerHTML.slice(0, 300),
      hasOnclick, tabindex: el.getAttribute('tabindex'), role: el.getAttribute('role') || '', text: clean(el.textContent).slice(0, 80)});
  }

  for (const a of document.querySelectorAll('a[href]')) {
    if (!visible(a)) continue;
    let name = a.getAttribute('aria-label') || '';
    if (!name) {
      const copy = a.cloneNode(true);
      copy.querySelectorAll('img').forEach(i => i.replaceWith(document.createTextNode(' ' + (i.getAttribute('alt') || '') + ' ')));
      name = copy.textContent;
    }
    // One malformed href must not break the whole agent (regression caught by tests).
    let href = a.getAttribute('href');
    try { const u = new URL(href, location.href); u.hash = ''; href = u.href; } catch (e) { href = href.split('#')[0]; }
    out.links.push({selector: window.__paritySelector(a), html: a.outerHTML.slice(0, 300), name: clean(name), href});
  }

  for (const el of document.querySelectorAll('input, textarea')) {
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image', 'checkbox', 'radio', 'file', 'range', 'color'].includes(type)) continue;
    if (!visible(el) || !el.getAttribute('placeholder')) continue;
    const labelled = (el.labels && el.labels.length > 0) || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title');
    if (labelled) continue;
    out.placeholders.push({selector: window.__paritySelector(el), html: el.outerHTML.slice(0, 300), placeholder: el.getAttribute('placeholder')});
  }
  return out;
}
"""


@dataclass
class InteractionAudit:
    findings: list[Finding] = field(default_factory=list)
    tab_stops: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


async def keyboard_walk(page, max_stops: int = MAX_TAB_STOPS) -> list[str]:
    """Press Tab through the page; return focused elements in order (stops when it wraps around)."""
    await page.evaluate(_SELECTOR_JS)
    await page.evaluate("() => { document.activeElement && document.activeElement.blur && document.activeElement.blur(); window.scrollTo(0, 0); }")
    stops: list[str] = []
    for _ in range(max_stops):
        await page.keyboard.press("Tab")
        sel = await page.evaluate(_ACTIVE_JS)
        if not sel:
            if stops:  # focus left the page content: we've been through everything
                break
            continue
        if stops and sel == stops[0]:
            break  # wrapped around
        if sel in stops[-3:]:
            break  # stuck: the same element keeps focus (a possible keyboard trap; milestone 4 follow-up)
        stops.append(sel)
    return stops


def _finding(rule_id, help_text, description, wcag, level, impact, node, confidence=Confidence.auto_verified, url=""):
    return Finding(rule_id=rule_id, description=description, help=help_text, help_url=url, impact=impact,
                   wcag_criteria=[wcag], wcag_level=level, source=Source.interaction_agent,
                   confidence=confidence, nodes=[node])


async def audit_interaction(page) -> InteractionAudit:
    audit = InteractionAudit()
    audit.tab_stops = await keyboard_walk(page)
    reached = set(audit.tab_stops)
    found = await page.evaluate(_CANDIDATES_JS)

    for c in found["clickables"]:
        if c["selector"] in reached:
            continue
        focusable_attr = c["tabindex"] is not None and c["tabindex"] != "-1"
        if focusable_attr:
            continue
        sure = c["hasOnclick"]
        evidence = (f"Pressed Tab through the page ({len(audit.tab_stops)} stops); this element never received focus. "
                    + ("It has a click handler, so mouse users can activate it but keyboard users cannot."
                       if sure else "It shows a pointer cursor like a clickable control; a human should confirm it does something."))
        audit.findings.append(_finding(
            "keyboard-inaccessible", "Everything clickable must also work with a keyboard",
            "A clickable element cannot be reached or used with the keyboard.", "2.1.1", "A", Impact.critical,
            NodeRef(target=c["selector"], html=c["html"], evidence=evidence,
                    suggestion="Use a real <button> or <a href> element (or add tabindex=\"0\", a role and Enter/Space key handling)."),
            Confidence.auto_verified if sure else Confidence.needs_review,
            "https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html",
        ))

    by_name: dict[str, list[dict]] = {}
    for link in found["links"]:
        if link["name"]:
            by_name.setdefault(link["name"].lower().strip(" .!?:"), []).append(link)
    for name, links in by_name.items():
        if len({x["href"] for x in links}) < 2:
            continue
        generic = name in GENERIC_LINK_TEXT
        for link in links:
            others = len({x["href"] for x in links}) - 1
            audit.findings.append(_finding(
                "link-purpose-unclear", "Links need text that says where they go",
                f'{len(links)} links are all called "{link["name"]}" but lead to different pages.', "2.4.4", "A", Impact.serious,
                NodeRef(target=link["selector"], html=link["html"],
                        evidence=f'Screen-reader users listing links hear "{link["name"]}" {len(links)} times, going to {others + 1} different pages.',
                        suggestion=f'Make each link say where it goes, e.g. "{link["name"]} about <topic>", or add a visually hidden description.'),
                Confidence.auto_verified if generic else Confidence.needs_review,
                "https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-in-context.html",
            ))

    for f in found["placeholders"]:
        audit.findings.append(_finding(
            "placeholder-as-label", "Form fields need a visible label, not just placeholder text",
            "The field's only label is placeholder text, which disappears as soon as you start typing.", "3.3.2", "A", Impact.serious,
            NodeRef(target=f["selector"], html=f["html"],
                    evidence=f'No <label>, aria-label or aria-labelledby; the only hint is the placeholder "{f["placeholder"]}".',
                    suggestion=f'Add a visible label: <label for="…">{f["placeholder"]}</label>.'),
            url="https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html",
        ))

    audit.notes.append(f"Keyboard walk: {len(audit.tab_stops)} focus stops reached with the Tab key.")
    return audit
