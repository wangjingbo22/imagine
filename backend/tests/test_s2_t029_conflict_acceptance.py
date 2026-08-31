from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.application.collaboration_service import CollaborationService
from app.application.trip_draft_revision_service import TripDraftRevisionService
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import (
    ActorScope,
    CollaborationIssue,
    CollaborationStatus,
    OrganizerConversationRequest,
    ParticipantConfirmationStatus,
    QUESTION_IDS,
    ResolveConfirmationItemRequest,
)
from app.domain.collaboration_digest import member_digest, shared_digest
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.domain.trip_draft import (
    CareDraft,
    CareWalkLimits,
    FieldEvidence,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
)
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.infrastructure.trip_draft_revision_store import (
    SqliteTripDraftRevisionRepository,
)
from app.main import create_app
from backend.tests.s2_t003_support import (
    FakeTripDraftRevisionPort,
    revision_with_places,
    revision_with_trip_budget,
)
from backend.tests.test_s2_t003_collaboration_service import _ready_harness


FIXTURE = Path(__file__).parent / "fixtures" / "collaboration" / "s2_t029_conflict_case.json"
TRIP_UNDERSTANDING_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "trip_understanding"
    / "two_participants.json"
)


class SingleProposalGateway:
    def __init__(self, proposal: TripUnderstandingProposal) -> None:
        self.proposal = proposal
        self.calls = 0

    async def understand(self, request: Any) -> TripUnderstandingGatewayResult:
        del request
        self.calls += 1
        return TripUnderstandingGatewayResult(
            decision="MODEL_PROPOSAL",
            proposal=self.proposal,
            failureCode=None,
            callCount=1,
            model="t029-integration-fixture",
        )


def _complete_budget_conflict_proposal() -> TripUnderstandingProposal:
    proposal = TripUnderstandingProposal.model_validate_json(
        TRIP_UNDERSTANDING_FIXTURE.read_text(encoding="utf-8"),
        strict=True,
    )
    ordinary = CareDraft(
        assistanceTypeHint="ORDINARY",
        childAge=None,
        walkLimits=CareWalkLimits(
            maxContinuousMeters=None,
            maxDailyMeters=None,
        ),
        maxTransfers=None,
        restIntervalMinutes=None,
        napWindow=None,
        avoidStairs=False,
    )
    participants = [
        participant.model_copy(update={"care_draft": ordinary})
        for participant in proposal.participants
    ]
    evidence = [*proposal.field_evidence]
    for index, participant in enumerate(participants):
        evidence.extend(
            [
                FieldEvidence(
                    fieldPath=(
                        f"participants[{index}].careDraft.assistanceTypeHint"
                    ),
                    memberKey=participant.member_key,
                    sourceType="USER_TEXT",
                    sourceText="ordinary assistance",
                ),
                FieldEvidence(
                    fieldPath=f"participants[{index}].careDraft.avoidStairs",
                    memberKey=participant.member_key,
                    sourceType="USER_TEXT",
                    sourceText="no stair restriction",
                ),
            ]
        )
    return proposal.model_copy(
        update={
            # member-2 has a 400 CNY cap, so 450 CNY creates one deterministic
            # organizer-resolvable shared-budget conflict.
            "trip": proposal.trip.model_copy(update={"budget_cents": 45_000}),
            "participants": participants,
            "field_evidence": evidence,
            "missing_fields": [],
            "confirmation_questions": [],
        }
    )


def _organizer_request() -> OrganizerConversationRequest:
    source = json.loads(TRIP_UNDERSTANDING_FIXTURE.read_text(encoding="utf-8"))
    evidence = " ".join(item["sourceText"] for item in source["fieldEvidence"])
    natural_language_request = (
        f"{evidence} ordinary assistance no stair restriction"
    )
    return OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate="2026-08-28",
        naturalLanguageRequest=natural_language_request,
        answers=[
            {"questionId": question_id, "answer": natural_language_request}
            for question_id in QUESTION_IDS
        ],
    )


