"""Download W3C's WCAG 2.2 source material from GitHub.

W3C maintains WCAG in public GitHub repositories:
  - w3c/wai-wcag-quickref: structured JSON of every success criterion,
    its level, versions and techniques
  - w3c/wcag: the "Understanding" document for each criterion

Both are published under the W3C Software and Document License, which allows
redistribution with attribution (see data/wcag/NOTICE.md). We save the raw
files in data/wcag/raw/ and commit them, so builds are reproducible offline.

Run:  uv run parity kb fetch
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

QUICKREF_URL = "https://raw.githubusercontent.com/w3c/wai-wcag-quickref/gh-pages/_data/wcag22.json"
UNDERSTANDING_URL = "https://raw.githubusercontent.com/w3c/wcag/main/understanding/{folder}/{id}.html"
# An Understanding page lives in the folder of the WCAG version that introduced it.
VERSION_FOLDER = {"2.0": "20", "2.1": "21", "2.2": "22"}


def iter_criteria(quickref: dict):
    for principle in quickref["principles"]:
        for guideline in principle["guidelines"]:
            for sc in guideline["successcriteria"]:
                yield guideline, sc


def fetch_sources(raw_dir: Path, client: httpx.Client | None = None) -> dict[str, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "understanding").mkdir(exist_ok=True)
    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        resp = client.get(QUICKREF_URL)
        resp.raise_for_status()
        quickref = resp.json()
        (raw_dir / "wcag22.json").write_text(json.dumps(quickref, indent=1, ensure_ascii=False), encoding="utf-8")

        def fetch_one(sc: dict) -> None:
            url = UNDERSTANDING_URL.format(folder=VERSION_FOLDER[sc["versions"][0]], id=sc["id"])
            r = client.get(url)
            r.raise_for_status()
            (raw_dir / "understanding" / f"{sc['id']}.html").write_text(r.text, encoding="utf-8")

        scs = [sc for _, sc in iter_criteria(quickref)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fetch_one, scs))
        return {"criteria": len(scs), "understanding_pages": len(scs)}
    finally:
        if own_client:
            client.close()
