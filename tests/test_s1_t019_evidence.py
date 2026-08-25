import json
from pathlib import Path

from app.infrastructure.plan_store import SqlitePlanVersionRepository
from tests.test_plan_v2_diff import setup_executing, v2_payload
from tests.test_plan_versions import parse_proposal


def _load_evidence() -> dict[str, object]:
    return json.loads(
        Path("docs/testing/evidence/s1_t019_diff_and_decisions.json").read_text(
            encoding="utf-8"
        )
    )


def test_t019_diff_json_is_generated_from_the_real_contract(tmp_path: Path) -> None:
    evidence = _load_evidence()
    repository = SqlitePlanVersionRepository(tmp_path / "diff.sqlite3")
    v1 = setup_executing(repository)
    v2 = parse_proposal(v2_payload())
    repository.register_proposed(v2)
    actual = repository.get_diff(v1.trip_snapshot.trip_id, v2.plan_id).model_dump(
        mode="json", by_alias=True
    )
    actual_items = {item["key"]: item for item in actual["items"]}

    assert evidence["taskId"] == "S1-T019"
    stored_diff = evidence["diff"]
    assert stored_diff["tripId"] == actual["tripId"]
    assert stored_diff["basePlanId"] == actual["basePlanId"]
    assert stored_diff["candidatePlanId"] == actual["candidatePlanId"]
    assert stored_diff["metricsDelta"] == actual["metricsDelta"]
    for item in stored_diff["items"]:
        assert item == actual_items[item["key"]]

    assert {item["category"] for item in stored_diff["items"]} == {
        "PLACE",
        "TIME",
        "ROUTE",
        "COST",
        "CARE",
    }
    assert {item["changeType"] for item in stored_diff["items"]} == {
        "RETAINED",
        "REMOVED",
        "ADDED",
        "CHANGED",
    }


def test_t019_accept_and_reject_snapshots_match_atomic_repository_state(
    tmp_path: Path,
) -> None:
    evidence = _load_evidence()

    accept_repository = SqlitePlanVersionRepository(tmp_path / "accept.sqlite3")
    accept_v1 = setup_executing(accept_repository)
    accept_v2 = parse_proposal(v2_payload())
    accept_repository.register_proposed(accept_v2)
    accepted = accept_repository.accept_v2(
        accept_v1.trip_snapshot.trip_id, accept_v2.plan_id
    )
    assert evidence["acceptState"] == {
        "tripStatus": accepted.trip_status,
        "currentPlanId": str(accepted.current_plan_id),
        "v1Status": accepted.previous_current_status.value,
        "v2Status": accepted.candidate_status.value,
    }

    reject_repository = SqlitePlanVersionRepository(tmp_path / "reject.sqlite3")
    reject_v1 = setup_executing(reject_repository)
    reject_v2 = parse_proposal(v2_payload())
    reject_repository.register_proposed(reject_v2)
    rejected = reject_repository.reject_v2(
        reject_v1.trip_snapshot.trip_id, reject_v2.plan_id
    )
    assert evidence["rejectState"] == {
        "tripStatus": rejected.trip_status,
        "currentPlanId": str(rejected.current_plan_id),
        "v1Status": rejected.previous_current_status.value,
        "v2Status": rejected.candidate_status.value,
    }
