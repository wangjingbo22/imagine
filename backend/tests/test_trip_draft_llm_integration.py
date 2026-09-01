from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.trip_draft_service import TripDraftParserService
from app.domain.models import CityResolution, Provenance, SourceStatus
from app.domain.trip_draft import LlmTripDraftFields, TripDraftParseRequest
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig


class FixtureCityResolver:
    async def resolve_city(self, city_name: str) -> CityResolution:
        assert city_name == "武汉"
        return CityResolution(
            cityContext=CityContext(
                country_code="CN",
                city_code="420100",
                city_name="武汉市",
                center=GeoPoint(longitude=114.305393, latitude=30.593099),
                provider_config=ProviderConfig(
                    provider="AMAP",
                    coordinate_system="GCJ02",
                ),
            ),
            provenance=Provenance(
                sourceStatus=SourceStatus.VERIFIED_CACHE,
                fetchedAt=datetime(2026, 8, 26, tzinfo=UTC),
                isStale=False,
            ),
        )


class FixtureLlmExtractor:
    model = "fixture-qwen"

    async def extract(self, *, text: str, reference_date) -> LlmTripDraftFields:
        assert text == "请按我的完整安排生成行程"
        assert reference_date.isoformat() == "2026-08-26"
        return LlmTripDraftFields(
            city_name="武汉",
            travel_date="2026-09-03",
            start_time="09:30",
            end_time="19:00",
            start_location_text="武汉站",
            end_location_text="汉口站",
            budget_cents=50_000,
            interests=["建筑"],
            must_visit=["黄鹤楼"],
            avoid_places=["拥挤商场"],
        )


@pytest.mark.asyncio
async def test_llm_candidates_enter_trip_only_after_rule_validation() -> None:
    service = TripDraftParserService(
        FixtureCityResolver(),
        llm_extractor=FixtureLlmExtractor(),
    )

    result = await service.parse(
        TripDraftParseRequest(
            natural_language_request="请按我的完整安排生成行程",
            reference_date="2026-08-26",
        )
    )

    assert result.can_plan is True
    assert result.recognition_source == "BAILIAN"
    assert result.recognition_model == "fixture-qwen"
    assert result.degraded_reason is None
    assert result.confirmation_items == []
    assert result.trip is not None
    assert result.trip.city_context.city_code == "420100"
    assert result.trip.total_budget_cents == 50_000
    assert result.trip.days[0].start_location_text == "武汉站"
    assert result.trip.days[0].end_location_text == "汉口站"
    assert [item.value for item in result.trip.participants[0].preferences] == [
        "建筑",
        "黄鹤楼",
        "拥挤商场",
    ]


class FailingLlmExtractor:
    model = "fixture-qwen"

    async def extract(self, *, text: str, reference_date) -> LlmTripDraftFields:
        from app.domain.trip_draft import TripDraftExtractionError

        raise TripDraftExtractionError("BAILIAN_TIMEOUT")


@pytest.mark.asyncio
async def test_llm_failure_is_visible_when_rules_take_over() -> None:
    service = TripDraftParserService(
        FixtureCityResolver(),
        llm_extractor=FailingLlmExtractor(),
    )

    result = await service.parse(
        TripDraftParseRequest(
            natural_language_request="武汉 2026-09-03 09:30 到 19:00，预算500元，喜欢建筑",
            city_name="武汉",
            travel_date="2026-09-03",
            start_time="09:30",
            end_time="19:00",
            start_location_text="武汉站",
            end_location_text="汉口站",
            budget_cents=50_000,
            interests=["建筑"],
            reference_date="2026-08-26",
        )
    )

    assert result.can_plan is True
    assert result.recognition_source == "DEGRADED_RULES"
    assert result.recognition_model is None
    assert result.degraded_reason == "BAILIAN_TIMEOUT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("travel_date", "start_time", "expected_path"),
    [
        ("2026-09-02", "11:00", "travelDate"),
        ("2026-09-03", "09:00", "startTime"),
    ],
)
async def test_parser_rejects_past_dates_and_elapsed_same_day_times(
    travel_date: str,
    start_time: str,
    expected_path: str,
) -> None:
    service = TripDraftParserService(FixtureCityResolver())

    result = await service.parse(
        TripDraftParseRequest(
            natural_language_request="武汉一日行程，喜欢建筑",
            city_name="武汉",
            travel_date=travel_date,
            start_time=start_time,
            end_time="19:00",
            start_location_text="武汉站",
            end_location_text="汉口站",
            budget_cents=50_000,
            interests=["建筑"],
            reference_date="2026-09-03",
            reference_time="10:00",
        )
    )

    assert result.can_plan is False
    assert any(item.path == expected_path and item.code == "invalid" for item in result.confirmation_items)
