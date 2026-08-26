from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.domain.trip_draft as trip_draft


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trip_understanding"


def _proposal_payload() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "trip": {
            "cityName": "北京",
            "travelDate": "2026-09-05",
            "startTime": "09:00",
            "endTime": "18:00",
            "startLocationText": "北京站",
            "endLocationText": "故宫",
            "budgetCents": 50000,
        },
        "participants": [
            {
                "memberKey": "member-1",
                "nickname": "我",
                "budgetCapCents": 50000,
                "interests": ["博物馆"],
                "mustVisit": ["故宫"],
                "avoidPlaces": [],
                "careDraft": None,
            }
        ],
        "fieldEvidence": [
            {
                "fieldPath": "trip.cityName",
                "memberKey": None,
                "sourceType": "USER_TEXT",
                "sourceText": "北京",
            },
            {
                "fieldPath": "trip.travelDate",
                "memberKey": None,
                "sourceType": "USER_TEXT",
                "sourceText": "2026-09-05",
            },
            {
                "fieldPath": "trip.startTime",
                "memberKey": None,
                "sourceType": "USER_TEXT",
                "sourceText": "09:00",
            },
            {
                "fieldPath": "trip.endTime",
                "memberKey": None,
                "sourceType": "USER_TEXT",
                "sourceText": "18:00",
            },
            {
                "fieldPath": "trip.startLocationText",
                "memberKey": None,
                "sourceType": "USER_TEXT",
                "sourceText": "北京站",
            },
            {
                "fieldPath": "trip.endLocationText",
                "memberKey": None,
                "sourceType": "USER_TEXT",
                "sourceText": "故宫",
            },
            {
                "fieldPath": "trip.budgetCents",
                "memberKey": None,
                "sourceType": "USER_TEXT",
                "sourceText": "50000",
            },
            {
                "fieldPath": "participants[0].nickname",
                "memberKey": "member-1",
                "sourceType": "USER_TEXT",
                "sourceText": "我",
            },
            {
                "fieldPath": "participants[0].budgetCapCents",
                "memberKey": "member-1",
                "sourceType": "USER_TEXT",
                "sourceText": "50000",
            },
            {
                "fieldPath": "participants[0].interests[0]",
                "memberKey": "member-1",
                "sourceType": "USER_TEXT",
                "sourceText": "博物馆",
            },
            {
                "fieldPath": "participants[0].mustVisit[0]",
                "memberKey": "member-1",
                "sourceType": "USER_TEXT",
                "sourceText": "故宫",
            },
        ],
        "missingFields": [],
        "ambiguities": [],
        "confirmationQuestions": [],
    }


def _request_payload() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-26",
        "rawConversation": "我一个人去北京，2026-09-05 09:00 到 18:00，从北京站到故宫，预算 50000，喜欢博物馆，必须去故宫。",
        "explicitFields": {
            "cityName": "北京",
            "travelDate": "2026-09-05",
            "startTime": "09:00",
            "endTime": "18:00",
            "startLocationText": "北京站",
            "endLocationText": "故宫",
            "budgetCents": 50000,
            "participants": [
                {
                    "memberKey": "member-1",
                    "nickname": "我",
                    "budgetCapCents": 50000,
                    "interests": ["博物馆"],
                    "mustVisit": ["故宫"],
                    "avoidPlaces": [],
                    "careText": None,
                }
            ],
        },
    }


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _request_for_proposal(payload: dict[str, object]) -> dict[str, object]:
    trip = payload["trip"]
    participants = payload["participants"]
    evidence = payload["fieldEvidence"]
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-26",
        "rawConversation": " ".join(item["sourceText"] for item in evidence),
        "explicitFields": {
            "cityName": trip["cityName"],
            "travelDate": trip["travelDate"],
            "startTime": trip["startTime"],
            "endTime": trip["endTime"],
            "startLocationText": trip["startLocationText"],
            "endLocationText": trip["endLocationText"],
            "budgetCents": trip["budgetCents"],
            "participants": [
                {
                    "memberKey": participant["memberKey"],
                    "nickname": participant["nickname"],
                    "budgetCapCents": participant["budgetCapCents"],
                    "interests": participant["interests"],
                    "mustVisit": participant["mustVisit"],
                    "avoidPlaces": participant["avoidPlaces"],
                    "careText": None,
                }
                for participant in participants
            ],
        },
    }


def _models():
    return (
        trip_draft.TripUnderstandingRequest,
        trip_draft.TripUnderstandingProposal,
        trip_draft.validate_trip_understanding,
    )


