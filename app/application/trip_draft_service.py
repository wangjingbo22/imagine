from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Protocol
from unicodedata import normalize
from uuid import uuid4

from app.domain.trip_draft import (
    ConfirmationItem,
    ParsedTripFields,
    TripDraftParseRequest,
    TripDraftParseResult,
)
from app.schemas.trip import (
    AssistanceProfile,
    AssistanceType,
    CreateSingleDayTrip,
    Participant,
    Preference,
    PreferenceType,
    TripDayInput,
    WalkLimits,
    validate_single_day_policy,
)
from app.schemas.validation_error import TripSchemaError, ValidationIssue


_CITY_NAMES = (
    "北京", "上海", "天津", "重庆", "广州", "深圳", "成都", "杭州",
    "西安", "南京", "武汉", "长沙", "苏州", "青岛", "厦门", "昆明",
    "大连", "沈阳", "哈尔滨", "郑州", "济南", "福州", "南昌",
)
_INTEREST_NAMES = (
    "历史文化", "特色餐饮", "城市漫步", "摄影", "自然风景", "博物馆",
    "历史", "美食", "亲子", "公园", "建筑", "购物",
)
_AMBIGUOUS_DATE_WORDS = ("周末", "下周", "过几天", "改天", "某天")


class CityResolver(Protocol):
    async def resolve_city(self, city_name: str): ...


class TripDraftParserService:
    def __init__(self, city_resolver: CityResolver) -> None:
        self._city_resolver = city_resolver

    async def parse(self, request: TripDraftParseRequest) -> TripDraftParseResult:
        text = normalize("NFKC", request.natural_language_request).strip()
        reference = request.reference_date or date.today()
        items: list[ConfirmationItem] = []

        city_name = _non_blank(request.city_name) or _extract_city(text)
        if city_name is None:
            items.append(_missing("city", "cityName", "请确认目标城市"))

        travel_date = _explicit_date(request.travel_date)
        if request.travel_date and travel_date is None:
            items.append(_invalid("date", "travelDate", "出行日期格式必须为 YYYY-MM-DD"))
        if travel_date is None and not request.travel_date:
            travel_date, date_issue = _extract_date(text, reference)
            if date_issue is not None:
                items.append(date_issue)
        if travel_date is None and not any(item.path == "travelDate" for item in items):
            items.append(_missing("date", "travelDate", "请确认具体出行日期"))

        explicit_start = _explicit_time(request.start_time)
        explicit_end = _explicit_time(request.end_time)
        if request.start_time and explicit_start is None:
            items.append(_invalid("start-time", "startTime", "开始时间格式必须为 HH:mm"))
        if request.end_time and explicit_end is None:
            items.append(_invalid("end-time", "endTime", "结束时间格式必须为 HH:mm"))
        extracted_start, extracted_end, time_issues = _extract_time_window(text)
        start_time = explicit_start or extracted_start
        end_time = explicit_end or extracted_end
        if explicit_start is not None:
            time_issues = [item for item in time_issues if item.path != "startTime"]
        if explicit_end is not None:
            time_issues = [item for item in time_issues if item.path != "endTime"]
        items.extend(time_issues)
        if start_time is None and not any(item.path == "startTime" for item in items):
            items.append(_missing("start-time", "startTime", "请确认当天开始时间"))
        if end_time is None and not any(item.path == "endTime" for item in items):
            items.append(_missing("end-time", "endTime", "请确认当天结束时间"))
        if start_time and end_time and start_time >= end_time:
            items.append(
                _invalid("time-window", "endTime", "结束时间必须晚于开始时间")
            )

        budget_cents = request.budget_cents
        if budget_cents is None:
            budget_cents = _extract_budget_cents(text)
        if budget_cents is None:
            items.append(_missing("budget", "budgetCents", "请确认本次行程总预算"))

        interests = _unique(request.interests or _extract_interests(text))
        if not interests:
            items.append(_missing("interests", "interests", "请至少确认一项兴趣"))

        must_visit = _unique(request.must_visit or _extract_places(text, "must"))
        avoid_places = _unique(request.avoid_places or _extract_places(text, "avoid"))
        conflicts = sorted({_key(item) for item in must_visit} & {_key(item) for item in avoid_places})
        if conflicts:
            items.append(
                ConfirmationItem(
                    item_id="place-conflict",
                    path="placeRestrictions",
                    code="conflict",
                    message="同一地点不能同时设为必去和避开",
                    candidates=conflicts,
                )
            )

        parsed = ParsedTripFields(
            city_name=city_name,
            travel_date=travel_date.isoformat() if travel_date else None,
            start_time=start_time,
            end_time=end_time,
            budget_cents=budget_cents,
            interests=interests,
            must_visit=must_visit,
            avoid_places=avoid_places,
        )
        trip_uuid = uuid4()
        trip_id = str(trip_uuid)
        if items:
            return TripDraftParseResult(
                trip_id=trip_id,
                parsed=parsed,
                confirmation_items=_stable_items(items),
                can_plan=False,
                trip=None,
            )

        assert city_name and travel_date and start_time and end_time
        assert budget_cents is not None
        city = (await self._city_resolver.resolve_city(city_name)).cityContext
        participant_id = uuid4()
        preferences = [
            Preference(type=PreferenceType.INTEREST, value=value, weight=4, is_hard=False)
            for value in interests
        ]
        preferences.extend(
            Preference(type=PreferenceType.MUST_VISIT, value=value, weight=5, is_hard=True)
            for value in must_visit
        )
        preferences.extend(
            Preference(type=PreferenceType.AVOID_PLACE, value=value, weight=5, is_hard=True)
            for value in avoid_places
        )
        assistance = request.assistance_profile
        assistance_type = {
            "standard": AssistanceType.ORDINARY,
            "family": AssistanceType.PARENT_CHILD,
            "low-mobility": AssistanceType.LOW_STAMINA,
            "assisted": AssistanceType.MOBILITY_ASSISTANCE_BETA,
        }[request.assistance_mode]
        trip = CreateSingleDayTrip(
            schema_version="1.0",
            trip_id=trip_uuid,
            mode="SINGLE",
            status="DRAFT",
            city_context=city,
            start_date=travel_date,
            end_date=travel_date,
            currency="CNY",
            total_budget_cents=budget_cents,
            participants=[
                Participant(
                    participant_id=participant_id,
                    nickname="单人旅客",
                    budget_cap_cents=budget_cents,
                    preferences=preferences,
                    assistance_profile=AssistanceProfile(
                        type=assistance_type,
                        child_age=None,
                        walk_limits=WalkLimits(
                            max_continuous_meters=assistance.max_segment_walk_meters,
                            max_daily_meters=None,
                        ),
                        max_transfers=assistance.max_transfers,
                        rest_interval=assistance.rest_interval_minutes,
                        nap_window=None,
                        avoid_stairs=request.assistance_mode == "assisted",
                    ),
                )
            ],
            days=[
                TripDayInput(
                    day_index=0,
                    date=travel_date,
                    daily_budget_cents=budget_cents,
                    start_location_text=f"{city.city_name.removesuffix('市')}市中心",
                    end_location_text=f"{city.city_name.removesuffix('市')}市中心",
                    time_window={"start": f"{start_time}:00", "end": f"{end_time}:00"},
                )
            ],
        )
        policy_issues = validate_single_day_policy(trip)
        if policy_issues:
            raise TripSchemaError(policy_issues)
        return TripDraftParseResult(
            trip_id=trip_id,
            parsed=parsed,
            confirmation_items=[],
            can_plan=True,
            trip=trip,
        )

    @staticmethod
    def require_planning_ready(result: TripDraftParseResult) -> CreateSingleDayTrip:
        if not result.can_plan or result.trip is None:
            raise TripSchemaError(
                [
                    ValidationIssue(
                        path=item.path,
                        code=item.code,
                        message=item.message,
                        candidates=item.candidates or None,
                    )
                    for item in result.confirmation_items
                ],
                code="TRIP_CONFIRMATION_REQUIRED",
            )
        return result.trip


