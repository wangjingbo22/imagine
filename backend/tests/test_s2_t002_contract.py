from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.domain.collaboration as collaboration
import app.domain.trip_draft as trip_draft


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trip_understanding"


def valid_group_proposal(*, member_keys: tuple[str, ...]) -> trip_draft.TripUnderstandingProposal:
    payload = json.loads((FIXTURE_DIR / "two_participants.json").read_text(encoding="utf-8"))
    payload["participants"] = payload["participants"][: len(member_keys)]
    for participant, member_key in zip(payload["participants"], member_keys, strict=True):
        participant["memberKey"] = member_key
    return trip_draft.TripUnderstandingProposal.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def valid_six_answers() -> list[dict[str, str]]:
    return [
        {"questionId": question_id, "answer": "已回答"}
        for question_id in collaboration.QUESTION_IDS
    ]


def test_revision_envelope_rejects_binding_drift_and_extra_fields() -> None:
    proposal = valid_group_proposal(member_keys=("member-1", "member-2"))
    revision_model = getattr(trip_draft, "TripDraftRevision", None)
    assert revision_model is not None
    with pytest.raises(ValidationError):
        revision_model(
            schemaVersion="1.0",
            draftId=uuid4(),
            revision=1,
            tripId=uuid4(),
            understanding=proposal,
            memberBindings={"member-1": uuid4()},
            sourceDigest="a" * 64,
            createdAt=datetime.now(UTC),
            canPlan=True,
        )


def test_organizer_conversation_reuses_fixed_question_contract() -> None:
    request_model = getattr(collaboration, "OrganizerConversationRequest", None)
    assert request_model is not None
    request = request_model(
        schemaVersion="1.0",
        referenceDate=date(2026, 8, 27),
        naturalLanguageRequest="两人去上海一日游",
        answers=valid_six_answers(),
    )
    assert [answer.question_id for answer in request.answers] == list(collaboration.QUESTION_IDS)
