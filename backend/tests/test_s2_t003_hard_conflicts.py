from dataclasses import replace

import pytest

from app.domain.collaboration import ActorScope, IssueCode
from app.domain.hard_conflicts import (
    DeterministicHardConflictEvaluator,
    merged_constraints_for_revision,
)
from app.domain.trip_draft import CareDraft, CareNapWindow, CareWalkLimits
from backend.tests.s2_t003_support import (
    load_revision,
    revision_with_places,
    revision_with_times,
)


@pytest.fixture
def two_person_revision():
    return load_revision()


def test_missing_and_ambiguity_keep_owner_rule_reason_and_candidates(
    two_person_revision,
) -> None:
    issues = DeterministicHardConflictEvaluator().evaluate(two_person_revision)
    missing = next(item for item in issues if item.code is IssueCode.MISSING)
    assert missing.participant_id == two_person_revision.member_bindings["member-2"]
    assert missing.rule_id == "S2T003.FIELD.REQUIRED"
    assert missing.reason
    assert isinstance(missing.relaxations, list)


def test_time_window_order_is_a_trip_issue(two_person_revision) -> None:
    revision = revision_with_times(two_person_revision, "20:00", "08:30")
    issues = DeterministicHardConflictEvaluator().evaluate(revision)
    issue = next(item for item in issues if item.rule_id == "S2T003.TIME.WINDOW_ORDER")
    assert issue.participant_id is None
    assert issue.field_path == "trip.endTime"


def test_budget_caps_and_nfkc_place_overlap_are_stable(two_person_revision) -> None:
    revision = revision_with_places(
        two_person_revision,
        must_visit=[" Ｔｈｅ　Ｂｕｎｄ "],
        avoid_places=["the bund"],
    )
    first = DeterministicHardConflictEvaluator().evaluate(revision)
    second = DeterministicHardConflictEvaluator().evaluate(revision)
    assert [item.model_dump(mode="json", by_alias=True) for item in first] == [
        item.model_dump(mode="json", by_alias=True) for item in second
    ]
    assert any(item.rule_id == "S2T003.BUDGET.CAP_BELOW_SHARED" for item in first)
    place = next(item for item in first if item.rule_id == "S2T003.PLACE.MUST_AVOID")
    assert len(place.related_participant_ids) == 1
    assert {option.actor_scope for option in place.relaxations} == {
        ActorScope.PARTICIPANT
    }


def _care(
    *,
    continuous: int,
    transfers: int,
    rest: int,
    nap_start: str,
    nap_end: str,
) -> CareDraft:
    return CareDraft(
        assistanceTypeHint="LOW_STAMINA",
        childAge=None,
        walkLimits=CareWalkLimits(
            maxContinuousMeters=continuous,
            maxDailyMeters=None,
        ),
        maxTransfers=transfers,
        restIntervalMinutes=rest,
        napWindow=CareNapWindow(start=nap_start, end=nap_end),
        avoidStairs=None,
    )


@pytest.fixture
def care_revision(two_person_revision):
    participants = list(two_person_revision.understanding.participants)
    participants[0] = participants[0].model_copy(update={
        "care_draft": _care(
            continuous=500, transfers=0, rest=60,
            nap_start="13:00", nap_end="13:30",
        )
    })
    participants[1] = participants[1].model_copy(update={
        "care_draft": _care(
            continuous=1000, transfers=2, rest=90,
            nap_start="13:30", nap_end="14:00",
        )
    })
    proposal = two_person_revision.understanding.model_copy(update={
        "participants": participants,
        "missing_fields": [],
        "ambiguities": [],
        "confirmation_questions": [],
    })
    return replace(two_person_revision, understanding=proposal)


@pytest.fixture
def invalid_care_revision(care_revision):
    participants = list(care_revision.understanding.participants)
    invalid = participants[1].care_draft.model_copy(
        update={"assistance_type_hint": None}
    )
    participants[1] = participants[1].model_copy(update={"care_draft": invalid})
    return replace(
        care_revision,
        understanding=care_revision.understanding.model_copy(
            update={"participants": participants}
        ),
    )


def test_stricter_walk_transfer_and_rest_limits_merge_without_issue(
    care_revision,
) -> None:
    issues = DeterministicHardConflictEvaluator().evaluate(care_revision)
    assert not any("CONSTRAINT_MERGE" in item.rule_id for item in issues)
    merged = merged_constraints_for_revision(care_revision)
    values = {item.field: item.value for item in merged.constraints}
    assert values["walkLimits.maxContinuousMeters"] == 500
    assert values["maxTransfers"] == 0
    assert values["restInterval"] == 60


def test_nap_convex_hull_covering_trip_window_is_conflict(care_revision) -> None:
    revision = revision_with_times(care_revision, "13:00", "14:00")
    issues = DeterministicHardConflictEvaluator().evaluate(revision)
    issue = next(item for item in issues if item.rule_id == "S2T003.TIME.BLOCKS_ALL_DAY")
    assert issue.code is IssueCode.CONFLICT
    assert set(issue.related_participant_ids)


def test_invalid_care_profile_is_field_addressable(invalid_care_revision) -> None:
    issues = DeterministicHardConflictEvaluator().evaluate(invalid_care_revision)
    issue = next(item for item in issues if item.rule_id == "S2T003.CARE.PROFILE_INVALID")
    assert issue.participant_id == invalid_care_revision.member_bindings["member-2"]
