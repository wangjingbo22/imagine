from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.domain.collaboration import QUESTION_IDS
from app.domain.hard_conflicts import merged_constraints_for_revision
from app.domain.trip_draft import (
    FieldEvidence,
    ParticipantUnderstanding,
    TripUnderstandingProposal,
)
from app.main import create_app
from backend.tests.test_s1_t024_golden_path import (
    _fixture,
    _review_confirmations,
)
from backend.tests.test_s2_t002_http import CountingGateway
from backend.tests.test_s2_t024_full_golden_path import (
    _candidate_request_from_trusted_plan,
    _persist_adjustment,
    _post_execution_event,
    _provider_search_payload,
)
from backend.tests.test_s2_t024_single_golden_path import (
    SingleTripProvider,
    _ready_low_stamina_proposal,
)


def _three_member_budget_conflict_proposal() -> TripUnderstandingProposal:
    """Build one complete group revision with one organizer relaxation."""

    base = _ready_low_stamina_proposal()
    care = base.participants[0].care_draft
    assert care is not None
    participants = [
        ParticipantUnderstanding(
            memberKey="member-1",
            nickname="组织者",
            budgetCapCents=50_000,
            interests=["历史文化"],
            mustVisit=[],
            avoidPlaces=[],
            careDraft=care.model_copy(deep=True),
        ),
        ParticipantUnderstanding(
            memberKey="member-2",
            nickname="同行成员甲",
            budgetCapCents=50_000,
            interests=["公园"],
            mustVisit=[],
            avoidPlaces=[],
            careDraft=care.model_copy(deep=True),
        ),
        ParticipantUnderstanding(
            memberKey="member-3",
            nickname="同行成员乙",
            budgetCapCents=40_000,
            interests=["美食"],
            mustVisit=[],
            avoidPlaces=[],
            careDraft=care.model_copy(deep=True),
        ),
    ]
    trip = base.trip.model_copy(update={"budget_cents": 45_000})
    evidence_specs: list[tuple[str, str | None, str]] = [
        ("trip.cityName", None, "北京"),
        ("trip.travelDate", None, "2026-09-05"),
        ("trip.startTime", None, "09:00"),
        ("trip.endTime", None, "18:00"),
        ("trip.startLocationText", None, "北京市中心"),
        ("trip.endLocationText", None, "北京市中心"),
        ("trip.budgetCents", None, "45000"),
    ]
    for index, participant in enumerate(participants):
        member_key = participant.member_key
        participant_care = participant.care_draft
        assert participant.nickname is not None
        assert participant.budget_cap_cents is not None
        assert participant_care is not None
        evidence_specs.extend(
            [
                (
                    f"participants[{index}].nickname",
                    member_key,
                    participant.nickname,
                ),
                (
                    f"participants[{index}].budgetCapCents",
                    member_key,
                    str(participant.budget_cap_cents),
                ),
                (
                    f"participants[{index}].interests[0]",
                    member_key,
                    participant.interests[0],
                ),
                (
                    f"participants[{index}].careDraft.assistanceTypeHint",
                    member_key,
                    str(participant_care.assistance_type_hint),
                ),
                (
                    f"participants[{index}].careDraft.walkLimits."
                    "maxContinuousMeters",
                    member_key,
                    str(participant_care.walk_limits.max_continuous_meters),
                ),
                (
                    f"participants[{index}].careDraft.maxTransfers",
                    member_key,
                    str(participant_care.max_transfers),
                ),
                (
                    f"participants[{index}].careDraft.restIntervalMinutes",
                    member_key,
                    str(participant_care.rest_interval_minutes),
                ),
                (
                    f"participants[{index}].careDraft.avoidStairs",
                    member_key,
                    str(participant_care.avoid_stairs).lower(),
                ),
            ]
        )
    return TripUnderstandingProposal(
        schemaVersion="1.0",
        trip=trip,
        participants=participants,
        fieldEvidence=[
            FieldEvidence(
                fieldPath=path,
                memberKey=member_key,
                sourceType="USER_TEXT",
                sourceText=source_text,
            )
            for path, member_key, source_text in evidence_specs
        ],
        missingFields=[],
        ambiguities=[],
        confirmationQuestions=[],
    )