def test_trip_understanding_json_is_strict_and_validates_source_context():
    request_model = getattr(trip_draft, "TripUnderstandingRequest", None)
    proposal_model = getattr(trip_draft, "TripUnderstandingProposal", None)
    validator = getattr(trip_draft, "validate_trip_understanding", None)
    assert request_model is not None
    assert proposal_model is not None
    assert validator is not None

    request = request_model.model_validate_json(
        json.dumps(_request_payload(), ensure_ascii=False), strict=True
    )
    proposal = proposal_model.model_validate_json(
        json.dumps(_proposal_payload(), ensure_ascii=False), strict=True
    )

    validated = validator(request, proposal)

    assert len(validated.participants) == 1
    assert validated.participants[0].member_key == "member-1"


def test_trip_understanding_rejects_user_text_not_present_in_request():
    request_model = getattr(trip_draft, "TripUnderstandingRequest", None)
    proposal_model = getattr(trip_draft, "TripUnderstandingProposal", None)
    validator = getattr(trip_draft, "validate_trip_understanding", None)
    assert request_model is not None
    assert proposal_model is not None
    assert validator is not None

    payload = _proposal_payload()
    payload["fieldEvidence"][0]["sourceText"] = "上海"
    request = request_model.model_validate_json(
        json.dumps(_request_payload(), ensure_ascii=False), strict=True
    )
    proposal = proposal_model.model_validate_json(
        json.dumps(payload, ensure_ascii=False), strict=True
    )

    with pytest.raises(ValueError):
        validator(request, proposal)


@pytest.mark.parametrize("fixture_name", ["one_participant", "two_participants", "three_participants"])
def test_understanding_fixtures_validate_and_bind_to_request_context(fixture_name: str):
    request_model, proposal_model, validator = _models()
    payload = _load_fixture(fixture_name)
    request = request_model.model_validate_json(
        json.dumps(_request_for_proposal(payload), ensure_ascii=False), strict=True
    )
    proposal = proposal_model.model_validate_json(
        json.dumps(payload, ensure_ascii=False), strict=True
    )

    result = validator(request, proposal)

    assert result == proposal
    assert len(result.participants) in {1, 2, 3}
    assert [participant.member_key for participant in result.participants] == [
        f"member-{index}" for index in range(1, len(result.participants) + 1)
    ]


def test_request_requires_nullable_fields_and_rejects_nested_extra_fields():
    request_model, _, _ = _models()
    payload = _request_payload()
    del payload["explicitFields"]["cityName"]

    with pytest.raises(ValidationError):
        request_model.model_validate_json(json.dumps(payload), strict=True)

    payload = _request_payload()
    payload["explicitFields"]["participants"][0]["privateFlag"] = True
    with pytest.raises(ValidationError):
        request_model.model_validate_json(json.dumps(payload), strict=True)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload["trip"].update({"tripId": "not-authoritative"}),
        lambda payload: payload["participants"][0].update({"participantId": "not-authoritative"}),
        lambda payload: payload["fieldEvidence"][0].update({"provider": "AMAP"}),
    ],
)
def test_proposal_rejects_extra_fields_at_every_contract_layer(mutation):
    _, proposal_model, _ = _models()
    payload = _proposal_payload()
    mutation(payload)

    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("budgetCents", "50000"),
        ("budgetCents", 50000.0),
        ("startTime", "24:00"),
        ("endTime", "18:00:00"),
    ],
)
def test_proposal_rejects_strict_type_and_time_format_mutations(field: str, value):
    _, proposal_model, _ = _models()
    payload = _proposal_payload()
    if field in {"budgetCents", "startTime", "endTime"}:
        payload["trip"][field] = value

    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


def test_proposal_rejects_nonsequential_member_keys_and_wrong_evidence_member():
    _, proposal_model, _ = _models()
    payload = _load_fixture("two_participants")
    payload["participants"][1]["memberKey"] = "member-3"

    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)

    payload = _load_fixture("one_participant")
    payload["fieldEvidence"][0]["memberKey"] = "member-1"
    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


def test_proposal_requires_evidence_for_every_non_null_modeled_value():
    _, proposal_model, _ = _models()
    payload = _proposal_payload()
    payload["fieldEvidence"] = payload["fieldEvidence"][1:]

    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


def test_missing_and_ambiguity_question_loops_are_closed():
    _, proposal_model, _ = _models()
    payload = _proposal_payload()
    missing = {
        "fieldPath": "participants[0].careDraft.assistanceTypeHint",
        "memberKey": "member-1",
        "code": "MISSING",
        "questionKey": "MEMBER_CARE_PRESET",
    }
    payload["missingFields"] = [missing]
    payload["confirmationQuestions"] = [
        {
            "fieldPath": missing["fieldPath"],
            "memberKey": missing["memberKey"],
            "questionKey": missing["questionKey"],
            "prompt": "Does the member need care assistance?",
            "choices": [],
        }
    ]
    proposal_model.model_validate_json(json.dumps(payload), strict=True)

    payload["confirmationQuestions"] = []
    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


