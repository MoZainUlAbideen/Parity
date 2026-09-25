"""Turn axe-core tags into WCAG success criteria.

axe tags each rule like ["cat.text-alternatives", "wcag2a", "wcag111"].
"wcag111" means success criterion 1.1.1; "wcag2a" / "wcag21aa" / "wcag22aa"
give the conformance level. WCAG criteria numbers are principle.guideline.
criterion, and the criterion part can be two digits (e.g. 1.4.10, 2.5.8).
"""

from __future__ import annotations

import re

# wcag followed by 3+ digits, e.g. wcag111, wcag1410, wcag258
_SC_TAG = re.compile(r"^wcag(\d)(\d)(\d{1,2})$")
# level tags: wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, wcag2aaa
_LEVEL_TAG = re.compile(r"^wcag2\d?(a{1,3})$")


def parse_criteria(tags: list[str]) -> list[str]:
    """Return sorted, de-duplicated success criteria like ['1.1.1', '1.4.3']."""
    found: set[str] = set()
    for tag in tags:
        m = _SC_TAG.match(tag)
        if m:
            found.add(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
    return sorted(found, key=lambda sc: tuple(int(p) for p in sc.split(".")))


def parse_level(tags: list[str]) -> str | None:
    """Return the strictest level named in the tags ('A', 'AA', 'AAA') or None.

    None means the rule is a best practice, not a WCAG requirement.
    """
    levels = []
    for tag in tags:
        if _SC_TAG.match(tag):
            continue  # criterion tags like wcag111 can look like level tags
        m = _LEVEL_TAG.match(tag)
        if m:
            levels.append(len(m.group(1)))
    return "A" * max(levels) if levels else None