def _conversation_payload(proposal: TripUnderstandingProposal) -> dict[str, object]:
    evidence = "三人同行 " + " ".join(
        item.source_text for item in proposal.field_evidence
    )
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-31",
        "naturalLanguageRequest": evidence,
        "answers": [
            {"questionId": question_id, "answer": evidence}
            for question_id in QUESTION_IDS
        ],
    }


def _proposal_with_member_nicknames(
    proposal: TripUnderstandingProposal,
    updates: dict[str, str],
) -> TripUnderstandingProposal:
    participants = [
        participant.model_copy(
            update={"nickname": updates[participant.member_key]}
        )
        if participant.member_key in updates
        else participant.model_copy(deep=True)
        for participant in proposal.participants
    ]
    evidence = [
        item.model_copy(update={"source_text": updates[item.member_key]})
        if item.member_key in updates and item.field_path.endswith(".nickname")
        else item.model_copy(deep=True)
        for item in proposal.field_evidence
    ]
    return proposal.model_copy(
        deep=True,
        update={"participants": participants, "field_evidence": evidence},
    )


def _member_conversation_payload(
    proposal: TripUnderstandingProposal,
    *,
    base_revision: int,
    expected_version: int,
) -> dict[str, object]:
    payload = _conversation_payload(proposal)
    payload.pop("referenceDate")
    payload.update(
        {
            "baseRevision": base_revision,
            "expectedVersion": expected_version,
        }
    )
    return payload


