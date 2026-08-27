from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError
import pytest

from app.application.arrival_decision_service import (
    ArrivalDecisionService,
    HaversineDistanceCalculator,
)
from app.application.arrival_evidence_service import ArrivalEvidenceService
from app.core.config import Settings
from app.infrastructure.arrival_evidence_store import (
    SqliteArrivalEvidenceRepository,
)
from app.main import create_app
from app.schemas.arrival_decision import (
    ArrivalDecisionRequest,
    ArrivalDecisionResult,
    TargetTaskLocation,
)
from app.schemas.arrival_evidence import CreateArrivalEvidence, LocationEvidence
from backend.tests.plan_support import UnusedLocationService


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "s2_t014"
    / "arrival_decision_cases.json"
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _request_payload(
    case: dict[str, Any],
    *,
    evidence_id: str | None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "taskId": "task-longmen-grottoes",
        "targetLocation": _fixture()["targetLocation"],
        "attemptOutcome": case["attemptOutcome"],
        "source": "WEB_GEOLOCATION",
        "arrivalEvidenceId": evidence_id,
    }


class FixedDistanceCalculator:
    def __init__(self, distance_meters: float) -> None:
        self.distance_meters = distance_meters

    def meters_between(
        self,
        reading: LocationEvidence,
        target: TargetTaskLocation,
    ) -> float:
        return self.distance_meters


def _service_with_evidence(
    tmp_path: Path,
    *,
    accuracy: float,
    distance_meters: float,
) -> tuple[ArrivalDecisionService, UUID, dict[str, Any]]:
    fixture = _fixture()
    trip_id = UUID(fixture["tripId"])
    repository = SqliteArrivalEvidenceRepository(tmp_path / f"{accuracy}.sqlite3")
    evidence_service = ArrivalEvidenceService(repository)
    payload = json.loads(json.dumps(fixture["cases"][0]["evidence"]))
    payload["locationEvidence"]["accuracy"] = accuracy
    payload["idempotencyKey"] = f"boundary:{accuracy}:{distance_meters}"
    evidence = evidence_service.save(
        trip_id,
        CreateArrivalEvidence.model_validate_json(
            json.dumps(payload),
            strict=True,
        ),
    )
    request = _request_payload(
        fixture["cases"][0],
        evidence_id=str(evidence.evidence_id),
    )
    return (
        ArrivalDecisionService(
            evidence_service,
            distance_calculator=FixedDistanceCalculator(distance_meters),
        ),
        trip_id,
        request,
    )


def test_haversine_distance_is_zero_for_same_coordinate() -> None:
    case = _fixture()["cases"][0]
    reading = LocationEvidence.model_validate_json(
        json.dumps(case["evidence"]["locationEvidence"]),
        strict=True,
    )
    target = TargetTaskLocation.model_validate_json(
        json.dumps(_fixture()["targetLocation"]),
        strict=True,
    )
    assert HaversineDistanceCalculator().meters_between(reading, target) == 0


@pytest.mark.parametrize(
    ("accuracy", "distance", "expected"),
    [
        (75.0, 150.0, ArrivalDecisionResult.ARRIVED),
        (75.0, 150.001, ArrivalDecisionResult.TOO_FAR),
        (100.0, 200.0, ArrivalDecisionResult.ARRIVED),
        (100.0, 200.001, ArrivalDecisionResult.TOO_FAR),
        (100.001, 0.0, ArrivalDecisionResult.LOW_ACCURACY),
    ],
)
def test_threshold_boundaries_are_inclusive_and_deterministic(
    tmp_path: Path,
    accuracy: float,
    distance: float,
    expected: ArrivalDecisionResult,
) -> None:
    service, trip_id, payload = _service_with_evidence(
        tmp_path,
        accuracy=accuracy,
        distance_meters=distance,
    )
    request = ArrivalDecisionRequest.model_validate_json(
        json.dumps(payload),
        strict=True,
    )

    first = service.assess(trip_id, request)
    second = service.assess(trip_id, request)

    assert first == second
    assert first.result is expected
    assert first.allowed_distance_meters == max(150.0, 2 * accuracy)
    assert first.auto_confirmed is (expected is ArrivalDecisionResult.ARRIVED)
    assert first.manual_confirmation_allowed is (
        expected is not ArrivalDecisionResult.ARRIVED
    )


@pytest.mark.parametrize("outcome", ["PERMISSION_DENIED", "TIMEOUT"])
def test_failure_outcomes_forbid_fabricated_evidence_id(outcome: str) -> None:
    payload = _request_payload(
        {"attemptOutcome": outcome},
        evidence_id="33333333-3333-4333-8333-333333333333",
    )
    with pytest.raises(ValidationError):
        ArrivalDecisionRequest.model_validate_json(
            json.dumps(payload),
            strict=True,
        )


@pytest.mark.asyncio
async def test_five_fixtures_return_only_deterministic_judgement_data(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    trip_id = fixture["tripId"]
    database_path = tmp_path / "arrival-decision.sqlite3"
    settings = Settings(
        amap_web_service_key="test-amap",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
        plan_version_db_path=database_path,
    )
    evidence_service = ArrivalEvidenceService(
        SqliteArrivalEvidenceRepository(database_path)
    )
    app = create_app(
        settings=settings,
        service=UnusedLocationService(),  # type: ignore[arg-type]
        arrival_evidence_service=evidence_service,
    )

    responses: list[dict[str, Any]] = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            for case in fixture["cases"]:
                evidence_id = None
                if case["evidence"] is not None:
                    saved = await client.post(
                        f"/api/v1/trips/{trip_id}/arrival-evidence",
                        json=case["evidence"],
                    )
                    assert saved.status_code == 200, saved.text
                    evidence_id = saved.json()["data"]["evidenceId"]
                payload = _request_payload(case, evidence_id=evidence_id)
                first = await client.post(
                    f"/api/v1/trips/{trip_id}/arrival-decision",
                    json=payload,
                )
                second = await client.post(
                    f"/api/v1/trips/{trip_id}/arrival-decision",
                    json=payload,
                )
                assert first.status_code == 200, first.text
                assert second.json() == first.json()
                body = first.json()["data"]
                assert body["result"] == case["expectedResult"]
                assert body["taskId"] == "task-longmen-grottoes"
                assert body["reasonCode"]
                assert body["message"]
                assert body["manualConfirmationAllowed"] is (
                    case["expectedResult"] != "ARRIVED"
                )
                responses.append(body)

    assert {item["result"] for item in responses} == {
        "ARRIVED",
        "TOO_FAR",
        "PERMISSION_DENIED",
        "TIMEOUT",
        "LOW_ACCURACY",
    }
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM arrival_evidence"
        ).fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='arrival_decisions'"
        ).fetchone()[0] == 0
