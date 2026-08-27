from uuid import uuid4

import pytest

from app.application.collaboration_ports import (
    CanonicalRevisionPatch,
    TripDraftRevisionUnavailable,
    UnavailableTripDraftRevisionPort,
)
from app.domain.collaboration import (
    ConversationSubmission,
    RelaxationAction,
)


def _submission() -> ConversationSubmission:
    ids = ("trip", "party", "endpoints_budget", "preferences", "assistance", "confirm")
    return ConversationSubmission(
        naturalLanguageRequest="北京两人一日游",
        answers=[{"questionId": key, "answer": "已回答"} for key in ids],
    )


@pytest.mark.asyncio
async def test_unavailable_revision_port_fails_closed_for_every_command() -> None:
    port = UnavailableTripDraftRevisionPort()
    trip_id, participant_id = uuid4(), uuid4()
    with pytest.raises(TripDraftRevisionUnavailable):
        port.get_current(trip_id)
    with pytest.raises(TripDraftRevisionUnavailable):
        await port.submit_participant_conversation(
            trip_id=trip_id,
            participant_id=participant_id,
            base_revision=1,
            submission=_submission(),
            idempotency_key="0123456789abcdef",
        )
    with pytest.raises(TripDraftRevisionUnavailable):
        port.apply_relaxation(
            trip_id=trip_id,
            base_revision=1,
            patch=CanonicalRevisionPatch(
                action=RelaxationAction.REMOVE_AVOID_PLACE,
                participant_id=participant_id,
                field_path="participants[1].avoidPlaces[0]",
                value=None,
            ),
            idempotency_key="fedcba9876543210",
        )
