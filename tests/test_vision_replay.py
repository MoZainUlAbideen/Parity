"""Replay REAL recorded Gemini answers through today's logic (no network, no key).

On 2026-09-26 gemini-3.1-flash-lite produced 5 false alarms on the benchmark
(precision 80%). The consistency checks in parity.agents.images fix that; this
test proves it on the model's genuine answers and guards against regressions.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

from parity.eval.baseline import run_eval
from parity.scanner import AgentOptions

DATA = json.loads((Path(__file__).parent / "data" / "gemini_answers_2026-09-26.json").read_text(encoding="utf-8"))
TABLE = {(a["file"], a["alt"]): a["answer"] for a in DATA["answers"]}


class ReplayVision:
    name = "replay:" + DATA["model"]

    def judge_json(self, prompt, image, mime):
        file = re.search(r"file name: (\S+)", prompt).group(1)
        alt = re.search(r"alt attribute: (.*)", prompt).group(1).strip()
        key = "MISSING" if alt.startswith("MISSING") else "EMPTY" if alt.startswith("EMPTY") else alt
        answer = TABLE.get((file, key)) or TABLE.get((file, "OTHER"))
        assert answer is not None, f"no recorded answer for {file} with alt {key}"
        return answer, self.name


@pytest.fixture(scope="module")
def result():
    try:
        return asyncio.run(run_eval(AgentOptions(vision=ReplayVision()), "replay"))
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip("Chromium not available")
        raise


def test_real_gemini_answers_no_longer_cause_false_alarms(result):
    assert result.precision == 1.0
    assert result.false_positives_on_clean == 0


def test_real_catches_are_kept(result):
    # With the interaction agent (2026-09-27) every labeled issue is found.
    assert result.recall_all == 1.0
    missed = {m.selector for m in result.missed}
    assert "#sales-bars" not in missed and "#promo-text" not in missed