@pytest.mark.asyncio
async def test_s2_t032_three_member_conversation_to_memory_local_e2e(
    tmp_path: Path,
) -> None:
    """Local ASGI/SQLite acceptance; public-network evidence is out of scope."""

    database_path = tmp_path / "s2-t032-multiplayer.sqlite3"
    provider = SingleTripProvider()
    proposal = _three_member_budget_conflict_proposal()
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
            created = await client.post(
                "/api/v2/trips/conversations",
                headers={"Idempotency-Key": "s2-t032-create-group-0001"},
                json=_conversation_payload(proposal),
            )
            assert created.status_code == 200, created.text
            created_data = created.json()["data"]
            revision = created_data["revision"]
            trip_id = revision["tripId"]
            bindings = revision["memberBindings"]
            organizer_id = bindings["member-1"]
            organizer_token = created_data["organizerAccess"]["organizerToken"]
            assert list(bindings) == ["member-1", "member-2", "member-3"]
            assert len(set(bindings.values())) == 3
            assert gateway.calls == 1

            collaboration_version = 1
            invitation_tokens: dict[str, str] = {}
            for index, member_key in enumerate(("member-2", "member-3"), start=2):
                invited = await client.post(
                    f"/api/v2/trips/{trip_id}/participants/"
                    f"{bindings[member_key]}/invitations",
                    headers={
                        "X-Organizer-Token": organizer_token,
                        "Idempotency-Key": f"s2-t032-invite-member-000{index}",
                    },
                    json={
                        "schemaVersion": "1.0",
                        "expectedVersion": collaboration_version,
                    },
                )
                assert invited.status_code == 200, invited.text
                invitation = invited.json()["data"]
                collaboration_version = invitation["collaborationVersion"]
                invitation_tokens[member_key] = invitation["invitationUrl"].rsplit(
                    "/", 1
                )[1]

            member_tokens: dict[str, str] = {}
            for index, member_key in enumerate(("member-2", "member-3"), start=2):
                redeemed = await client.post(
                    "/api/v2/participant-invitations/redeem",
                    headers={
                        "Idempotency-Key": f"s2-t032-redeem-member-000{index}"
                    },
                    json={
                        "schemaVersion": "1.0",
                        "token": invitation_tokens[member_key],
                    },
                )
                assert redeemed.status_code == 200, redeemed.text
                member_tokens[member_key] = redeemed.json()["data"][
                    "participantSessionToken"
                ]
            assert len(set(member_tokens.values())) == 2
            assert organizer_token not in set(member_tokens.values())

            for member_key in ("member-2", "member-3"):
                member_view = await client.get(
                    "/api/v2/member-session",
                    headers={
                        "X-Participant-Session": member_tokens[member_key]
                    },
                )
                assert member_view.status_code == 200, member_view.text
                assert member_view.json()["data"]["participantId"] == bindings[
                    member_key
                ]

            base_revision = 1
            expected_nicknames = {
                "member-1": "组织者",
                "member-2": "同行成员甲（独立填写）",
                "member-3": "同行成员乙（独立填写）",
            }
            for index, member_key in enumerate(("member-2", "member-3"), start=2):
                before = app.state.trip_draft_revision_creator.get_current(
                    UUID(trip_id)
                )
                before_participants = {
                    item.member_key: item
                    for item in before.understanding.participants
                }
                candidate = _proposal_with_member_nicknames(
                    before.understanding,
                    {member_key: expected_nicknames[member_key]},
                )
                if member_key == "member-2":
                    overreaching = _proposal_with_member_nicknames(
                        candidate,
                        {"member-1": "被成员甲越权修改的组织者"},
                    )
                    gateway.proposal = overreaching
                    denied = await client.put(
                        "/api/v2/member-session/conversation",
                        headers={
                            "X-Participant-Session": member_tokens[member_key],
                            "Idempotency-Key": "s2-t032-member-scope-denied-0001",
                        },
                        json=_member_conversation_payload(
                            overreaching,
                            base_revision=base_revision,
                            expected_version=collaboration_version,
                        ),
                    )
                    assert (denied.status_code, denied.json()["code"]) == (
                        403,
                        "PARTICIPANT_SCOPE_VIOLATION",
                    )
                    unchanged = app.state.trip_draft_revision_creator.get_current(
                        UUID(trip_id)
                    )
                    assert unchanged.revision == before.revision
                    assert unchanged.understanding == before.understanding

                gateway.proposal = candidate
                submitted = await client.put(
                    "/api/v2/member-session/conversation",
                    headers={
                        "X-Participant-Session": member_tokens[member_key],
                        "Idempotency-Key": f"s2-t032-submit-member-000{index}",
                    },
                    json=_member_conversation_payload(
                        candidate,
                        base_revision=base_revision,
                        expected_version=collaboration_version,
                    ),
                )
                assert submitted.status_code == 200, submitted.text
                submitted_view = submitted.json()["data"]
                assert submitted_view["participantId"] == bindings[member_key]
                base_revision = submitted_view["currentRevision"]
                collaboration_version = submitted_view["collaborationVersion"]
                after = app.state.trip_draft_revision_creator.get_current(
                    UUID(trip_id)
                )
                after_participants = {
                    item.member_key: item
                    for item in after.understanding.participants
                }
                assert after_participants[member_key].nickname == (
                    expected_nicknames[member_key]
                )
                for other_key in set(bindings) - {member_key}:
                    assert after_participants[other_key] == before_participants[
                        other_key
                    ]
            assert base_revision == 3
            assert gateway.calls == 4

            organizer_confirmation = await client.post(
                f"/api/v2/trips/{trip_id}/participants/{organizer_id}/confirm",
                headers={
                    "X-Organizer-Token": organizer_token,
                    "Idempotency-Key": "s2-t032-confirm-organizer-0001",
                },
                json={
                    "schemaVersion": "1.0",
                    "baseRevision": base_revision,
                    "expectedVersion": collaboration_version,
                },
            )
            assert organizer_confirmation.status_code == 200
            collaboration_version = organizer_confirmation.json()["data"][
                "collaborationVersion"
            ]
            for index, member_key in enumerate(("member-2", "member-3"), start=2):
                confirmed = await client.post(
                    "/api/v2/member-session/confirm",
                    headers={
                        "X-Participant-Session": member_tokens[member_key],
                        "Idempotency-Key": f"s2-t032-confirm-member-000{index}",
                    },
                    json={
                        "schemaVersion": "1.0",
                        "baseRevision": base_revision,
                        "expectedVersion": collaboration_version,
                    },
                )
                assert confirmed.status_code == 200, confirmed.text
                collaboration_version = confirmed.json()["data"][
                    "collaborationVersion"
                ]

            conflicted = await client.get(
                f"/api/v2/trips/{trip_id}/collaboration",
                headers={"X-Organizer-Token": organizer_token},
            )
            assert conflicted.status_code == 200, conflicted.text
            conflict_state = conflicted.json()["data"]
            assert conflict_state["status"] == "CONFLICT_REVIEW"
            assert conflict_state["canPlan"] is False
            assert conflict_state["progress"] == {
                "expectedCount": 3,
                "confirmedCount": 2,
                "openIssueCount": 1,
            }

            blocked_provider = await client.post(
                "/api/v1/places/search",
                headers={
                    "X-Organizer-Token": organizer_token,
                    "Idempotency-Key": "s2-t032-block-provider-0001",
                },
                json=_provider_search_payload(trip_id),
            )
            blocked_recommendation = await client.get(
                f"/api/v2/trips/{trip_id}/recommendations",
                headers={
                    "X-Organizer-Token": organizer_token,
                    "Idempotency-Key": "s2-t032-block-recommend-0001",
                },
            )
            for blocked in (blocked_provider, blocked_recommendation):
                assert (blocked.status_code, blocked.json()["code"]) == (
                    409,
                    "COLLABORATION_NOT_READY",
                )
            assert (
                provider.resolve_calls,
                provider.search_calls,
                provider.route_calls,
            ) == (0, 0, 0)
            with sqlite3.connect(database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM plan_versions WHERE trip_id=?",
                    (trip_id,),
                ).fetchone()[0] == 0

            issue = next(
                item
                for item in conflict_state["confirmationItems"]
                if item["ruleId"] == "S2T003.BUDGET.CAP_BELOW_SHARED"
            )
            assert issue["participantId"] == bindings["member-3"]
            relaxation = next(
                item
                for item in issue["allowedRelaxations"]
                if item["actorScope"] == "ORGANIZER"
                and item["action"] == "LOWER_SHARED_BUDGET"
            )
            assert relaxation["proposedValue"] == 40_000
            resolved = await client.post(
                f"/api/v2/trips/{trip_id}/confirmation-items/"
                f"{issue['itemId']}/resolve",
                headers={
                    "X-Organizer-Token": organizer_token,
                    "Idempotency-Key": "s2-t032-resolve-budget-0001",
                },
                json={
                    "schemaVersion": "1.0",
                    "baseRevision": conflict_state["currentRevision"],
                    "expectedVersion": conflict_state["collaborationVersion"],
                    "relaxationId": relaxation["relaxationId"],
                },
            )
            assert resolved.status_code == 200, resolved.text
            after_relaxation = resolved.json()["data"]
            assert after_relaxation["currentRevision"] == 4
            assert after_relaxation["status"] == "COLLECTING_MEMBERS"
            assert after_relaxation["canPlan"] is False
            assert {
                item["confirmationStatus"]
                for item in after_relaxation["participants"]
            } == {"NEEDS_RECONFIRMATION"}

            collaboration_version = after_relaxation["collaborationVersion"]
            reconfirmed_organizer = await client.post(
                f"/api/v2/trips/{trip_id}/participants/{organizer_id}/confirm",
                headers={
                    "X-Organizer-Token": organizer_token,
                    "Idempotency-Key": "s2-t032-reconfirm-organizer-0001",
                },
                json={
                    "schemaVersion": "1.0",
                    "baseRevision": 4,
                    "expectedVersion": collaboration_version,
                },
            )
            assert reconfirmed_organizer.status_code == 200
            collaboration_version = reconfirmed_organizer.json()["data"][
                "collaborationVersion"
            ]
            for index, member_key in enumerate(("member-2", "member-3"), start=2):
                reconfirmed = await client.post(
                    "/api/v2/member-session/confirm",
                    headers={
                        "X-Participant-Session": member_tokens[member_key],
                        "Idempotency-Key": f"s2-t032-reconfirm-member-000{index}",
                    },
                    json={
                        "schemaVersion": "1.0",
                        "baseRevision": 4,
                        "expectedVersion": collaboration_version,
                    },
                )
                assert reconfirmed.status_code == 200, reconfirmed.text
                collaboration_version = reconfirmed.json()["data"][
                    "collaborationVersion"
                ]

            ready = await client.get(
                f"/api/v2/trips/{trip_id}/collaboration",
                headers={"X-Organizer-Token": organizer_token},
            )
            assert ready.status_code == 200, ready.text
            ready_state = ready.json()["data"]
            assert ready_state["status"] == "READY_TO_PLAN"
            assert ready_state["canPlan"] is True
            assert ready_state["progress"] == {
                "expectedCount": 3,
                "confirmedCount": 3,
                "openIssueCount": 0,
            }
            assert ready_state["readinessDigest"] is not None

            client.headers["X-Organizer-Token"] = organizer_token
            city_response = await client.post(
                "/api/v1/cities/resolve",
                json={"schemaVersion": "1.0", "cityName": "北京"},
            )
            assert city_response.status_code == 200, city_response.text
            city_resolution = city_response.json()["data"]
            provider_response = await client.post(
                "/api/v1/places/search",
                headers={"Idempotency-Key": "s2-t032-provider-ready-0001"},
                json=_provider_search_payload(trip_id),
            )
            assert provider_response.status_code == 200, provider_response.text

            recommendation_response = await client.get(
                f"/api/v2/trips/{trip_id}/recommendations",
                headers={"Idempotency-Key": "s2-t032-recommend-ready-0001"},
            )
            assert recommendation_response.status_code == 200, (
                recommendation_response.text
            )
            recommendation = recommendation_response.json()["data"]
            assert 6 <= len(recommendation["candidates"]) <= 8
            assert recommendation["factSetId"]
            assert len(recommendation["providerFactDigest"]) == 64
            trusted_plan = recommendation["trustedPlan"]
            assert trusted_plan is not None
            assert 2 <= len(trusted_plan["tasks"]) <= 3
            assert {
                item["participantId"] for item in trusted_plan["memberScores"]
            } == set(bindings.values())

            planning_trip_response = await client.get(
                f"/api/v2/trips/{trip_id}/planning-trip",
                headers={"Idempotency-Key": "s2-t032-planning-trip-0001"},
            )
            assert planning_trip_response.status_code == 200, (
                planning_trip_response.text
            )
            planning_trip = planning_trip_response.json()["data"]
            assert planning_trip["tripId"] == trip_id
            assert planning_trip["mode"] == "GROUP"
            assert planning_trip["status"] == "DRAFT"
            assert [
                item["participantId"] for item in planning_trip["participants"]
            ] == [bindings[f"member-{index}"] for index in range(1, 4)]

            planning_request, recommendation_trace = (
                await _candidate_request_from_trusted_plan(
                    client,
                    trip=deepcopy(planning_trip),
                    city_resolution=city_resolution,
                    recommendation=recommendation,
                )
            )
            current_revision = app.state.trip_draft_revision_creator.get_current(
                UUID(trip_id)
            )
            merged = merged_constraints_for_revision(current_revision)
            assert len(merged.constraints) > 0
            planning_request["confirmedConstraints"] = [
                item.model_dump(mode="json", by_alias=True)
                for item in merged.constraints
            ]
            assert recommendation_trace["selectedFactRefs"] == [
                item["factRefId"] for item in trusted_plan["tasks"]
            ]

            generated = await client.post(
                f"/api/v1/trips/{trip_id}/plan-versions/generate",
                headers={"Idempotency-Key": "s2-t032-generate-v1-0001"},
                json=planning_request,
            )
            if generated.status_code == 422:
                assert generated.json()["code"] == "CANDIDATE_CONFIRMATION_REQUIRED"
                review = generated.json()["errors"][0]["review"]
                reviewed = await client.post(
                    f"/api/v1/trips/{trip_id}/plan-reviews/"
                    f"{review['reviewId']}/confirm",
                    headers={
                        "Idempotency-Key": "s2-t032-confirm-review-0001"
                    },
                    json={
                        "schemaVersion": "1.0",
                        "confirmations": _review_confirmations(review, _fixture()),
                    },
                )
                assert reviewed.status_code == 200, reviewed.text
                v1 = reviewed.json()["data"]
            else:
                assert generated.status_code == 200, generated.text
                v1 = generated.json()["data"]
            v1_id = v1["planId"]
            assert v1["version"] == 1
            assert v1["tripSnapshot"]["mode"] == "GROUP"
            assert [
                item["participantId"]
                for item in v1["tripSnapshot"]["participants"]
            ] == [bindings[f"member-{index}"] for index in range(1, 4)]

            denied_v1 = await client.post(
                f"/api/v1/trips/{trip_id}/plan-versions/{v1_id}/confirm",
                headers={
                    "X-Organizer-Token": "",
                    "X-Participant-Session": member_tokens["member-2"],
                    "Idempotency-Key": "s2-t032-member-confirm-v1-0001",
                },
            )
            assert (denied_v1.status_code, denied_v1.json()["code"]) == (
                403,
                "ORGANIZER_PERMISSION_REQUIRED",
            )
            confirmed_v1 = await client.post(
                f"/api/v1/trips/{trip_id}/plan-versions/{v1_id}/confirm",
                headers={"Idempotency-Key": "s2-t032-organizer-confirm-v1-0001"},
            )
            assert confirmed_v1.status_code == 200, confirmed_v1.text
            started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
            assert started.status_code == 200, started.text
            assert started.json()["data"]["planId"] == v1_id

            restored_facts = await client.get(
                f"/api/v1/trips/{trip_id}/planning-facts",
                headers={"Idempotency-Key": "s2-t032-restore-facts-0001"},
            )
            assert restored_facts.status_code == 200, restored_facts.text
            restored_request = restored_facts.json()["data"]
            assert restored_request["trip"]["tripId"] == trip_id
            assert restored_request["trip"]["mode"] == "GROUP"
            assert restored_request["confirmedConstraints"] == planning_request[
                "confirmedConstraints"
            ]

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
                    "idempotencyKey": "s2-t032-arrival-evidence-0001",
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
                    "idempotencyKey": "s2-t032-arrival-complete-0001",
                    "occurredAt": "2026-09-05T10:30:05+08:00",
                },
            )
            assert completed.status_code == 200, completed.text
            complete_event = completed.json()["data"]

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
                key="s2-t032-task-start-0001",
                occurred_at="2026-09-05T11:00:00+08:00",
            )
            late = await _persist_adjustment(
                client,
                trip_id=trip_id,
                plan_id=v1_id,
                task_id=current_task["taskId"],
                event_type="LATE",
                key="s2-t032-late-0001",
                occurred_at="2026-09-05T11:10:00+08:00",
            )
            fatigue = await _persist_adjustment(
                client,
                trip_id=trip_id,
                plan_id=v1_id,
                task_id=current_task["taskId"],
                event_type="FATIGUE",
                key="s2-t032-fatigue-0001",
                occurred_at="2026-09-05T11:20:00+08:00",
            )
            assert late["eventType"] == "LATE"
            assert fatigue["eventType"] == "FATIGUE"

            preview = await client.post(
                f"/api/v1/trips/{trip_id}/replans/from-adjustment",
                headers={"Idempotency-Key": "s2-t032-v2-preview-0001"},
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
            assert v2["version"] == 2
            assert v2["parentId"] == v1_id
            assert v2["status"] == "PROPOSED"
            assert v2["tripSnapshot"]["mode"] == "GROUP"
            assert preview_data["diff"]["basePlanId"] == v1_id
            assert preview_data["diff"]["candidatePlanId"] == v2["planId"]
            assert preview_data["frozenTaskIds"][:2] == [
                first_task["taskId"],
                current_task["taskId"],
            ]

            before_decision = await client.get(f"/api/v1/trips/{trip_id}")
            assert before_decision.status_code == 200
            assert before_decision.json()["data"]["currentPlan"]["planId"] == v1_id
            denied_v2 = await client.post(
                f"/api/v1/trips/{trip_id}/replans/{v2['planId']}/decision",
                headers={
                    "X-Organizer-Token": "",
                    "X-Participant-Session": member_tokens["member-3"],
                    "Idempotency-Key": "s2-t032-member-v2-decision-0001",
                },
                json={"schemaVersion": "1.0", "decision": "ACCEPT"},
            )
            assert (denied_v2.status_code, denied_v2.json()["code"]) == (
                403,
                "ORGANIZER_PERMISSION_REQUIRED",
            )
            unchanged = await client.get(f"/api/v1/trips/{trip_id}")
            assert unchanged.json()["data"]["currentPlan"]["planId"] == v1_id

            accepted = await client.post(
                f"/api/v1/trips/{trip_id}/replans/{v2['planId']}/decision",
                headers={"Idempotency-Key": "s2-t032-organizer-v2-accept-0001"},
                json={"schemaVersion": "1.0", "decision": "ACCEPT"},
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["data"]["result"]["currentPlanId"] == v2[
                "planId"
            ]
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
            assert timeline["summary"]["assistanceProfile"] is None
            assert [
                (
                    item["participantId"],
                    item["nickname"],
                    item["assistanceProfile"]["type"],
                )
                for item in timeline["summary"]["participantCareResults"]
            ] == [
                (
                    bindings[member_key],
                    expected_nicknames[member_key],
                    "LOW_STAMINA",
                )
                for member_key in ("member-1", "member-2", "member-3")
            ]
            plan_items = [
                item for item in timeline["items"] if item["kind"] == "PLAN_VERSION"
            ]
            assert [item["planVersionId"] for item in plan_items] == [
                v1_id,
                v2["planId"],
            ]
            photos = [
                item for item in timeline["items"] if item["kind"] == "PHOTO"
            ]
            assert len(photos) == 1
            assert photos[0]["taskId"] == first_task["taskId"]
            assert photos[0]["photo"]["mediaId"] == replacement.json()["data"][
                "mediaId"
            ]
            serialized_timeline = json.dumps(timeline, ensure_ascii=False)
            assert "data:image/jpeg;base64," + "A" * 64 not in serialized_timeline
            assert "data:image/jpeg;base64," + "B" * 64 in serialized_timeline
            assert "data:image/jpeg;base64," + "C" * 64 not in serialized_timeline
            occurred = [
                datetime.fromisoformat(item["occurredAt"])
                for item in timeline["items"]
            ]
            assert occurred == sorted(occurred)

    with sqlite3.connect(database_path) as connection:
        lineage_tables = (
            "collaboration_sessions",
            "trip_draft_revisions",
            "participant_invitations",
            "confirmed_trip_inputs",
            "provider_fact_sets",
            "plan_versions",
            "trusted_plan_issuances",
            "execution_events",
            "execution_adjustment_events",
            "arrival_evidence",
            "task_media",
        )
        table_trip_ids = {
            table: {
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT trip_id FROM {table}"
                ).fetchall()
            }
            for table in lineage_tables
        }
        assert all(ids == {trip_id} for ids in table_trip_ids.values())
        assert connection.execute(
            "SELECT revision FROM trip_draft_revisions "
            "WHERE trip_id=? ORDER BY revision",
            (trip_id,),
        ).fetchall() == [(1,), (2,), (3,), (4,)]
        assert connection.execute(
            "SELECT participant_id FROM participant_invitations "
            "WHERE trip_id=? ORDER BY participant_id",
            (trip_id,),
        ).fetchall() == [
            (participant_id,)
            for participant_id in sorted(
                (bindings["member-2"], bindings["member-3"])
            )
        ]
        stored_plans = connection.execute(
            "SELECT version,status,snapshot_json FROM plan_versions "
            "WHERE trip_id=? ORDER BY version",
            (trip_id,),
        ).fetchall()
        assert [(row[0], row[1]) for row in stored_plans] == [
            (1, "SUPERSEDED"),
            (2, "CURRENT"),
        ]
        assert json.loads(stored_plans[0][2])["tripSnapshot"]["tripId"] == trip_id
        assert json.loads(stored_plans[1][2])["parentId"] == v1_id
        assert connection.execute(
            "SELECT event_type,plan_version_id FROM execution_adjustment_events "
            "WHERE trip_id=? ORDER BY occurred_at",
            (trip_id,),
        ).fetchall() == [("LATE", v1_id), ("FATIGUE", v1_id)]
        assert connection.execute(
            "SELECT boundary_kind,issuance_state FROM trusted_plan_issuances "
            "WHERE trip_id=? ORDER BY plan_version",
            (trip_id,),
        ).fetchall() == [("V1", "ISSUED"), ("V2", "ISSUED")]
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