class ResolvingBudgetRevisionPort(FakeTripDraftRevisionPort):
    def apply_relaxation(self, **kwargs):
        self.relaxation_calls += 1
        patch = kwargs["patch"]
        assert patch.action.value == "LOWER_SHARED_BUDGET"
        trip = self.current.understanding.trip.model_copy(
            update={"budget_cents": patch.value}
        )
        self.current = replace(
            self.current,
            revision=self.current.revision + 1,
            source_digest="b" * 64,
            understanding=self.current.understanding.model_copy(update={"trip": trip}),
        )
        return self.current


def test_cross_member_place_conflict_matches_frozen_t029_fixture(tmp_path: Path) -> None:
    harness = _ready_harness(tmp_path)
    revision = revision_with_places(
        harness.revision,
        must_visit=["A"],
        avoid_places=["Ａ"],
    )
    issue = next(
        item
        for item in DeterministicHardConflictEvaluator().evaluate(
            revision,
            organizer_participant_id=revision.member_bindings["member-1"],
        )
        if item.rule_id == "S2T003.PLACE.MUST_AVOID"
    )
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = issue.model_dump(mode="json", by_alias=True)

    assert actual == expected
    assert "allowedRelaxations" in actual
    assert "relaxations" not in actual
    assert issue.participant_id == revision.member_bindings["member-2"]
    assert issue.related_participant_ids == [revision.member_bindings["member-1"]]
    assert issue.reason
    assert {item.actor_scope for item in issue.relaxations} == {ActorScope.PARTICIPANT}


def test_t029_accepts_legacy_input_but_always_serializes_canonical_name() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    legacy = {**payload, "relaxations": payload["allowedRelaxations"]}
    legacy.pop("allowedRelaxations")
    issue = CollaborationIssue.model_validate(legacy)

    serialized = issue.model_dump(mode="json", by_alias=True)
    assert serialized["allowedRelaxations"] == payload["allowedRelaxations"]
    assert "relaxations" not in serialized


@pytest.mark.asyncio
async def test_http_organizer_view_uses_canonical_t029_conflict_contract(tmp_path: Path) -> None:
    harness = _ready_harness(tmp_path)
    revisions = FakeTripDraftRevisionPort(
        revision_with_places(harness.revision, must_visit=["A"], avoid_places=["Ａ"])
    )
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
        ),
        collaboration_repository=harness.repository,
        trip_draft_revision_port=revisions,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/collaboration",
            headers={"X-Organizer-Token": harness.organizer_token},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CONFLICT_REVIEW"
    assert data["canPlan"] is False
    place_issue = next(
        item for item in data["confirmationItems"]
        if item["ruleId"] == "S2T003.PLACE.MUST_AVOID"
    )
    assert place_issue["participantId"] == "10000000-0000-4000-8000-000000000002"
    assert place_issue["reason"]
    assert len(place_issue["allowedRelaxations"]) == 2
    assert "relaxations" not in place_issue


