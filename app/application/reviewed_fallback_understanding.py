from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from app.core.errors import AppError
from app.domain.collaboration import ConversationSubmission, OrganizerConversationRequest
from app.domain.trip_draft import TripUnderstandingProposal


_TRIP_RE = re.compile(
    r"目的城市：(?P<city>[^；]+)；出行日期：(?P<date>\d{4}-\d{2}-\d{2})；"
    r"(?:可用时间|出行时间)：(?P<start>\d{2}:\d{2})到(?P<end>\d{2}:\d{2})"
)
_ROUTE_RE = re.compile(
    r"从(?P<start>.+?)出发；结束地：(?P<end>.+?)；"
    r"(?:共享预算|单人预算|本次行程总预算|同行行程总预算)：(?P<budget>\d+(?:\.\d{1,2})?)"
)
_NICKNAME_RE = re.compile(r"组织者昵称：(?P<nickname>[^；]+)")
_PERSONAL_BUDGET_RE = re.compile(r"组织者个人预算上限：(?P<budget>\d+(?:\.\d{1,2})?)元")
_CARE_MODE_RE = re.compile(
    r"关怀模式：(?P<mode>ORDINARY|PARENT_CHILD|LOW_STAMINA|MOBILITY_ASSISTANCE_BETA)"
)


