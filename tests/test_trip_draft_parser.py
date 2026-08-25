from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import httpx
import pytest

from app.application.trip_draft_service import TripDraftParserService
from app.domain.models import CityResolution, Provenance, SourceStatus
from app.domain.trip_draft import TripDraftParseRequest
from app.main import create_app
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig
from app.schemas.validation_error import TripSchemaError


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trip_drafts"
PARSE_EVIDENCE = (
    Path(__file__).parent.parent
    / "docs"
    / "testing"
    / "evidence"
    / "s1_t002_complete_parse_result.json"
)


class FixtureCityResolver:
    city_codes = {"北京": "110000", "上海": "310000", "成都": "510100"}
    centers = {
        "北京": (116.407387, 39.904179),
        "上海": (121.473701, 31.230416),
        "成都": (104.066541, 30.572269),
    }

    async def resolve_city(self, city_name: str) -> CityResolution:
        longitude, latitude = self.centers[city_name]
        return CityResolution(
            cityContext=CityContext(
                country_code="CN",
                city_code=self.city_codes[city_name],
                city_name=f"{city_name}市",
                center=GeoPoint(longitude=longitude, latitude=latitude),
                provider_config=ProviderConfig(
                    provider="AMAP", coordinate_system="GCJ02"
                ),
            ),
            provenance=Provenance(
                sourceStatus=SourceStatus.VERIFIED_CACHE,
                fetchedAt=datetime(2026, 8, 25, tzinfo=UTC),
                isStale=False,
            ),
        )


@pytest.mark.parametrize("fixture_path", sorted(FIXTURE_DIR.glob("*.json")), ids=lambda path: path.stem)
@pytest.mark.asyncio
async def test_five_natural_language_fixtures_have_stable_confirmation_contract(
    fixture_path: Path,
) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    service = TripDraftParserService(FixtureCityResolver())

    result = await service.parse(TripDraftParseRequest.model_validate(fixture["request"]))

    assert result.can_plan is fixture["expectedCanPlan"]
    assert [item.path for item in result.confirmation_items] == fixture["expectedConfirmationPaths"]
    if result.can_plan:
        assert result.trip is not None
        assert result.trip.city_context.city_code == "110000"
        assert result.trip.participants[0].preferences
        assert result.trip.days[0].day_index == 0
        assert result.trip.total_budget_cents == 35_000
    else:
        assert result.trip is None


@pytest.mark.asyncio
async def test_unconfirmed_draft_is_rejected_before_planning() -> None:
    fixture = json.loads((FIXTURE_DIR / "missing_budget.json").read_text(encoding="utf-8"))
    service = TripDraftParserService(FixtureCityResolver())
    result = await service.parse(TripDraftParseRequest.model_validate(fixture["request"]))

    with pytest.raises(TripSchemaError) as captured:
        service.require_planning_ready(result)

    assert captured.value.code == "TRIP_CONFIRMATION_REQUIRED"
    assert [item.path for item in captured.value.errors] == ["budgetCents"]


@pytest.mark.asyncio
async def test_parse_and_confirm_http_endpoints_enforce_confirmation_gate() -> None:
    app = create_app(
        service=FixtureCityResolver(),  # type: ignore[arg-type]
        plan_service=object(),  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app)
    missing = json.loads((FIXTURE_DIR / "missing_budget.json").read_text(encoding="utf-8"))["request"]
    complete = json.loads((FIXTURE_DIR / "complete.json").read_text(encoding="utf-8"))["request"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        parsed = await client.post("/api/v1/trips/drafts/parse", json=missing)
        blocked = await client.post("/api/v1/trips/drafts/confirm", json=missing)
        confirmed = await client.post("/api/v1/trips/drafts/confirm", json=complete)

    assert parsed.status_code == 200
    assert parsed.json()["data"]["canPlan"] is False
    assert parsed.json()["data"]["confirmationItems"][0]["path"] == "budgetCents"
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "TRIP_CONFIRMATION_REQUIRED"
    assert blocked.json()["errors"][0]["path"] == "budgetCents"
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["cityContext"]["cityCode"] == "110000"


def test_complete_parse_result_evidence_matches_unified_trip_contract() -> None:
    evidence = json.loads(PARSE_EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["canPlan"] is True
    assert evidence["confirmationItems"] == []
    assert evidence["trip"]["tripId"] == evidence["tripId"]
    assert evidence["trip"]["cityContext"]["cityCode"] == "110000"
    assert evidence["trip"]["participants"][0]["budgetCapCents"] == 35_000
    assert evidence["trip"]["days"][0]["timeWindow"] == {
        "start": "09:00:00",
        "end": "20:00:00",
    }