@pytest.mark.asyncio
async def test_real_sqlite_asgi_conflict_relaxation_reconfirmation_reaches_ready(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "s2-t029-integration.sqlite3"
    gateway = SingleProposalGateway(_complete_budget_conflict_proposal())
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=object(),  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )

    assert isinstance(app.state.trip_draft_revision_creator, TripDraftRevisionService)
    assert isinstance(
        app.state.trip_draft_revision_creator.repository,
        SqliteTripDraftRevisionRepository,
    )
    assert isinstance(
        app.state.collaboration_service.repository,
        SqliteCollaborationRepository,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": "s2-t029-real-create-0001"},
            json=_organizer_request().model_dump(mode="json", by_alias=True),
        )
        assert created.status_code == 200
        created_data = created.json()["data"]
        revision = created_data["revision"]
        trip_id = revision["tripId"]
        bindings = revision["memberBindings"]
        organizer_token = created_data["organizerAccess"]["organizerToken"]
        assert revision["revision"] == 1

        organizer_confirmation = await client.post(
            f"/api/v2/trips/{trip_id}/participants/{bindings['member-1']}/confirm",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t029-real-confirm-0001",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": 1,
                "expectedVersion": 1,
            },
        )
        assert organizer_confirmation.status_code == 200
        collaboration_version = organizer_confirmation.json()["data"][
            "collaborationVersion"
        ]

        invitation = await client.post(
            f"/api/v2/trips/{trip_id}/participants/{bindings['member-2']}/invitations",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t029-real-invite-0001",
            },
            json={
                "schemaVersion": "1.0",
                "expectedVersion": collaboration_version,
            },
        )
        assert invitation.status_code == 200
        invitation_data = invitation.json()["data"]
        invitation_token = invitation_data["invitationUrl"].rsplit("/", 1)[1]
        collaboration_version = invitation_data["collaborationVersion"]

        redeemed = await client.post(
            "/api/v2/participant-invitations/redeem",
            headers={"Idempotency-Key": "s2-t029-real-redeem-0001"},
            json={"schemaVersion": "1.0", "token": invitation_token},
        )
        assert redeemed.status_code == 200
        member_token = redeemed.json()["data"]["participantSessionToken"]

        member_confirmation = await client.post(
            "/api/v2/member-session/confirm",
            headers={
                "X-Participant-Session": member_token,
                "Idempotency-Key": "s2-t029-real-confirm-0002",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": 1,
                "expectedVersion": collaboration_version,
            },
        )
        assert member_confirmation.status_code == 200

        conflicted = await client.get(
            f"/api/v2/trips/{trip_id}/collaboration",
            headers={"X-Organizer-Token": organizer_token},
        )
        assert conflicted.status_code == 200
        conflict_state = conflicted.json()["data"]
        assert conflict_state["status"] == "CONFLICT_REVIEW"
        assert conflict_state["canPlan"] is False
        assert conflict_state["progress"] == {
            "expectedCount": 2,
            # The persisted confirmation for the affected member is deliberately
            # not counted as ready while that member still owns an open issue.
            "confirmedCount": 1,
            "openIssueCount": 1,
        }
        issue = next(
            item
            for item in conflict_state["confirmationItems"]
            if item["ruleId"] == "S2T003.BUDGET.CAP_BELOW_SHARED"
        )
        relaxation = next(
            item
            for item in issue["allowedRelaxations"]
            if item["actorScope"] == "ORGANIZER"
        )
        assert relaxation["action"] == "LOWER_SHARED_BUDGET"
        assert relaxation["proposedValue"] == 40_000

        resolved = await client.post(
            f"/api/v2/trips/{trip_id}/confirmation-items/{issue['itemId']}/resolve",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t029-real-resolve-0001",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": conflict_state["currentRevision"],
                "expectedVersion": conflict_state["collaborationVersion"],
                "relaxationId": relaxation["relaxationId"],
            },
        )
        assert resolved.status_code == 200
        after_relaxation = resolved.json()["data"]
        assert after_relaxation["currentRevision"] == 2
        assert after_relaxation["status"] == "COLLECTING_MEMBERS"
        assert after_relaxation["canPlan"] is False
        assert after_relaxation["progress"]["openIssueCount"] == 0
        assert {
            participant["confirmationStatus"]
            for participant in after_relaxation["participants"]
        } == {"NEEDS_RECONFIRMATION"}

        organizer_reconfirmation = await client.post(
            f"/api/v2/trips/{trip_id}/participants/{bindings['member-1']}/confirm",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t029-real-reconfirm-0001",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": 2,
                "expectedVersion": after_relaxation["collaborationVersion"],
            },
        )
        assert organizer_reconfirmation.status_code == 200
        collaboration_version = organizer_reconfirmation.json()["data"][
            "collaborationVersion"
        ]

        member_reconfirmation = await client.post(
            "/api/v2/member-session/confirm",
            headers={
                "X-Participant-Session": member_token,
                "Idempotency-Key": "s2-t029-real-reconfirm-0002",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": 2,
                "expectedVersion": collaboration_version,
            },
        )
        assert member_reconfirmation.status_code == 200

        ready = await client.get(
            f"/api/v2/trips/{trip_id}/collaboration",
            headers={"X-Organizer-Token": organizer_token},
        )

    assert ready.status_code == 200
    ready_state = ready.json()["data"]
    assert ready_state["status"] == "READY_TO_PLAN"
    assert ready_state["canPlan"] is True
    assert ready_state["readinessDigest"] is not None
    assert ready_state["progress"] == {
        "expectedCount": 2,
        "confirmedCount": 2,
        "openIssueCount": 0,
    }
    assert gateway.calls == 1

    revision_repository = app.state.trip_draft_revision_creator.repository
    current = revision_repository.get_current(UUID(revision["tripId"]))
    assert current.revision == 2
    assert current.understanding.trip.budget_cents == 40_000
    with revision_repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions WHERE trip_id=?",
            (trip_id,),
        ).fetchone()[0] == 2

    collaboration_repository = app.state.collaboration_service.repository
    stored = collaboration_repository.get_stored(UUID(revision["tripId"]))
    assert stored.current_revision == 2
    with collaboration_repository._connect() as connection:
        audit = connection.execute(
            "SELECT before_revision, after_revision FROM collaboration_resolution_audit "
            "WHERE trip_id=?",
            (trip_id,),
        ).fetchone()
    assert tuple(audit) == (1, 2)


