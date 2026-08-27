from __future__ import annotations

import json
from pathlib import Path

from backend.tests.s2_t003_support import evaluate_fixture_case, serialize_issues


CASES = Path(__file__).parent / "fixtures" / "s2_t003" / "cases.json"
SNAPSHOT = Path(__file__).parent / "snapshots" / "s2_t003_confirmation_items.json"


def test_all_named_cases_match_deterministic_issue_snapshot() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    actual = {
        case["name"]: serialize_issues(evaluate_fixture_case(case))
        for case in cases["cases"]
    }
    assert actual == expected
