from __future__ import annotations

import json
from pathlib import Path

from backend.tests.s2_t003_support import evaluate_fixture_case, serialize_issues


CASES = Path(__file__).parent / "fixtures" / "s2_t003" / "cases.json"
SNAPSHOT = Path(__file__).parent / "snapshots" / "s2_t003_confirmation_items.json"


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    snapshot = {
        case["name"]: serialize_issues(evaluate_fixture_case(case))
        for case in cases
    }
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