def test_ambiguity_choices_must_equal_candidates_and_missing_cannot_overlap():
    _, proposal_model, _ = _models()
    payload = _proposal_payload()
    ambiguity = {
        "fieldPath": "trip.cityName",
        "memberKey": None,
        "code": "AMBIGUOUS",
        "reason": "Two cities were mentioned",
        "candidates": ["Beijing", "Shanghai"],
        "questionKey": "CITY_NAME",
    }
    payload["ambiguities"] = [ambiguity]
    payload["confirmationQuestions"] = [
        {
            "fieldPath": "trip.cityName",
            "memberKey": None,
            "questionKey": "CITY_NAME",
            "prompt": "Which city should we use?",
            "choices": ["Beijing"],
        }
    ]
    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)

    payload["confirmationQuestions"][0]["choices"] = ["Beijing", "Shanghai"]
    payload["missingFields"] = [
        {
            "fieldPath": "trip.cityName",
            "memberKey": None,
            "code": "MISSING",
            "questionKey": "CITY_NAME",
        }
    ]
    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


def test_care_draft_must_contain_a_signal_and_uses_strict_nullable_fields():
    _, proposal_model, _ = _models()
    payload = _proposal_payload()
    payload["participants"][0]["careDraft"] = {
        "assistanceTypeHint": None,
        "childAge": None,
        "walkLimits": {"maxContinuousMeters": None, "maxDailyMeters": None},
        "maxTransfers": None,
        "restIntervalMinutes": None,
        "napWindow": None,
        "avoidStairs": None,
    }
    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


def test_explicit_field_evidence_uses_request_context_and_display_value():
    request_model, proposal_model, validator = _models()
    payload = _proposal_payload()
    payload["fieldEvidence"][0]["sourceType"] = "EXPLICIT_FIELD"
    request = request_model.model_validate_json(
        json.dumps(_request_payload(), ensure_ascii=False), strict=True
    )
    proposal = proposal_model.model_validate_json(
        json.dumps(payload, ensure_ascii=False), strict=True
    )
    assert validator(request, proposal) == proposal

    payload["fieldEvidence"][0]["sourceText"] = "Shanghai"
    proposal = proposal_model.model_validate_json(
        json.dumps(payload, ensure_ascii=False), strict=True
    )
    with pytest.raises(ValueError):
        validator(request, proposal)


def test_explicit_field_evidence_must_match_the_proposal_value():
    request_model, proposal_model, validator = _models()
    payload = _proposal_payload()
    payload["trip"]["cityName"] = "Shanghai"
    payload["fieldEvidence"][0]["sourceType"] = "EXPLICIT_FIELD"
    request = request_model.model_validate_json(
        json.dumps(_request_payload(), ensure_ascii=False), strict=True
    )
    proposal = proposal_model.model_validate_json(
        json.dumps(payload, ensure_ascii=False), strict=True
    )

    with pytest.raises(ValueError):
        validator(request, proposal)


def test_structured_care_text_can_bind_care_evidence_without_raw_conversation():
    request_model, proposal_model, validator = _models()
    payload = _proposal_payload()
    payload["trip"]["cityName"] = None
    payload["trip"]["travelDate"] = None
    payload["trip"]["startTime"] = None
    payload["trip"]["endTime"] = None
    payload["trip"]["startLocationText"] = None
    payload["trip"]["endLocationText"] = None
    payload["trip"]["budgetCents"] = None
    payload["participants"][0]["nickname"] = None
    payload["participants"][0]["budgetCapCents"] = None
    payload["participants"][0]["interests"] = []
    payload["participants"][0]["mustVisit"] = []
    payload["participants"][0]["careDraft"] = {
        "assistanceTypeHint": "LOW_STAMINA",
        "childAge": None,
        "walkLimits": {"maxContinuousMeters": None, "maxDailyMeters": None},
        "maxTransfers": None,
        "restIntervalMinutes": None,
        "napWindow": None,
        "avoidStairs": None,
    }
    payload["fieldEvidence"] = [
        {
            "fieldPath": "participants[0].careDraft.assistanceTypeHint",
            "memberKey": "member-1",
            "sourceType": "EXPLICIT_FIELD",
            "sourceText": "老人少走路",
        }
    ]
    request_payload = _request_payload()
    request_payload["rawConversation"] = ""
    request_payload["explicitFields"]["cityName"] = None
    request_payload["explicitFields"]["travelDate"] = None
    request_payload["explicitFields"]["startTime"] = None
    request_payload["explicitFields"]["endTime"] = None
    request_payload["explicitFields"]["startLocationText"] = None
    request_payload["explicitFields"]["endLocationText"] = None
    request_payload["explicitFields"]["budgetCents"] = None
    request_payload["explicitFields"]["participants"][0]["nickname"] = None
    request_payload["explicitFields"]["participants"][0]["budgetCapCents"] = None
    request_payload["explicitFields"]["participants"][0]["interests"] = []
    request_payload["explicitFields"]["participants"][0]["mustVisit"] = []
    request_payload["explicitFields"]["participants"][0]["careText"] = "老人少走路"
    request = request_model.model_validate_json(
        json.dumps(request_payload, ensure_ascii=False), strict=True
    )
    proposal = proposal_model.model_validate_json(
        json.dumps(payload, ensure_ascii=False), strict=True
    )

    assert validator(request, proposal) == proposal