def test_conflict_review_blocks_readiness_before_any_downstream_call(tmp_path: Path) -> None:
    harness = _ready_harness(tmp_path)
    revisions = FakeTripDraftRevisionPort(
        revision_with_places(harness.revision, must_visit=["A"], avoid_places=["Ａ"])
    )
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    downstream_calls = 0

    assert state.status is CollaborationStatus.CONFLICT_REVIEW
    assert state.can_plan is False
    assert state.readiness_digest is None
    with pytest.raises(AppError) as captured:
        service.require_ready(harness.revision.trip_id, harness.organizer_token)
        downstream_calls += 1
    assert captured.value.code == "COLLABORATION_NOT_READY"
    assert downstream_calls == 0


def test_organizer_relaxation_requires_reconfirmation_before_ready(tmp_path: Path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = ResolvingBudgetRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    before = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in before.confirmation_items if item.rule_id == "S2T003.BUDGET.CAP_BELOW_SHARED")
    option = next(item for item in issue.relaxations if item.actor_scope is ActorScope.ORGANIZER)

    after_relaxation = service.resolve_organizer_issue(
        trip_id=harness.revision.trip_id,
        item_id=issue.item_id,
        request=ResolveConfirmationItemRequest(
            schemaVersion="1.0",
            baseRevision=conflict.revision,
            expectedVersion=before.collaboration_version,
            relaxationId=option.relaxation_id,
        ),
        organizer_token=harness.organizer_token,
        idempotency_key="s2-t029-resolve-0001",
    )

    assert revisions.relaxation_calls == 1
    assert after_relaxation.status is CollaborationStatus.COLLECTING_MEMBERS
    assert after_relaxation.can_plan is False
    assert not after_relaxation.confirmation_items
    assert {
        item.confirmation_status for item in after_relaxation.participants
    } == {ParticipantConfirmationStatus.NEEDS_RECONFIRMATION}

    current = revisions.current
    version = harness.repository.get_stored(current.trip_id).version
    for index, member_key in enumerate(sorted(current.member_bindings), start=1):
        harness.repository.record_confirmation(
            trip_id=current.trip_id,
            participant_id=current.member_bindings[member_key],
            revision=current.revision,
            source_digest=current.source_digest,
            shared_digest=shared_digest(current),
            member_digest=member_digest(current, member_key),
            expected_version=version,
            idempotency_key=f"s2-t029-reconfirm-{index:02d}",
        )
        version += 1

    ready = service.organizer_state(current.trip_id, harness.organizer_token)
    assert ready.status is CollaborationStatus.READY_TO_PLAN
    assert ready.can_plan is True
    assert ready.readiness_digest is not None
    assert ready.progress.open_issue_count == 0
