from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.application.collaboration_service import CollaborationService
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import (
    ActorScope,
    CollaborationIssue,
    CollaborationStatus,
    ParticipantConfirmationStatus,
    ResolveConfirmationItemRequest,
)
from app.domain.collaboration_digest import member_digest, shared_digest
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.main import create_app
from backend.tests.s2_t003_support import (
    FakeTripDraftRevisionPort,
    revision_with_places,
    revision_with_trip_budget,
)
from backend.tests.test_s2_t003_collaboration_service import _ready_harness


FIXTURE = Path(__file__).parent / "fixtures" / "collaboration" / "s2_t029_conflict_case.json"


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