def test_preference_lists_allow_at_most_twenty_items():
    request_model, proposal_model, _ = _models()
    request_payload = _request_payload()
    request_payload["explicitFields"]["participants"][0]["interests"] = [
        f"interest-{index}" for index in range(20)
    ]
    request_model.model_validate_json(
        json.dumps(request_payload, ensure_ascii=False), strict=True
    )
    request_payload["explicitFields"]["participants"][0]["interests"].append(
        "interest-20"
    )
    with pytest.raises(ValidationError):
        request_model.model_validate_json(
            json.dumps(request_payload, ensure_ascii=False), strict=True
        )

    payload = _proposal_payload()
    payload["participants"][0]["interests"] = [
        f"interest-{index}" for index in range(20)
    ]
    payload["fieldEvidence"] = [
        evidence
        for evidence in payload["fieldEvidence"]
        if not evidence["fieldPath"].startswith("participants[0].interests[")
    ]
    payload["fieldEvidence"].extend(
        {
            "fieldPath": f"participants[0].interests[{index}]",
            "memberKey": "member-1",
            "sourceType": "USER_TEXT",
            "sourceText": f"interest-{index}",
        }
        for index in range(20)
    )
    proposal_model.model_validate_json(
        json.dumps(payload, ensure_ascii=False), strict=True
    )
    payload["participants"][0]["interests"].append("interest-20")
    payload["fieldEvidence"].append(
        {
            "fieldPath": "participants[0].interests[20]",
            "memberKey": "member-1",
            "sourceType": "USER_TEXT",
            "sourceText": "interest-20",
        }
    )
    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(
            json.dumps(payload, ensure_ascii=False), strict=True
        )


def test_duplicate_preference_values_are_rejected_after_nfkc_normalization():
    _, proposal_model, _ = _models()
    payload = _proposal_payload()
    payload["participants"][0]["interests"] = ["museum", "  Ｍｕｓｅｕｍ  "]
    payload["fieldEvidence"].append(
        {
            "fieldPath": "participants[0].interests[1]",
            "memberKey": "member-1",
            "sourceType": "USER_TEXT",
            "sourceText": "museum",
        }
    )

    with pytest.raises(ValidationError):
        proposal_model.model_validate_json(json.dumps(payload), strict=True)


def test_recursive_schema_is_extra_forbidden_and_nullable_fields_are_required():
    _, proposal_model, _ = _models()
    schema = proposal_model.model_json_schema(by_alias=True, mode="validation")
    objects = [schema]
    objects.extend(schema.get("$defs", {}).values())
    for object_schema in objects:
        if object_schema.get("type") == "object":
            assert object_schema.get("additionalProperties") is False
            assert set(object_schema.get("properties", {})).issuperset(
                set(object_schema.get("required", []))
            )
    assert "careDraft" in schema["$defs"]["ParticipantUnderstanding"]["required"]
    assert "avoidStairs" in schema["$defs"]["CareDraft"]["required"]


def test_understanding_schema_matches_snapshot_and_published_schema():
    _, proposal_model, _ = _models()
    expected = json.dumps(
        proposal_model.model_json_schema(by_alias=True, mode="validation"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    snapshot_path = FIXTURE_DIR.parent.parent / "snapshots" / "trip_understanding.schema.json"
    published_path = FIXTURE_DIR.parent.parent.parent / "schemas" / "trip-understanding.schema.json"

    assert snapshot_path.read_text(encoding="utf-8") == expected
    assert json.loads(published_path.read_text(encoding="utf-8")) == json.loads(expected)
