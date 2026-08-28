from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import httpx
import pytest

from app.core.config import Settings
from app.domain.collaboration import QUESTION_IDS
from app.main import create_app
from backend.tests.test_s1_t024_golden_path import (
    _candidate_request_from_provider,
    _fixture,
    _review_confirmations,
)
from backend.tests.test_s2_t002_http import CountingGateway
from backend.tests.test_s2_t024_single_golden_path import (
    SingleTripProvider,
    _ready_low_stamina_proposal,
)


def _conversation_payload() -> dict[str, object]:
    proposal = _ready_low_stamina_proposal()
    evidence = " ".join(item.source_text for item in proposal.field_evidence)
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-26",
        "naturalLanguageRequest": evidence,
        "answers": [
            {"questionId": question_id, "answer": evidence}
            for question_id in QUESTION_IDS
        ],
    }


def _provider_search_payload(trip_id: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "tripId": trip_id,
        "cityContext": {
            "countryCode": "CN",
            "cityCode": "110000",
            "cityName": "北京市",
            "center": {"longitude": 116.407387, "latitude": 39.904179},
            "providerConfig": {
                "provider": "AMAP",
                "coordinateSystem": "GCJ02",
            },
        },
        "keywords": "museum",
        "types": [],
        "page": 1,
        "pageSize": 20,
    }