def _cents(value: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise AppError("FIXED_QUESTION_REVIEW_INVALID", "预算格式无法识别", 422, False) from error
    if amount < 0:
        raise AppError("FIXED_QUESTION_REVIEW_INVALID", "预算不能为负数", 422, False)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _preference_parts(answer: str) -> tuple[list[str], list[str], list[str]]:
    interests: list[str] = []
    must_visit: list[str] = []
    avoid_places: list[str] = []
    patterns = (
        (interests, r"(?:兴趣|喜欢)[:：]?\s*(.+?)(?=[；。]|必去|不去|避开|$)"),
        (must_visit, r"必去[:：]?\s*(.+?)(?=[；。]|不去|避开|$)"),
        (avoid_places, r"(?:不去|避开)[:：]?\s*(.+?)(?=[；。]|$)"),
    )
    for target, pattern in patterns:
        match = re.search(pattern, answer)
        if not match:
            continue
        for item in re.split(r"[、,，/]|\s+和\s*|和|及", match.group(1)):
            normalized = item.strip(" ，,。；;：:")
            if normalized and normalized not in target:
                target.append(normalized[:120])
    if not interests:
        fallback = answer.strip()[:120]
        if fallback:
            interests.append(fallback)
    return interests[:20], must_visit[:20], avoid_places[:20]


def reviewed_fallback_proposal(payload: OrganizerConversationRequest) -> TripUnderstandingProposal:
    answers = [item.answer.strip() for item in payload.answers]
    trip_match = _TRIP_RE.search(answers[0])
    route_match = _ROUTE_RE.search(answers[2])
    nickname_match = _NICKNAME_RE.search(answers[1])
    personal_budget_match = _PERSONAL_BUDGET_RE.search(answers[4])
    care_mode_match = _CARE_MODE_RE.search(answers[4])
    if not all((trip_match, route_match, nickname_match, personal_budget_match, care_mode_match)):
        raise AppError(
            "FIXED_QUESTION_REVIEW_INVALID",
            "已核对答案缺少城市、日期、时间、起终点、预算、组织者昵称或关怀模式，请返回对应问题修改。",
            422,
            False,
        )

    assert trip_match and route_match and nickname_match and personal_budget_match and care_mode_match
    try:
        travel_date = date.fromisoformat(trip_match.group("date"))
    except ValueError as error:
        raise AppError("FIXED_QUESTION_REVIEW_INVALID", "出行日期无效", 422, False) from error
    interests, must_visit, avoid_places = _preference_parts(answers[3])
    member_count = payload.participant_count
    mode = care_mode_match.group("mode")

    participants: list[dict[str, object]] = [
        {
            "memberKey": "member-1",
            "nickname": nickname_match.group("nickname").strip()[:40],
            "budgetCapCents": _cents(personal_budget_match.group("budget")),
            "interests": interests,
            "mustVisit": must_visit,
            "avoidPlaces": avoid_places,
            "careDraft": {
                "assistanceTypeHint": mode,
                "childAge": None,
                "walkLimits": {"maxContinuousMeters": None, "maxDailyMeters": None},
                "maxTransfers": None,
                "restIntervalMinutes": None,
                "napWindow": None,
                "avoidStairs": None,
            },
        }
    ]
    for index in range(1, member_count):
        participants.append(
            {
                "memberKey": f"member-{index + 1}",
                "nickname": None,
                "budgetCapCents": None,
                "interests": [],
                "mustVisit": [],
                "avoidPlaces": [],
                "careDraft": None,
            }
        )

    evidence: list[dict[str, object]] = [
        {"fieldPath": "trip.cityName", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": trip_match.group("city")},
        {"fieldPath": "trip.travelDate", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": trip_match.group("date")},
        {"fieldPath": "trip.startTime", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": trip_match.group("start")},
        {"fieldPath": "trip.endTime", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": trip_match.group("end")},
        {"fieldPath": "trip.startLocationText", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": route_match.group("start")},
        {"fieldPath": "trip.endLocationText", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": route_match.group("end")},
        {"fieldPath": "trip.budgetCents", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": route_match.group("budget")},
        {"fieldPath": "participants", "memberKey": None, "sourceType": "USER_TEXT", "sourceText": str(member_count)},
        {"fieldPath": "participants[0].nickname", "memberKey": "member-1", "sourceType": "USER_TEXT", "sourceText": nickname_match.group("nickname").strip()},
        {"fieldPath": "participants[0].budgetCapCents", "memberKey": "member-1", "sourceType": "USER_TEXT", "sourceText": personal_budget_match.group("budget")},
        {"fieldPath": "participants[0].careDraft.assistanceTypeHint", "memberKey": "member-1", "sourceType": "USER_TEXT", "sourceText": mode},
    ]
    for field_name, values in (("interests", interests), ("mustVisit", must_visit), ("avoidPlaces", avoid_places)):
        for index, value in enumerate(values):
            evidence.append(
                {
                    "fieldPath": f"participants[0].{field_name}[{index}]",
                    "memberKey": "member-1",
                    "sourceType": "USER_TEXT",
                    "sourceText": value,
                }
            )

    missing_fields: list[dict[str, object]] = []
    confirmation_questions: list[dict[str, object]] = []
    for index in range(1, member_count):
        member_key = f"member-{index + 1}"
        field_path = f"participants[{index}].careDraft.assistanceTypeHint"
        missing_fields.append(
            {"fieldPath": field_path, "memberKey": member_key, "code": "MISSING", "questionKey": "MEMBER_CARE_PRESET"}
        )
        confirmation_questions.append(
            {
                "fieldPath": field_path,
                "memberKey": member_key,
                "questionKey": "MEMBER_CARE_PRESET",
                "prompt": "请由该成员确认自己的关怀模式。",
                "choices": ["ORDINARY", "PARENT_CHILD", "LOW_STAMINA", "MOBILITY_ASSISTANCE_BETA"],
            }
        )

    return TripUnderstandingProposal.model_validate(
        {
            "schemaVersion": "1.0",
            "trip": {
                "cityName": trip_match.group("city").strip(),
                "travelDate": travel_date,
                "startTime": trip_match.group("start"),
                "endTime": trip_match.group("end"),
                "startLocationText": route_match.group("start").strip(),
                "endLocationText": route_match.group("end").strip(),
                "budgetCents": _cents(route_match.group("budget")),
            },
            "participants": participants,
            "fieldEvidence": evidence,
            "missingFields": missing_fields,
            "ambiguities": [],
            "confirmationQuestions": confirmation_questions,
        }
    )


def reviewed_member_fallback_proposal(
    current: TripUnderstandingProposal,
    *,
    member_key: str,
    submission: ConversationSubmission,
) -> TripUnderstandingProposal:
    participant_index = next(
        (index for index, item in enumerate(current.participants) if item.member_key == member_key),
        None,
    )
    if participant_index is None:
        raise AppError("PARTICIPANT_NOT_BOUND", "成员绑定不存在", 404, False)

    answers = [item.answer.strip() for item in submission.answers]
    interests, must_visit, avoid_places = _preference_parts(answers[3])
    budget_match = re.search(r"个人预算上限：(?P<budget>\d+(?:\.\d{1,2})?|未设置)", answers[4])
    if not budget_match:
        raise AppError("FIXED_QUESTION_REVIEW_INVALID", "成员预算答案格式无法识别，请返回第 5 问修改。", 422, False)
    budget_text = budget_match.group("budget")
    budget_cents = None if budget_text == "未设置" else _cents(budget_text)

    mode_match = re.search(
        r"关怀类型：(?P<mode>ORDINARY|PARENT_CHILD|LOW_STAMINA|MOBILITY_ASSISTANCE_BETA)",
        answers[4],
    )
    if mode_match:
        mode = mode_match.group("mode")
        care_source = mode
    elif "没有额外关怀限制" in answers[4]:
        mode = "ORDINARY"
        care_source = "没有额外关怀限制"
    else:
        raise AppError("FIXED_QUESTION_REVIEW_INVALID", "成员关怀模式无法识别，请返回第 5 问修改。", 422, False)

    def optional_int(pattern: str) -> int | None:
        match = re.search(pattern, answers[4])
        return int(match.group(1)) if match else None

    care = {
        "assistanceTypeHint": mode,
        "childAge": None,
        "walkLimits": {
            "maxContinuousMeters": optional_int(r"连续步行不超过(\d+)米"),
            "maxDailyMeters": None,
        },
        "maxTransfers": optional_int(r"最多换乘(\d+)次"),
        "restIntervalMinutes": optional_int(r"每(\d+)分钟休息"),
        "napWindow": None,
        "avoidStairs": True if "避开楼梯" in answers[4] else None,
    }

    # Keep date/time objects intact because the canonical proposal validates in
    # strict mode; JSON-mode dumping would turn travelDate into a plain string.
    candidate = current.model_dump(mode="python", by_alias=True)
    participant = candidate["participants"][participant_index]
    participant.update(
        {
            "budgetCapCents": budget_cents,
            "interests": interests,
            "mustVisit": must_visit,
            "avoidPlaces": avoid_places,
            "careDraft": care,
        }
    )
    mutable_prefixes = (
        "budgetCapCents",
        "interests[",
        "mustVisit[",
        "avoidPlaces[",
        "careDraft.",
    )
    participant_prefix = f"participants[{participant_index}]."
    candidate["fieldEvidence"] = [
        item for item in candidate["fieldEvidence"]
        if not (
            item.get("memberKey") == member_key
            and item.get("fieldPath", "").startswith(participant_prefix)
            and item["fieldPath"][len(participant_prefix):].startswith(mutable_prefixes)
        )
    ]
    evidence = candidate["fieldEvidence"]
    if budget_cents is not None:
        evidence.append(
            {"fieldPath": f"{participant_prefix}budgetCapCents", "memberKey": member_key, "sourceType": "USER_TEXT", "sourceText": budget_text}
        )
    for field_name, values in (("interests", interests), ("mustVisit", must_visit), ("avoidPlaces", avoid_places)):
        for index, value in enumerate(values):
            evidence.append(
                {"fieldPath": f"{participant_prefix}{field_name}[{index}]", "memberKey": member_key, "sourceType": "USER_TEXT", "sourceText": value}
            )
    evidence.append(
        {"fieldPath": f"{participant_prefix}careDraft.assistanceTypeHint", "memberKey": member_key, "sourceType": "USER_TEXT", "sourceText": care_source}
    )
    for path, pattern in (
        ("careDraft.walkLimits.maxContinuousMeters", r"连续步行不超过(\d+)米"),
        ("careDraft.maxTransfers", r"最多换乘(\d+)次"),
        ("careDraft.restIntervalMinutes", r"每(\d+)分钟休息"),
    ):
        match = re.search(pattern, answers[4])
        if match:
            evidence.append(
                {"fieldPath": f"{participant_prefix}{path}", "memberKey": member_key, "sourceType": "USER_TEXT", "sourceText": match.group(1)}
            )
    if care["avoidStairs"]:
        evidence.append(
            {"fieldPath": f"{participant_prefix}careDraft.avoidStairs", "memberKey": member_key, "sourceType": "USER_TEXT", "sourceText": "避开楼梯"}
        )

    candidate["missingFields"] = [item for item in candidate["missingFields"] if item.get("memberKey") != member_key]
    candidate["ambiguities"] = [item for item in candidate["ambiguities"] if item.get("memberKey") != member_key]
    candidate["confirmationQuestions"] = [item for item in candidate["confirmationQuestions"] if item.get("memberKey") != member_key]
    return TripUnderstandingProposal.model_validate(candidate)


__all__ = ["reviewed_fallback_proposal", "reviewed_member_fallback_proposal"]
