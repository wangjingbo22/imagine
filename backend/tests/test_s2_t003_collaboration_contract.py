import pytest
from pydantic import ValidationError

from app.domain.collaboration import (
    CollaborationIssue,
    InvitationRedeemRequest,
    ParticipantProgress,
)


def test_issue_always_has_rule_reason_and_allowed_relaxation_array() -> None:
    issue = CollaborationIssue.model_validate(
        {
            "itemId": "ci_0123456789abcdef",
            "fieldPath": "trip.startTime",
            "participantId": None,
            "relatedParticipantIds": [],
            "ruleId": "S2T003.TIME.WINDOW_ORDER",
            "code": "INVALID",
            "reason": "结束时间必须晚于开始时间",
            "candidates": [],
            "allowedRelaxations": [],
        }
    )
    assert issue.rule_id == "S2T003.TIME.WINDOW_ORDER"
    assert issue.relaxations == []
    assert issue.model_dump(mode="json", by_alias=True)["allowedRelaxations"] == []
    assert "relaxations" not in issue.model_dump(mode="json", by_alias=True)
    with pytest.raises(ValidationError):
        CollaborationIssue.model_validate(issue.model_dump(exclude={"rule_id"}))


def test_redeem_token_is_exactly_one_32_byte_base64url_secret() -> None:
    InvitationRedeemRequest(schemaVersion="1.0", token="A" * 43)
    with pytest.raises(ValidationError):
        InvitationRedeemRequest(schemaVersion="1.0", token="A" * 42)


def test_progress_separates_access_from_confirmation() -> None:
    fields = ParticipantProgress.model_json_schema(by_alias=True)["properties"]
    assert "accessStatus" in fields
    assert "confirmationStatus" in fields
    assert "parsed" not in fields
