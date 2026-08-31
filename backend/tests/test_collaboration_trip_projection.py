from __future__ import annotations

from dataclasses import replace

from app.application.collaboration_planning_bridge import (
    CollaborationPlanningBridge,
)
from app.application.recommendation_service import (
    project_collaboration_recommendation_trip,
)
from app.domain.trip_draft import CareDraft, CareWalkLimits
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig
from backend.tests.s2_t003_support import load_revision


class RecordingWorkflow:
    def __init__(self) -> None:
        self.confirmed_trip = None

    def confirm_collaboration_trip(self, trip):
        self.confirmed_trip = trip
        return trip


def _ready_revision_with_optional_member_fields():
    revision = load_revision()
    ordinary_care = CareDraft(
        assistanceTypeHint="ORDINARY",
        childAge=None,
        walkLimits=CareWalkLimits(
            maxContinuousMeters=None,
            maxDailyMeters=None,
        ),
        maxTransfers=None,
        restIntervalMinutes=None,
        napWindow=None,
        avoidStairs=None,
    )
    participants = [
        participant.model_copy(update={"care_draft": ordinary_care})
        for participant in revision.understanding.participants
    ]
    participants[1] = participants[1].model_copy(
        update={"nickname": None, "budget_cap_cents": None}
    )
    understanding = revision.understanding.model_copy(
        update={
            "participants": participants,
            "missing_fields": [],
            "ambiguities": [],
            "confirmation_questions": [],
        }
    )
    return replace(revision, understanding=understanding)


def _city_context() -> CityContext:
    return CityContext(
        countryCode="CN",
        cityCode="310000",
        cityName="上海市",
        center=GeoPoint(longitude=121.4737, latitude=31.2304),
        providerConfig=ProviderConfig(
            provider="AMAP",
            coordinateSystem="GCJ02",
        ),
    )


def test_optional_member_identity_projects_consistently_for_recommendation_and_plan() -> None:
    revision = _ready_revision_with_optional_member_fields()
    recommendation_trip = project_collaboration_recommendation_trip(
        revision,
        _city_context(),
    )
    workflow = RecordingWorkflow()
    planning_trip = CollaborationPlanningBridge(workflow).materialize(
        revision,
        _city_context(),
    )

    expected = [("Alex", 50_000), ("成员 2", 90_000)]
    assert [
        (participant.nickname, participant.budget_cap_cents)
        for participant in recommendation_trip.participants
    ] == expected
    assert [
        (participant.nickname, participant.budget_cap_cents)
        for participant in planning_trip.participants
    ] == expected
    assert workflow.confirmed_trip == planning_trip