async def _create_ready_collaboration_trip(
    client: httpx.AsyncClient,
) -> tuple[str, str, str]:
    created = await client.post(
        "/api/v2/trips/conversations",
        headers={"Idempotency-Key": "s2-t024-full-create-0001"},
        json=_conversation_payload(),
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    trip_id = data["revision"]["tripId"]
    organizer_token = data["organizerAccess"]["organizerToken"]
    organizer_id = data["organizerAccess"]["organizerParticipantId"]

    confirmed = await client.post(
        f"/api/v2/trips/{trip_id}/participants/{organizer_id}/confirm",
        headers={
            "X-Organizer-Token": organizer_token,
            "Idempotency-Key": "s2-t024-full-confirm-member-0001",
        },
        json={
            "schemaVersion": "1.0",
            "baseRevision": 1,
            "expectedVersion": 1,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "READY_TO_PLAN"
    return trip_id, organizer_id, organizer_token


async def _issue_v1(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    organizer_id: str,
    city_resolution: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    planning_trip_response = await client.get(
        f"/api/v2/trips/{trip_id}/planning-trip",
        headers={"Idempotency-Key": "s2-t024-full-planning-trip-0001"},
    )
    assert planning_trip_response.status_code == 200, planning_trip_response.text
    planning_trip = planning_trip_response.json()["data"]
    assert planning_trip["tripId"] == trip_id
    assert planning_trip["participants"][0]["participantId"] == organizer_id

    planning_request = await _candidate_request_from_provider(
        client,
        trip=deepcopy(planning_trip),
        city_resolution=city_resolution,
        fixture=_fixture(),
    )
    requested = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/generate",
        headers={"Idempotency-Key": "s2-t024-full-generate-v1-0001"},
        json=planning_request,
    )
    assert requested.status_code == 422, requested.text
    assert requested.json()["code"] == "CANDIDATE_CONFIRMATION_REQUIRED"
    review = requested.json()["errors"][0]["review"]

    confirmed_review = await client.post(
        f"/api/v1/trips/{trip_id}/plan-reviews/{review['reviewId']}/confirm",
        headers={"Idempotency-Key": "s2-t024-full-review-0001"},
        json={
            "schemaVersion": "1.0",
            "confirmations": _review_confirmations(review, _fixture()),
        },
    )
    assert confirmed_review.status_code == 200, confirmed_review.text
    v1 = confirmed_review.json()["data"]
    assert v1["version"] == 1
    assert v1["tripSnapshot"]["tripId"] == trip_id
    assert v1["tripSnapshot"]["participants"][0]["participantId"] == organizer_id

    confirmed_v1 = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/{v1['planId']}/confirm",
        headers={"Idempotency-Key": "s2-t024-full-confirm-v1-0001"},
    )
    assert confirmed_v1.status_code == 200, confirmed_v1.text
    started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
    assert started.status_code == 200, started.text
    assert started.json()["data"]["planId"] == v1["planId"]
    return v1, planning_request


async def _post_execution_event(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    task_id: str,
    event_type: str,
    key: str,
    occurred_at: str,
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/trips/{trip_id}/events",
        json={
            "schemaVersion": "1.0",
            "taskId": task_id,
            "planVersionId": plan_id,
            "eventType": event_type,
            "amountCents": None,
            "idempotencyKey": key,
            "occurredAt": occurred_at,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _persist_adjustment(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    task_id: str,
    event_type: str,
    key: str,
    occurred_at: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "1.0",
        "confirmationStatus": "CONFIRMED",
        "eventType": event_type,
        "taskId": task_id,
        "lateMinutes": 20 if event_type == "LATE" else None,
        "fatigueLevel": "MODERATE" if event_type == "FATIGUE" else None,
        "planVersionId": plan_id,
        "idempotencyKey": key,
        "occurredAt": occurred_at,
    }
    response = await client.post(
        f"/api/v1/execution-adjustments/trips/{trip_id}/events",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_t024_single_trip_full_backend_golden_path(tmp_path: Path) -> None:
    """One ASGI app and SQLite file carry the same Trip through the S2 path."""

    database_path = tmp_path / "s2-t024-full.sqlite3"
    provider = SingleTripProvider()
    gateway = CountingGateway(_ready_low_stamina_proposal())
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=database_path,
            bailian_api_key=None,
        ),
        service=provider,  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            trip_id, organizer_id, organizer_token = (
                await _create_ready_collaboration_trip(client)
            )
            assert gateway.calls == 1
            client.headers["X-Organizer-Token"] = organizer_token

            city = await client.post(
                "/api/v1/cities/resolve",
                json={"schemaVersion": "1.0", "cityName": "北京"},
            )
            assert city.status_code == 200, city.text
            city_resolution = city.json()["data"]

            provider_result = await client.post(
                "/api/v1/places/search",
                headers={"Idempotency-Key": "s2-t024-full-provider-0001"},
                json=_provider_search_payload(trip_id),
            )
            assert provider_result.status_code == 200, provider_result.text
            recommendation = await client.get(
                f"/api/v2/trips/{trip_id}/recommendations",
                headers={"Idempotency-Key": "s2-t024-full-recommend-0001"},
            )
            assert recommendation.status_code == 200, recommendation.text
            recommendation_data = recommendation.json()["data"]
            assert 6 <= len(recommendation_data["candidates"]) <= 8
            assert all(
                item["factRefId"].startswith("AMAP:")
                for item in recommendation_data["candidates"]
            )
            assert recommendation_data["trustedPlan"]["memberScores"][0][
                "participantId"
            ] == organizer_id

            v1, planning_request = await _issue_v1(
                client,
                trip_id=trip_id,
                organizer_id=organizer_id,
                city_resolution=city_resolution,
            )
            v1_id = v1["planId"]
            tasks = v1["days"][0]["tasks"]
            first_task, current_task = tasks[0], tasks[1]
            first_fact = planning_request["taskFacts"][0]
            first_location = first_fact["place"]["location"]

            evidence = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-evidence",
                json={
                    "schemaVersion": "1.0",
                    "taskId": first_task["taskId"],
                    "locationEvidence": {
                        "longitude": first_location["longitude"],
                        "latitude": first_location["latitude"],
                        "accuracy": 25.0,
                        "capturedAt": "2026-09-05T10:30:00+08:00",
                        "source": "WEB_GEOLOCATION",
                    },
                    "idempotencyKey": "s2-t024-full-arrival-evidence-0001",
                },
            )
            assert evidence.status_code == 200, evidence.text
            evidence_id = evidence.json()["data"]["evidenceId"]
            completed = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-events",
                json={
                    "schemaVersion": "1.0",
                    "taskId": first_task["taskId"],
                    "planVersionId": v1_id,
                    "arrivalEvidenceId": evidence_id,
                    "targetLocation": first_location,
                    "source": "WEB_GEOLOCATION",
                    "idempotencyKey": "s2-t024-full-arrival-complete-0001",
                    "occurredAt": "2026-09-05T10:30:05+08:00",
                },
            )
            assert completed.status_code == 200, completed.text
            complete_event = completed.json()["data"]
            assert complete_event["tripId"] == trip_id
            assert complete_event["planVersionId"] == v1_id
            assert complete_event["arrivalEvidence"]["evidenceId"] == evidence_id

            photo_payload = {
                "dataUrl": "data:image/jpeg;base64," + "A" * 64,
                "mimeType": "image/jpeg",
                "byteSize": 64,
            }
            first_photo = await client.post(
                f"/api/v2/trips/{trip_id}/tasks/{first_task['taskId']}/media",
                json=photo_payload,
            )
            replacement = await client.post(
                f"/api/v2/trips/{trip_id}/tasks/{first_task['taskId']}/media",
                json={
                    **photo_payload,
                    "dataUrl": "data:image/jpeg;base64," + "B" * 64,
                },
            )
            deleted_photo = await client.post(
                f"/api/v2/trips/{trip_id}/tasks/{current_task['taskId']}/media",
                json={
                    **photo_payload,
                    "dataUrl": "data:image/jpeg;base64," + "C" * 64,
                },
            )
            deleted = await client.delete(
                f"/api/v2/trips/{trip_id}/tasks/{current_task['taskId']}/media"
            )
            assert first_photo.status_code == replacement.status_code == 200
            assert deleted_photo.status_code == deleted.status_code == 200
            assert (
                first_photo.json()["data"]["mediaId"]
                != replacement.json()["data"]["mediaId"]
            )

            started_task = await _post_execution_event(
                client,
                trip_id=trip_id,
                plan_id=v1_id,
                task_id=current_task["taskId"],
                event_type="START",
                key="s2-t024-full-task-start-0001",
                occurred_at="2026-09-05T11:00:00+08:00",
            )
            late = await _persist_adjustment(
                client,
                trip_id=trip_id,
                plan_id=v1_id,
                task_id=current_task["taskId"],
                event_type="LATE",
                key="s2-t024-full-late-0001",
                occurred_at="2026-09-05T11:10:00+08:00",
            )
            fatigue = await _persist_adjustment(
                client,
                trip_id=trip_id,
                plan_id=v1_id,
                task_id=current_task["taskId"],
                event_type="FATIGUE",
                key="s2-t024-full-fatigue-0001",
                occurred_at="2026-09-05T11:20:00+08:00",
            )
            listed_adjustments = await client.get(
                f"/api/v1/execution-adjustments/trips/{trip_id}/events"
            )
            assert listed_adjustments.status_code == 200, listed_adjustments.text
            assert [
                item["eventId"] for item in listed_adjustments.json()["data"]
            ] == [late["eventId"], fatigue["eventId"]]

            preview = await client.post(
                f"/api/v1/trips/{trip_id}/replans/from-adjustment",
                headers={"Idempotency-Key": "s2-t024-full-v2-preview-0001"},
                json={
                    "schemaVersion": "1.0",
                    "adjustmentEventId": fatigue["eventId"],
                    "adjustment": {
                        "schemaVersion": "1.0",
                        "confirmationStatus": "CONFIRMED",
                        "eventType": "FATIGUE",
                        "taskId": current_task["taskId"],
                        "lateMinutes": None,
                        "fatigueLevel": "MODERATE",
                    },
                    "lockedTaskIds": [],
                    "explainDifferences": False,
                },
            )
            assert preview.status_code == 200, preview.text
            preview_data = preview.json()["data"]
            v2 = preview_data["candidatePlan"]
            assert preview_data["currentPlanId"] == v1_id
            assert preview_data["currentPlanChanged"] is False
            assert v2["tripSnapshot"]["tripId"] == trip_id
            assert v2["version"] == 2
            assert v2["parentId"] == v1_id
            assert v2["reason"] == "FATIGUE"
            assert v2["status"] == "PROPOSED"
            assert preview_data["diff"]["basePlanId"] == v1_id
            assert preview_data["diff"]["candidatePlanId"] == v2["planId"]
            assert preview_data["frozenTaskIds"][:2] == [
                first_task["taskId"],
                current_task["taskId"],
            ]

            before_decision = await client.get(f"/api/v1/trips/{trip_id}")
            assert before_decision.json()["data"]["currentPlan"]["planId"] == v1_id
            decision = await client.post(
                f"/api/v1/trips/{trip_id}/replans/{v2['planId']}/decision",
                headers={"Idempotency-Key": "s2-t024-full-v2-accept-0001"},
                json={"schemaVersion": "1.0", "decision": "ACCEPT"},
            )
            assert decision.status_code == 200, decision.text
            assert decision.json()["data"]["result"]["currentPlanId"] == v2["planId"]

            final_state = await client.get(f"/api/v1/trips/{trip_id}")
            assert final_state.status_code == 200, final_state.text
            final_data = final_state.json()["data"]
            assert final_data["tripId"] == trip_id
            assert final_data["tripStatus"] == "EXECUTING"
            assert final_data["currentPlan"]["planId"] == v2["planId"]
            assert final_data["currentPlan"]["parentId"] == v1_id
            assert final_data["events"][0]["eventId"] == complete_event["eventId"]
            assert final_data["events"][1]["eventId"] == started_task["eventId"]

            timeline_response = await client.get(
                f"/api/v1/trips/{trip_id}/memory-timeline"
            )
            assert timeline_response.status_code == 200, timeline_response.text
            timeline = timeline_response.json()["data"]
            assert timeline["tripId"] == trip_id
            assert timeline["summary"]["currentPlanVersion"] == 2
            assert timeline["summary"]["planChangeCount"] == 1
            assert timeline["summary"]["completedTaskCount"] == 1
            assert timeline["summary"]["photoCount"] == 1
            plan_items = [
                item for item in timeline["items"] if item["kind"] == "PLAN_VERSION"
            ]
            assert [item["planVersionId"] for item in plan_items] == [v1_id, v2["planId"]]
            photos = [item for item in timeline["items"] if item["kind"] == "PHOTO"]
            assert photos[0]["taskId"] == first_task["taskId"]
            assert photos[0]["photo"]["mediaId"] == replacement.json()["data"]["mediaId"]
            serialized_timeline = json.dumps(timeline, ensure_ascii=False)
            assert "data:image/jpeg;base64," + "A" * 64 not in serialized_timeline
            assert "data:image/jpeg;base64," + "C" * 64 not in serialized_timeline

    with sqlite3.connect(database_path) as connection:
        table_trip_ids = {
            table: {
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT trip_id FROM {table}"
                ).fetchall()
            }
            for table in (
                "collaboration_sessions",
                "confirmed_trip_inputs",
                "plan_versions",
                "execution_events",
                "execution_adjustment_events",
                "arrival_evidence",
                "task_media",
            )
        }
        assert all(ids == {trip_id} for ids in table_trip_ids.values())
        stored_plans = connection.execute(
            "SELECT version,status,snapshot_json FROM plan_versions "
            "WHERE trip_id=? ORDER BY version",
            (trip_id,),
        ).fetchall()
        assert [(row[0], row[1]) for row in stored_plans] == [
            (1, "SUPERSEDED"),
            (2, "CURRENT"),
        ]
        assert json.loads(stored_plans[0][2])["parentId"] is None
        assert json.loads(stored_plans[1][2])["parentId"] == v1_id
        assert connection.execute(
            "SELECT event_type,plan_version_id FROM execution_adjustment_events "
            "WHERE trip_id=? ORDER BY occurred_at",
            (trip_id,),
        ).fetchall() == [("LATE", v1_id), ("FATIGUE", v1_id)]
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances "
            "WHERE trip_id=? AND boundary_kind='V2'",
            (trip_id,),
        ).fetchone()[0] == 1
        active_media = connection.execute(
            "SELECT media_id,task_id FROM task_media "
            "WHERE trip_id=? AND deleted_at IS NULL",
            (trip_id,),
        ).fetchall()
        assert active_media == [
            (
                replacement.json()["data"]["mediaId"],
                first_task["taskId"],
            )
        ]

    occurred = [
        datetime.fromisoformat(item["occurredAt"])
        for item in timeline["items"]
    ]
    assert occurred == sorted(occurred)
