from __future__ import annotations

from uuid import UUID

from app.application.collaboration_ports import TripDraftRevisionView
from app.application.workflow_service import WorkflowService
from app.core.errors import AppError
from app.domain.hard_conflicts import assistance_profile_from_care
from app.schemas.trip import (
    CityContext,
    CreateDayTrip,
    Participant,
    Preference,
    PreferenceType,
    TripDayInput,
    TripMode,
)


class CollaborationPlanningBridge:
    """Idempotently project one READY 1-3 member revision into planning."""

    def __init__(self, workflow_service: WorkflowService) -> None:
        self._workflow = workflow_service

    def materialize(
        self,
        revision: TripDraftRevisionView,
        city_context: CityContext,
    ) -> CreateDayTrip:
        proposal = revision.understanding
        shared = proposal.trip
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
            )
            if value is None
        ]
        participants_by_key = {
            participant.member_key: participant
            for participant in proposal.participants
        }
        binding_keys = set(revision.member_bindings)
        participant_keys = set(participants_by_key)
        if binding_keys != participant_keys:
            missing.append("participants.memberBindings")
        ordered_members = [
            participants_by_key[member_key]
            for member_key in sorted(binding_keys & participant_keys)
        ]
        for index, participant in enumerate(ordered_members):
            missing.extend(
                path
                for path, value in (
                    (f"participants[{index}].nickname", participant.nickname),
                    (
                        f"participants[{index}].budgetCapCents",
                        participant.budget_cap_cents,
                    ),
                    (f"participants[{index}].careDraft", participant.care_draft),
                )
                if value is None
            )
        if missing:
            raise AppError(
                "COLLABORATION_CANONICAL_TRIP_INCOMPLETE",
                "READY 协作版本缺少生成 canonical Trip 所需字段",
                409,
                False,
                errors=[{"path": path, "message": "required"} for path in missing],
            )

        projected_participants: list[Participant] = []
        for participant in ordered_members:
            care = participant.care_draft
            member_id = revision.member_bindings.get(participant.member_key)
            if care is None or not isinstance(member_id, UUID):
                raise AppError(
                    "COLLABORATION_MEMBER_BINDING_INVALID",
                    "READY 协作版本缺少成员 canonical participantId 或关怀资料",
                    409,
                    False,
                )
            try:
                assistance = assistance_profile_from_care(care)
            except ValueError as error:
                raise AppError(
                    "COLLABORATION_CANONICAL_TRIP_INCOMPLETE",
                    "READY 协作版本缺少已确认关怀类型",
                    409,
                    False,
                ) from error
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
            assert participant.nickname is not None
            assert participant.budget_cap_cents is not None
            projected_participants.append(
                Participant(
                    participant_id=member_id,
                    nickname=participant.nickname,
                    budget_cap_cents=participant.budget_cap_cents,
                    preferences=preferences,
                    assistance_profile=assistance,
                )
            )

        assert shared.travel_date is not None
        assert shared.start_time is not None and shared.end_time is not None
        assert shared.start_location_text is not None
        assert shared.end_location_text is not None
        assert shared.budget_cents is not None
        trip = CreateDayTrip(
            schema_version="1.0",
            trip_id=revision.trip_id,
            mode=(
                TripMode.SINGLE
                if len(projected_participants) == 1
                else TripMode.GROUP
            ),
            status="DRAFT",
            city_context=city_context,
            start_date=shared.travel_date,
            end_date=shared.travel_date,
            currency="CNY",
            total_budget_cents=shared.budget_cents,
            participants=projected_participants,
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
        # The legacy workflow table stores one AssistanceProfile.  Preserve
        # the established single-member memory item, but never collapse a
        # group's distinct long-term profiles into a fabricated profile.  The
        # group planner compiles and merges all participant profiles directly
        # from the immutable Trip snapshot.
        if len(projected_participants) == 1:
            assistance = projected_participants[0].assistance_profile
            assert assistance is not None
            self._workflow.save_constraint_draft(revision.trip_id, assistance)
            self._workflow.confirm_constraints(revision.trip_id)
        return persisted


# Compatibility for imports created while only the single-member hand-off was
# available.  Runtime composition uses the capability-oriented name below.
SingleCollaborationPlanningBridge = CollaborationPlanningBridge


__all__ = [
    "CollaborationPlanningBridge",
    "SingleCollaborationPlanningBridge",
]