def _non_blank(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        key = _key(value)
        if value and key not in seen:
            output.append(value)
            seen.add(key)
    return output


def _key(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def _extract_city(text: str) -> str | None:
    matches = [city for city in _CITY_NAMES if city in text]
    return matches[0] if len(matches) == 1 else None


def _explicit_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _extract_date(text: str, reference: date) -> tuple[date | None, ConfirmationItem | None]:
    iso_dates = []
    for match in re.finditer(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text):
        try:
            iso_dates.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            return None, _invalid("date", "travelDate", "自然语言中的日期无效")
    chinese_dates = []
    for match in re.finditer(r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日", text):
        try:
            chinese_dates.append(
                date(int(match.group(1) or reference.year), int(match.group(2)), int(match.group(3)))
            )
        except ValueError:
            return None, _invalid("date", "travelDate", "自然语言中的日期无效")
    found = _unique_dates([*iso_dates, *chinese_dates])
    if len(found) == 1:
        return found[0], None
    if len(found) > 1:
        return None, ConfirmationItem(
            item_id="date",
            path="travelDate",
            code="ambiguous",
            message="检测到多个出行日期，请确认具体日期",
            candidates=[item.isoformat() for item in found],
        )
    if "后天" in text:
        return reference + timedelta(days=2), None
    if "明天" in text:
        return reference + timedelta(days=1), None
    if any(word in text for word in _AMBIGUOUS_DATE_WORDS):
        return None, ConfirmationItem(
            item_id="date",
            path="travelDate",
            code="ambiguous",
            message="相对日期不够明确，请选择具体日期",
            candidates=[
                (reference + timedelta(days=offset)).isoformat()
                for offset in (1, 2, 7)
            ],
        )
    return None, None


def _unique_dates(values: list[date]) -> list[date]:
    return list(dict.fromkeys(values))


def _explicit_time(value: str | None) -> str | None:
    if not value or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return None
    return value


def _extract_time_window(text: str) -> tuple[str | None, str | None, list[ConfirmationItem]]:
    issues: list[ConfirmationItem] = []
    digital = re.search(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)\s*(?:到|至|—|-)\s*([01]?\d|2[0-3]):([0-5]\d)",
        text,
    )
    if digital:
        return (
            f"{int(digital.group(1)):02d}:{digital.group(2)}",
            f"{int(digital.group(3)):02d}:{digital.group(4)}",
            issues,
        )

    chinese = re.search(
        r"(早上|上午|中午|下午|晚上)?\s*(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?"
        r"\s*(?:到|至|—|-)\s*(早上|上午|中午|下午|晚上)?\s*(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?",
        text,
    )
    if chinese:
        start = _chinese_time(chinese.group(1), chinese.group(2), chinese.group(3))
        end = _chinese_time(chinese.group(4), chinese.group(5), chinese.group(6))
        if chinese.group(1) is None and int(chinese.group(2)) <= 7:
            issues.append(_ambiguous_time("start-time", "startTime", int(chinese.group(2)), chinese.group(3)))
            start = None
        if chinese.group(4) is None and int(chinese.group(5)) <= 12:
            issues.append(_ambiguous_time("end-time", "endTime", int(chinese.group(5)), chinese.group(6)))
            end = None
        return start, end, issues

    single = re.search(r"(?<!\d)(\d{1,2})\s*点", text)
    if single:
        hour = int(single.group(1))
        issues.append(_ambiguous_time("end-time", "endTime", hour, None))
    return None, None, issues


def _chinese_time(period: str | None, hour_text: str, minute_text: str | None) -> str | None:
    hour = int(hour_text)
    minute = int(minute_text or 0)
    if hour > 23 or minute > 59:
        return None
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    elif period == "中午" and hour < 11:
        hour += 12
    elif period in {"上午", "早上"} and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _ambiguous_time(item_id: str, path: str, hour: int, minute: str | None) -> ConfirmationItem:
    suffix = f":{int(minute or 0):02d}"
    morning = hour % 12
    evening = morning + 12
    return ConfirmationItem(
        item_id=item_id,
        path=path,
        code="ambiguous",
        message="时间缺少上午/下午信息，请确认 24 小时时间",
        candidates=[f"{morning:02d}{suffix}", f"{evening:02d}{suffix}"],
    )


def _extract_budget_cents(text: str) -> int | None:
    patterns = (
        r"预算(?:不超过|约|大约|控制在)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)",
        r"(\d+(?:\.\d+)?)\s*(?:元|块)(?:左右)?(?:的)?预算",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return round(float(match.group(1)) * 100)
    return None


def _extract_interests(text: str) -> list[str]:
    matches = sorted(
        (interest for interest in _INTEREST_NAMES if interest in text),
        key=len,
        reverse=True,
    )
    selected: list[str] = []
    for interest in matches:
        if not any(interest in existing for existing in selected):
            selected.append(interest)
    return selected


def _extract_places(text: str, kind: str) -> list[str]:
    pattern = (
        r"必去\s*([^，,。.;；]+)"
        if kind == "must"
        else r"(?:不要去|避开)\s*([^，,。.;；]+)"
    )
    return [match.group(1).strip() for match in re.finditer(pattern, text)]


def _missing(item_id: str, path: str, message: str) -> ConfirmationItem:
    return ConfirmationItem(item_id=item_id, path=path, code="missing", message=message)


def _invalid(item_id: str, path: str, message: str) -> ConfirmationItem:
    return ConfirmationItem(item_id=item_id, path=path, code="invalid", message=message)


def _stable_items(items: list[ConfirmationItem]) -> list[ConfirmationItem]:
    order = {
        "cityName": 0,
        "travelDate": 1,
        "startTime": 2,
        "endTime": 3,
        "budgetCents": 4,
        "interests": 5,
        "placeRestrictions": 6,
    }
    unique: dict[tuple[str, str], ConfirmationItem] = {}
    for item in items:
        unique[(item.path, item.code)] = item
    return sorted(unique.values(), key=lambda item: (order.get(item.path, 99), item.code))


__all__ = ["TripDraftParserService"]
