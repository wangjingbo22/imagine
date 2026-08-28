from __future__ import annotations

from uuid import UUID

from app.application.collaboration_ports import TripDraftRevisionView
from app.application.workflow_service import WorkflowService
from app.core.errors import AppError
from app.domain.hard_conflicts import assistance_profile_from_care
from app.schemas.trip import (
    CityContext,
    CreateSingleDayTrip,
    Participant,
    Preference,
    PreferenceType,
    TripDayInput,
)


class SingleCollaborationPlanningBridge:
    """Idempotently project one READY collaboration revision into S1 planning.

    T032 owns the group projection.  This bridge deliberately handles exactly
    one confirmed participant and reuses the existing immutable Trip and
    constraint stores instead of introducing a second planning authority.
    """

    def __init__(self, workflow_service: WorkflowService) -> None:
        self._workflow = workflow_service

    def materialize(
        self,
        revision: TripDraftRevisionView,
        city_context: CityContext,
    ) -> CreateSingleDayTrip | None:
        proposal = revision.understanding
        if len(proposal.participants) != 1:
            return None

        shared = proposal.trip
        participant = proposal.participants[0]
        missing = [
            path
            for path, value in (
                ("trip.cityName", shared.city_name),
                ("trip.travelDate", shared.travel_date),
                ("trip.startTime", shared.start_time),
                ("trip.endTime", shared.end_time),
                ("trip.startLocationText", shared.start_location_text),
                ("trip.endLocationText", shared.end_location_text),
                ("trip.budgetCents", shared.budget_cents),
                ("participants[0].nickname", participant.nickname),
                ("participants[0].budgetCapCents", participant.budget_cap_cents),
                ("participants[0].careDraft", participant.care_draft),
            )
            if value is None
        ]
        if missing:
            raise AppError(
                "COLLABORATION_CANONICAL_TRIP_INCOMPLETE",
                "READY 协作版本缺少生成 canonical Trip 所需字段",
                409,
                False,
                errors=[{"path": path, "message": "required"} for path in missing],
            )

        care = participant.care_draft
        assert care is not None
        if care.assistance_type_hint is None:
            raise AppError(
                "COLLABORATION_CANONICAL_TRIP_INCOMPLETE",
                "READY 协作版本缺少已确认关怀类型",
                409,
                False,
            )
        # Reuse the exact compiler used by READY/conflict evaluation so preset
        # defaults and explicit overrides cannot acquire a second meaning at
        # the planning hand-off.
        assistance = assistance_profile_from_care(care)
        preferences = [
            Preference(
                type=PreferenceType.INTEREST,
                value=value,
                weight=4,
                is_hard=False,
            )
            for value in participant.interests
        ]
        preferences.extend(
            Preference(
                type=PreferenceType.MUST_VISIT,
                value=value,
                weight=5,
                is_hard=True,
            )
            for value in participant.must_visit
        )
        preferences.extend(
            Preference(
                type=PreferenceType.AVOID_PLACE,
                value=value,
                weight=5,
                is_hard=True,
            )
            for value in participant.avoid_places
        )

        member_id = revision.member_bindings.get(participant.member_key)
        if not isinstance(member_id, UUID):
            raise AppError(
                "COLLABORATION_MEMBER_BINDING_INVALID",
                "READY 协作版本缺少成员 canonical participantId",
                409,
                False,
            )

        assert shared.travel_date is not None
        assert shared.start_time is not None and shared.end_time is not None
        assert shared.start_location_text is not None
        assert shared.end_location_text is not None
        assert shared.budget_cents is not None
        assert participant.nickname is not None
        assert participant.budget_cap_cents is not None
        trip = CreateSingleDayTrip(
            schema_version="1.0",
            trip_id=revision.trip_id,
            mode="SINGLE",
            status="DRAFT",
            city_context=city_context,
            start_date=shared.travel_date,
            end_date=shared.travel_date,
            currency="CNY",
            total_budget_cents=shared.budget_cents,
            participants=[
                Participant(
                    participant_id=member_id,
                    nickname=participant.nickname,
                    budget_cap_cents=participant.budget_cap_cents,
                    preferences=preferences,
                    assistance_profile=assistance,
                )
            ],
            days=[
                TripDayInput(
                    day_index=0,
                    date=shared.travel_date,
                    daily_budget_cents=shared.budget_cents,
                    start_location_text=shared.start_location_text,
                    end_location_text=shared.end_location_text,
                    time_window={
                        "start": f"{shared.start_time}:00",
                        "end": f"{shared.end_time}:00",
                    },
                )
            ],
        )
        persisted = self._workflow.confirm_collaboration_trip(trip)
        self._workflow.save_constraint_draft(
            revision.trip_id,
            assistance,
        )
        self._workflow.confirm_constraints(revision.trip_id)
        return persisted


__all__ = ["SingleCollaborationPlanningBridge"]
