import json
from pathlib import Path

from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.schemas.plan import PlanVersionStatus
from tests.test_plan_versions import parse_proposal


def test_t013_snapshot_and_refresh_evidence_matches_repository(tmp_path: Path) -> None:
    evidence = json.loads(
        Path("docs/testing/evidence/s1_t013_plan_v1_snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    repository = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    proposal = parse_proposal()
    repository.register_proposed(proposal)
    repository.confirm(proposal.trip_snapshot.trip_id, proposal.plan_id)

    reopened = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    restored = reopened.get_trip_state(proposal.trip_snapshot.trip_id)

    assert evidence["taskId"] == "S1-T013"
    assert evidence["databaseInvariants"] == {
        "immutableSnapshot": True,
        "uniqueCurrentPerTrip": True,
        "duplicateVersionWrite": "REJECTED",
    }
    assert restored.current_plan is not None
    assert restored.current_plan.status is PlanVersionStatus.CURRENT
    assert evidence["refreshRecovery"] == {
        "cityCode": restored.current_plan.trip_snapshot.city_context.city_code,
        "dayIndex": restored.current_plan.trip_snapshot.days[0].day_index,
        "taskIds": [task.task_id for task in restored.current_plan.days[0].tasks],
        "totalCostCents": restored.current_plan.metrics.total_cost_cents,
    }
