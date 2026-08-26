from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError
import pytest

from app.application.arrival_evidence_service import ArrivalEvidenceService
from app.core.config import Settings
from app.infrastructure.arrival_evidence_store import (
    ArrivalEvidenceStoreError,
    SqliteArrivalEvidenceRepository,
)
from app.main import create_app
from app.schemas.arrival_evidence import (
    ArrivalEvidence,
    CreateArrivalEvidence,
    LocationEvidence,
)
from backend.tests.plan_support import UnusedLocationService


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "s2_t013"
    / "arrival_evidence_idempotency.json"
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _request(name: str = "firstRequest") -> CreateArrivalEvidence:
    return CreateArrivalEvidence.model_validate_json(
        json.dumps(_fixture()[name], ensure_ascii=False),
        strict=True,
    )


def _schema_property_names(schema: object) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for value in schema.values():
            names.update(_schema_property_names(value))
    elif isinstance(schema, list):
        for value in schema:
            names.update(_schema_property_names(value))
    return names


def test_contract_is_single_reading_and_uses_camel_case() -> None:
    payload = _request().model_dump(mode="json", by_alias=True)

    assert set(payload) == {
        "schemaVersion",
        "taskId",
        "locationEvidence",
        "idempotencyKey",
    }
    assert set(payload["locationEvidence"]) == {
        "longitude",
        "latitude",
        "accuracy",
        "capturedAt",
        "source",
    }
    properties = _schema_property_names(
        CreateArrivalEvidence.model_json_schema(by_alias=True)
    )
    forbidden = {
        "watchPosition",
        "watchId",
        "trackingSessionId",
        "trackingStatus",
        "locationHistory",
    }
    assert properties.isdisjoint(forbidden)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("longitude", 180.1),
        ("latitude", -90.1),
        ("accuracy", 0.0),
        ("accuracy", float("inf")),
    ],
)
def test_location_evidence_rejects_invalid_measurements(
    field: str,
    value: float,
) -> None:
    payload = deepcopy(_fixture()["firstRequest"]["locationEvidence"])
    payload[field] = value
    with pytest.raises(ValidationError):
        LocationEvidence.model_validate(payload, strict=True)


def test_location_evidence_requires_timezone_and_forbids_tracking_fields() -> None:
    payload = deepcopy(_fixture()["firstRequest"]["locationEvidence"])
    payload["capturedAt"] = "2026-08-26T09:30:00"
    with pytest.raises(ValidationError):
        LocationEvidence.model_validate(payload, strict=True)

    payload = deepcopy(_fixture()["firstRequest"])
    payload["watchPosition"] = True
    with pytest.raises(ValidationError):
        CreateArrivalEvidence.model_validate(payload, strict=True)


def test_exact_retry_returns_same_persisted_evidence(tmp_path: Path) -> None:
    database_path = tmp_path / "arrival.sqlite3"
    repository = SqliteArrivalEvidenceRepository(database_path)
    trip_id = UUID(_fixture()["tripId"])

    first = repository.save(trip_id, _request("firstRequest"))
    retry = repository.save(trip_id, _request("exactRetry"))
    recovered = SqliteArrivalEvidenceRepository(database_path).get(
        trip_id,
        first.evidence_id,
    )

    assert retry == first
    assert recovered == first
    assert first.trip_id == trip_id
    assert first.task_id == "task-longmen-grottoes"
    assert first.location_evidence.accuracy == 18.5
    assert first.location_evidence.source.value == "WEB_GEOLOCATION"


def test_same_key_with_different_evidence_is_rejected(tmp_path: Path) -> None:
    repository = SqliteArrivalEvidenceRepository(tmp_path / "arrival.sqlite3")
    trip_id = UUID(_fixture()["tripId"])
    repository.save(trip_id, _request("firstRequest"))

    with pytest.raises(ArrivalEvidenceStoreError) as raised:
        repository.save(trip_id, _request("conflictingRetry"))

    assert raised.value.code == "ARRIVAL_EVIDENCE_IDEMPOTENCY_CONFLICT"
    assert len(repository.list_for_trip(trip_id)) == 1


@pytest.mark.asyncio
async def test_http_save_retry_recover_and_task_filter(tmp_path: Path) -> None:
    database_path = tmp_path / "arrival-http.sqlite3"
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
    trip_id = _fixture()["tripId"]
    path = f"/api/v1/trips/{trip_id}/arrival-evidence"

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            first = await client.post(path, json=_fixture()["firstRequest"])
            retry = await client.post(path, json=_fixture()["exactRetry"])
            conflict = await client.post(
                path,
                json=_fixture()["conflictingRetry"],
            )
            evidence_id = first.json()["data"]["evidenceId"]
            recovered = await client.get(f"{path}/{evidence_id}")
            filtered = await client.get(
                path,
                params={"taskId": "task-longmen-grottoes"},
            )

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "ARRIVAL_EVIDENCE_IDEMPOTENCY_CONFLICT"
    assert recovered.status_code == 200
    assert recovered.json() == first.json()
    assert filtered.status_code == 200
    assert filtered.json()["data"] == [first.json()["data"]]


def test_response_contract_contains_target_and_no_tracking_state() -> None:
    properties = _schema_property_names(
        ArrivalEvidence.model_json_schema(by_alias=True)
    )
    assert {"tripId", "taskId", "locationEvidence", "idempotencyKey"} <= properties
    assert "watchPosition" not in properties
