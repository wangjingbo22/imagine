from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.collaboration import (
    ConversationSubmission,
    FixedQuestionFallback,
    QUESTION_IDS,
    fixed_question_fallback,
)


def _submission() -> ConversationSubmission:
    return ConversationSubmission(
        naturalLanguageRequest="original-description-unchanged",
        answers=[
            {
                "questionId": question_id,
                "answer": f"original-answer-{index}",
            }
            for index, question_id in enumerate(QUESTION_IDS, start=1)
        ],
    )


def test_fixed_question_fallback_preserves_all_six_answers_in_order() -> None:
    fallback = fixed_question_fallback(_submission())

    assert fallback.mode == "FIXED_QUESTIONS"
    assert [item.question_id for item in fallback.items] == list(QUESTION_IDS)
    assert [item.answer for item in fallback.items] == [
        f"original-answer-{index}" for index in range(1, 7)
    ]
    assert {item.code for item in fallback.items} == {"REVIEW_REQUIRED"}


def test_fixed_question_fallback_rejects_reordered_or_missing_items() -> None:
    valid = fixed_question_fallback(_submission())

    with pytest.raises(ValidationError):
        FixedQuestionFallback(items=list(reversed(valid.items)))
    with pytest.raises(ValidationError):
        FixedQuestionFallback(items=valid.items[:-1])


def test_fixed_question_fallback_has_no_authoritative_business_fields() -> None:
    payload = fixed_question_fallback(_submission()).model_dump(
        mode="json", by_alias=True
    )
    serialized = str(payload)
    for forbidden in (
        "tripId",
        "participantId",
        "ruleId",
        "relaxations",
        "confirmationStatus",
        "Constraint",
        "PlanVersion",
    ):
        assert forbidden not in serialized
