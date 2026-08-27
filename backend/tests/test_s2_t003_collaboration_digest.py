from dataclasses import replace

import pytest

from app.domain.collaboration_digest import member_digest, readiness_digest, shared_digest
from backend.tests.s2_t003_support import (
    load_revision,
    revision_with_member_budget,
    revision_with_trip_budget,
)


@pytest.fixture
def two_person_revision():
    return load_revision()


def test_digest_is_order_stable_and_business_value_sensitive(two_person_revision) -> None:
    first = shared_digest(two_person_revision)
    reordered = replace(
        two_person_revision,
        member_bindings=dict(reversed(tuple(two_person_revision.member_bindings.items()))),
    )
    assert shared_digest(reordered) == first
    changed = revision_with_trip_budget(two_person_revision, 60_000)
    assert shared_digest(changed) != first


def test_member_change_only_invalidates_its_member_digest(two_person_revision) -> None:
    before_1 = member_digest(two_person_revision, "member-1")
    before_2 = member_digest(two_person_revision, "member-2")
    changed = revision_with_member_budget(two_person_revision, "member-2", 30_000)
    assert member_digest(changed, "member-1") == before_1
    assert member_digest(changed, "member-2") != before_2


def test_readiness_binds_revision_source_policy_and_confirmations(two_person_revision) -> None:
    confirmations = {
        "member-1": member_digest(two_person_revision, "member-1"),
        "member-2": member_digest(two_person_revision, "member-2"),
    }
    digest = readiness_digest(two_person_revision, confirmations)
    assert len(digest) == 64
    assert readiness_digest(replace(two_person_revision, revision=2), confirmations) != digest
