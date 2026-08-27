import pytest

from app.domain.collaboration import ActorScope, IssueCode
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
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
