"""Eval gate for the agents (no AI model needed, so it runs in CI).

Recorded on the 24-issue benchmark:
  rules only:                     precision 100%, recall 54%, AI-only recall 0%,  5 left for review
  + contrast/alt-text (09-26):    precision 100%, recall 75%, AI-only recall 45%, 0 left for review
  + interaction agent (09-27):    precision 100%, recall 92%, AI-only recall 82%, 0 left for review
A change that makes the agents noisier or weaker fails here.
"""

import asyncio

import pytest

from parity.eval.baseline import run_eval
from parity.scanner import AgentOptions


@pytest.fixture(scope="module")
def results():
    # Both full evals run once for the whole module (each is a browser pass over 15 pages).
    try:
        rules = asyncio.run(run_eval(None))
    except Exception as exc:  # no browser available
        pytest.skip(f"Chromium not available: {exc}")
    return rules, asyncio.run(run_eval(AgentOptions(vision=None)))


def test_agents_never_raise_false_alarms(results):
    _, agents = results
    assert agents.precision == 1.0
    assert agents.false_positives_on_clean == 0


def test_agents_find_judgment_issues_rules_cannot(results):
    rules, agents = results
    assert rules.recall_ai_only == 0.0
    assert agents.recall_ai_only >= 0.8
    assert agents.recall_all > rules.recall_all


def test_agents_settle_what_rules_leave_for_review(results):
    rules, agents = results
    assert agents.needs_review_total < rules.needs_review_total
