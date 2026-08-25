import json
from pathlib import Path
from typing import Any

import pytest

from app.domain.models import (
    CityContext,
    FacilityEvidenceStatus,
    FacilityType,
    SourceStatus,
    TravelMode,
)
from app.schemas.trip import GeoPoint
from tests.conftest import build_service


class RouteFacilityClient:
    async def plan_route(self, **_: Any) -> dict[str, Any]:
        return {
            "status": "1",
            "route": {
                "paths": [
                    {
                        "distance": "2196",
                        "duration": "1757",
                        "steps": [{"instruction": "步行前往目的地", "distance": "2196"}],
                    }
                ]
            },
        }


@pytest.mark.asyncio
async def test_real_route_snapshot_exposes_each_missing_facility_fact(
    tmp_path: Path,
    beijing: CityContext,
) -> None:
    service = build_service(tmp_path, RouteFacilityClient())
    result = await service.plan_route(
        beijing,
        origin=GeoPoint(longitude=116.397499, latitude=39.908722),
        destination=GeoPoint(longitude=116.403414, latitude=39.924091),
        mode=TravelMode.WALKING,
        strategy=None,
    )

    route = result.routes[0]
    assert route.distanceMeters == 2_196
    assert {item.facilityType for item in route.facilityEvidence} == set(FacilityType)
    assert all(
        item.status is FacilityEvidenceStatus.NEEDS_CONFIRMATION
        for item in route.facilityEvidence
    )
    assert all(
        item.provenance.sourceStatus is SourceStatus.UNKNOWN
        for item in route.facilityEvidence
    )
    assert all(item.referenceId == route.routeId for item in route.facilityEvidence)
    assert all("需现场或人工来源确认" in item.message for item in route.facilityEvidence)


def test_workspace_copy_never_marks_missing_facility_evidence_as_pass() -> None:
    source = Path("frontend/src/pages/WorkspacePage.tsx").read_text(encoding="utf-8")
    risk_helper = Path("frontend/src/services/routeRiskFacts.ts").read_text(
        encoding="utf-8"
    )

    assert "facilityEvidence.length === 0 ||" in source
    assert (
        "import { facilityEvidenceNeedsConfirmation } from "
        "'../services/routeRiskFacts'"
    ) in source
    assert "facilityEvidence.some(facilityEvidenceNeedsConfirmation)" in source
    assert "facilityEvidenceNeedsConfirmation(evidence) ? '待确认'" in source
    assert "evidence.status === 'NEEDS_CONFIRMATION'" in risk_helper
    assert "evidence.provenance.sourceStatus === 'UNKNOWN'" in risk_helper
    assert "const serverPlanReady = Boolean(persistedPlanId) &&" in source
    assert "activePlan.validationStatus === 'PASS'" in source
    assert "{serverPlanReady ? '服务端 PASS' : '待确认'}" in source
    assert "disabled={isConfirmingPlan || !serverPlanReady}" in source
    assert "证据待确认，暂不可接受" in source
    assert "全国无障碍" not in source


def test_t010_api_snapshot_records_all_missing_items() -> None:
    evidence = json.loads(
        Path("docs/testing/evidence/s1_t010_route_facility_snapshot.json").read_text(
            encoding="utf-8"
        )
    )

    assert evidence["taskId"] == "S1-T010"
    assert evidence["routeSnapshot"]["sourceStatus"] == "ONLINE"
    items = evidence["facilityEvidence"]
    assert {item["facilityType"] for item in items} == {
        item.value for item in FacilityType
    }
    assert all(item["status"] == "NEEDS_CONFIRMATION" for item in items)
    assert all(item["sourceStatus"] == "UNKNOWN" for item in items)
    assert evidence["uiAssertions"]["overallStatus"] == "NEEDS_CONFIRMATION"
    assert evidence["uiAssertions"]["showsPassForMissingFacilities"] is False
    assert Path(
        "docs/testing/evidence/s1_t010_facility_confirmation_desktop.png"
    ).stat().st_size > 10_000
