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
from app.services.planning import CandidatePlanRequest
from backend.tests.test_s1_t024_golden_path import (
    _fixture,
    _review_confirmations,
)
from backend.tests.test_s2_t002_http import CountingGateway
from backend.tests.test_s2_t024_single_golden_path import (
    SingleTripProvider,
    _ready_low_stamina_proposal,
)


def _conversation_payload(proposal=None) -> dict[str, object]:
    proposal = proposal or _ready_low_stamina_proposal()
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


def _provider_search_payload(
    trip_id: str,
    *,
    city_code: str = "110000",
    city_name: str = "北京市",
    longitude: float = 116.407387,
    latitude: float = 39.904179,
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "tripId": trip_id,
        "cityContext": {
            "countryCode": "CN",
            "cityCode": city_code,
            "cityName": city_name,
            "center": {"longitude": longitude, "latitude": latitude},
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


async def _candidate_request_from_trusted_plan(
    client: httpx.AsyncClient,
    *,
    trip: dict,
    city_resolution: dict,
    recommendation: dict,
) -> tuple[dict, dict[str, object]]:
    """Route only the signed FactRefs selected by the recommendation page."""

    trip_id = trip["tripId"]
    fact_set_id = recommendation["factSetId"]
    provider_fact_digest = recommendation["providerFactDigest"]
    summary_response = await client.get(
        f"/api/v1/trips/{trip_id}/provider-fact-sets/{fact_set_id}",
        params={"providerFactDigest": provider_fact_digest},
    )
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()["data"]
    assert summary["providerFactDigest"] == provider_fact_digest

    places_response = await client.get(
        f"/api/v1/trips/{trip_id}/provider-fact-sets/{fact_set_id}/places",
        params={"providerFactDigest": provider_fact_digest},
    )
    assert places_response.status_code == 200, places_response.text
    signed_places = places_response.json()["data"]
    assert signed_places["providerFactDigest"] == provider_fact_digest

    reference_by_id = {item["factRefId"]: item for item in summary["references"]}
    place_by_ref = {item["factRefId"]: item for item in signed_places["places"]}
    trusted_tasks = recommendation["trustedPlan"]["tasks"]
    selected_refs = [item["factRefId"] for item in trusted_tasks]
    selected_place_ids = [item["placeId"] for item in trusted_tasks]
    assert len(selected_refs) in {2, 3, 4, 5}
    assert len(selected_refs) == len(set(selected_refs))

    selected_places = []
    for task in trusted_tasks:
        fact_ref_id = task["factRefId"]
        reference = reference_by_id[fact_ref_id]
        signed = place_by_ref[fact_ref_id]
        assert reference["kind"] == "PLACE"
        assert reference["providerObjectId"] == task["placeId"]
        assert signed["providerObjectId"] == task["placeId"]
        assert signed["payloadDigest"] == reference["payloadDigest"]
        assert signed["place"]["placeId"] == task["placeId"]
        selected_places.append(signed["place"])

    return_response = await client.post(
        "/api/v1/places/search",
        json={
            "schemaVersion": "1.0",
            "tripId": trip_id,
            "cityContext": trip["cityContext"],
            "keywords": trip["days"][0]["endLocationText"],
            "types": [],
            "page": 1,
            "pageSize": 1,
        },
    )
    assert return_response.status_code == 200, return_response.text
    return_place = return_response.json()["data"]["places"][0]
    assert return_place["placeId"] not in selected_place_ids

    ordered_places = [*selected_places, return_place]
    dining_count = sum(
        "餐饮" in (place.get("category") or "")
        or "餐厅" in (place.get("category") or "")
        for place in selected_places
    )
    if len(selected_places) == 5 and dining_count == 2:
        time_ranges = (
            ("09:30:00", "10:15:00"),
            ("12:00:00", "13:00:00"),
            ("13:30:00", "14:15:00"),
            ("15:00:00", "16:00:00"),
            ("18:00:00", "19:00:00"),
            ("19:30:00", "19:45:00"),
        )
    elif len(selected_places) == 4 and dining_count == 2:
        time_ranges = (
            ("09:30:00", "10:15:00"),
            ("12:00:00", "13:00:00"),
            ("14:00:00", "15:00:00"),
            ("18:00:00", "19:00:00"),
            ("19:30:00", "19:45:00"),
        )
    elif len(selected_places) == 4 and dining_count == 1:
        time_ranges = (
            ("09:30:00", "10:15:00"),
            ("12:00:00", "13:00:00"),
            ("13:30:00", "14:15:00"),
            ("14:45:00", "15:30:00"),
            ("16:00:00", "16:15:00"),
        )
    else:
        time_ranges = (
            ("09:30:00", "10:15:00"),
            ("10:45:00", "11:30:00"),
            ("12:00:00", "13:00:00"),
            ("13:30:00", "15:00:00"),
        )
    task_facts: list[dict[str, object]] = []
    origin = trip["cityContext"]["center"]
    for index, place in enumerate(ordered_places, start=1):
        route_response = await client.post(
            "/api/v1/routes/plan",
            json={
                "schemaVersion": "1.0",
                "tripId": trip_id,
                "cityContext": trip["cityContext"],
                "origin": origin,
                "destination": place["location"],
                "mode": "WALKING",
                "strategy": None,
            },
        )
        assert route_response.status_code == 200, route_response.text
        route = route_response.json()["data"]["routes"][0]
        is_return = index == len(ordered_places)
        start_at, end_at = time_ranges[index - 1]
        task_facts.append(
            {
                "taskId": "trusted-return" if is_return else f"trusted-visit-{index}",
                "order": index,
                "title": (
                    f"返回{trip['days'][0]['endLocationText']}"
                    if is_return
                    else place["name"]
                ),
                "category": "RETURN" if is_return else place["category"] or "PLACE",
                "startAt": start_at,
                "endAt": end_at,
                "endLocationText": place["name"],
                "cityCode": place["cityCode"],
                "place": place,
                "route": route,
                "elapsedSinceRestMinutes": 30,
                "note": "服务端签发 FactRef 顺序" if not is_return else "独立核验返程",
            }
        )
        origin = place["location"]

    planning_trip = deepcopy(trip)
    planning_trip["status"] = "PLANNING"
    endpoint_provenance = city_resolution["provenance"]
    planning_request = {
        "schemaVersion": "1.0",
        "trip": planning_trip,
        "startLocation": {
            "locationText": trip["days"][0]["startLocationText"],
            "cityCode": trip["cityContext"]["cityCode"],
            "location": trip["cityContext"]["center"],
            "provenance": endpoint_provenance,
        },
        "endLocation": {
            "locationText": trip["days"][0]["endLocationText"],
            "cityCode": trip["cityContext"]["cityCode"],
            "location": return_place["location"],
            "provenance": return_place["provenance"],
        },
        "taskFacts": task_facts,
        "confirmedConstraints": _fixture()["confirmedConstraints"],
    }
    return planning_request, {
        "factSetId": fact_set_id,
        "providerFactDigest": provider_fact_digest,
        "selectedFactRefs": selected_refs,
        "selectedPlaceIds": selected_place_ids,
    }


async def _create_ready_collaboration_trip(
    client: httpx.AsyncClient,
    *,
    proposal=None,
) -> tuple[str, str, str]:
    created = await client.post(
        "/api/v2/trips/conversations",
        headers={"Idempotency-Key": "s2-t024-full-create-0001"},
        json=_conversation_payload(proposal),
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
    recommendation: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    planning_trip_response = await client.get(
        f"/api/v2/trips/{trip_id}/planning-trip",
        headers={"Idempotency-Key": "s2-t024-full-planning-trip-0001"},
    )
    assert planning_trip_response.status_code == 200, planning_trip_response.text
    planning_trip = planning_trip_response.json()["data"]
    assert planning_trip["tripId"] == trip_id
    assert planning_trip["participants"][0]["participantId"] == organizer_id

    planning_request, recommendation_trace = (
        await _candidate_request_from_trusted_plan(
            client,
            trip=deepcopy(planning_trip),
            city_resolution=city_resolution,
            recommendation=recommendation,
        )
    )
    requested = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/generate",
        headers={"Idempotency-Key": "s2-t024-full-generate-v1-0001"},
        json=planning_request,
    )
    if requested.status_code == 422:
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
    else:
        assert requested.status_code == 200, requested.text
        v1 = requested.json()["data"]
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
    planning_facts_response = await client.get(
        f"/api/v1/trips/{trip_id}/planning-facts",
        headers={"Idempotency-Key": "s2-t024-full-planning-facts-0001"},
    )
    assert planning_facts_response.status_code == 200, planning_facts_response.text
    restored_request = CandidatePlanRequest.model_validate_json(
        json.dumps(planning_facts_response.json()["data"])
    )
    submitted_request = CandidatePlanRequest.model_validate_json(
        json.dumps(planning_request)
    )
    assert restored_request.trip.trip_id == submitted_request.trip.trip_id
    assert [
        (item.task_id, item.place.placeId)
        for item in restored_request.task_facts
    ] == [
        (item.task_id, item.place.placeId)
        for item in submitted_request.task_facts
    ]
    return v1, planning_request, recommendation_trace


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


@pytest.mark.parametrize(
    ("city_input", "city_name", "city_code", "longitude", "latitude"),
    [
        pytest.param("北京", "北京市", "110000", 116.407387, 39.904179, id="beijing"),
        pytest.param("上海", "上海市", "310000", 121.473701, 31.230416, id="shanghai"),
        pytest.param("成都", "成都市", "510100", 104.066541, 30.572269, id="chengdu"),
    ],
)
@pytest.mark.asyncio
async def test_s3_t005_three_city_full_backend_golden_path(
    tmp_path: Path,
    city_input: str,
    city_name: str,
    city_code: str,
    longitude: float,
    latitude: float,
) -> None:
    """Each target city carries one Trip through the complete trusted S2 path."""

    database_path = tmp_path / f"s3-t005-{city_code}.sqlite3"
    end_location = f"{city_name}中心"
    proposal = _ready_low_stamina_proposal(
        city_input=city_input,
        end_location=end_location,
    )
    provider = SingleTripProvider(
        city_input=city_input,
        city_name=city_name,
        city_code=city_code,
        longitude=longitude,
        latitude=latitude,
        end_location=end_location,
    )
    gateway = CountingGateway(proposal)
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
                await _create_ready_collaboration_trip(client, proposal=proposal)
            )
            assert gateway.calls == 1
            client.headers["X-Organizer-Token"] = organizer_token

            city = await client.post(
                "/api/v1/cities/resolve",
                json={"schemaVersion": "1.0", "cityName": city_input},
            )
            assert city.status_code == 200, city.text
            city_resolution = city.json()["data"]
            assert city_resolution["cityContext"]["cityCode"] == city_code
            assert city_resolution["provenance"]["sourceStatus"] == "ONLINE"
            assert city_resolution["provenance"]["isStale"] is False

            provider_result = await client.post(
                "/api/v1/places/search",
                headers={"Idempotency-Key": "s2-t024-full-provider-0001"},
                json=_provider_search_payload(
                    trip_id,
                    city_code=city_code,
                    city_name=city_name,
                    longitude=longitude,
                    latitude=latitude,
                ),
            )
            assert provider_result.status_code == 200, provider_result.text
            provider_data = provider_result.json()["data"]
            assert provider_data["cityCode"] == city_code
            assert {item["cityCode"] for item in provider_data["places"]} == {
                city_code
            }
            assert all(
                item["provenance"]["sourceStatus"] == "ONLINE"
                and item["provenance"]["isStale"] is False
                for item in provider_data["places"]
            )
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

            v1, planning_request, recommendation_trace = await _issue_v1(
                client,
                trip_id=trip_id,
                organizer_id=organizer_id,
                city_resolution=city_resolution,
                recommendation=recommendation_data,
            )
            v1_id = v1["planId"]
            tasks = v1["days"][0]["tasks"]
            assert v1["tripSnapshot"]["cityContext"]["cityCode"] == city_code
            assert planning_request["trip"]["cityContext"]["cityCode"] == city_code
            assert {
                item["cityCode"] for item in planning_request["taskFacts"]
            } == {city_code}
            assert all(
                item["place"]["provenance"]["sourceStatus"] == "ONLINE"
                and item["route"]["provenance"]["sourceStatus"] == "ONLINE"
                and item["route"]["walkingDistanceMeters"] <= 800
                for item in planning_request["taskFacts"]
            )
            trusted_tasks = recommendation_data["trustedPlan"]["tasks"]
            trusted_place_ids = [item["placeId"] for item in trusted_tasks]
            request_place_ids = [
                item["place"]["placeId"] for item in planning_request["taskFacts"]
            ]
            assert recommendation_trace["selectedFactRefs"] == [
                item["factRefId"] for item in trusted_tasks
            ]
            assert recommendation_trace["selectedPlaceIds"] == trusted_place_ids
            assert request_place_ids[: len(trusted_place_ids)] == trusted_place_ids
            assert planning_request["taskFacts"][-1]["category"] == "RETURN"
            assert tasks[-1]["category"] == "RETURN"
            assert [item["taskId"] for item in planning_request["taskFacts"]] == [
                item["taskId"] for item in tasks
            ]
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
