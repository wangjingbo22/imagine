from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.domain.models import (
    CityResolution,
    Place,
    PlaceCollection,
    PriceFact,
    Provenance,
    Route,
    RouteCollection,
    SourceStatus,
    TravelMode,
)
from app.domain.collaboration import QUESTION_IDS
from app.domain.trip_draft import (
    CareDraft,
    CareWalkLimits,
    FieldEvidence,
    ParticipantUnderstanding,
    TripUnderstandingProposal,
    TripUnderstandingTrip,
)
from app.main import create_app
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig
from backend.tests.test_s1_t024_golden_path import (
    _candidate_request_from_provider,
    _fixture,
    _review_confirmations,
)
from backend.tests.test_s2_t002_http import (
    CountingGateway,
)


class SingleTripProvider:
    """Deterministic external seam; all stateful services use production wiring."""

    def __init__(self) -> None:
        self.resolve_calls = 0
        self.search_calls = 0
        self.route_calls = 0
        self._provenance = Provenance(
            sourceStatus=SourceStatus.ONLINE,
            fetchedAt=datetime(2026, 9, 5, tzinfo=UTC),
            isStale=False,
        )
        self._city = CityContext(
            country_code="CN",
            city_code="110000",
            city_name="北京市",
            center=GeoPoint(longitude=116.407387, latitude=39.904179),
            provider_config=ProviderConfig(
                provider="AMAP",
                coordinate_system="GCJ02",
            ),
        )

    async def resolve_city(self, city_name: str) -> CityResolution:
        self.resolve_calls += 1
        assert city_name == "北京"
        return CityResolution(
            cityContext=self._city,
            provenance=self._provenance,
        )

    async def search_places(
        self,
        city: CityContext,
        *,
        keywords: str,
        types: list[str],
        page: int,
        page_size: int,
    ) -> PlaceCollection:
        self.search_calls += 1
        assert city.city_code == "110000"
        assert page == 1
        assert page_size in {1, 20, 25}
        if page_size == 25 or keywords == "museum":
            places = [
                self._place(index, name=f"历史文化候选 {index}")
                for index in range(1, 7)
            ]
        else:
            selected = {
                "故宫博物院": (11, "故宫博物院"),
                "北京风味午餐": (12, "北京风味午餐"),
                "北京市中心": (13, "北京市中心"),
            }.get(keywords)
            assert selected is not None
            places = [self._place(selected[0], name=selected[1])]
        return PlaceCollection(
            cityCode="110000",
            total=len(places),
            places=places,
            provenance=self._provenance,
        )

    def _place(self, index: int, *, name: str) -> Place:
        location = (
            GeoPoint(longitude=116.407387, latitude=39.904179)
            if name == "北京市中心"
            else GeoPoint(
                longitude=116.40 + index / 1000,
                latitude=39.90 + index / 1000,
            )
        )
        return Place(
            placeId=f"B000A{index:05d}",
            name=name,
            address=f"Beijing test address {index}",
            cityCode="110000",
            location=location,
            category="museum",
            priceReference=PriceFact(
                amountCents=(index % 10 + 1) * 1000,
                currency="CNY",
                kind="admission",
                provenance=self._provenance,
            ),
            provenance=self._provenance,
        )

    async def plan_route(
        self,
        city: CityContext,
        *,
        origin: GeoPoint,
        destination: GeoPoint,
        mode: TravelMode,
        strategy: int | None,
    ) -> RouteCollection:
        self.route_calls += 1
        assert city.city_code == "110000"
        assert strategy is None
        route = Route(
            routeId=f"route-s2-t024-{self.route_calls}",
            mode=mode,
            origin=origin,
            destination=destination,
            distanceMeters=300,
            durationSeconds=600,
            walkingDistanceMeters=300,
            transferCount=0,
            steps=[],
            facilityEvidence=[],
            priceReference=PriceFact(
                amountCents=0,
                currency="CNY",
                kind="route",
                provenance=self._provenance,
            ),
            provenance=self._provenance,
        )
        return RouteCollection(
            cityCode="110000",
            routes=[route],
            provenance=self._provenance,
        )


def _provider_search_payload(trip_id: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "tripId": trip_id,
        "cityContext": {
            "countryCode": "CN",
            "cityCode": "110000",
            "cityName": "北京市",
            "center": {"longitude": 116.407387, "latitude": 39.904179},
            "providerConfig": {
                "provider": "AMAP",
                "coordinateSystem": "GCJ02",
            },
        },
        "keywords": "museum",
        "types": [],
        "page": 1,
        "pageSize": 20,
    }


def _ready_low_stamina_proposal() -> TripUnderstandingProposal:
    trip = TripUnderstandingTrip(
        cityName="北京",
        travelDate=date(2026, 9, 5),
        startTime="09:00",
        endTime="18:00",
        startLocationText="北京市中心",
        endLocationText="北京市中心",
        budgetCents=35_000,
    )
    participant = ParticipantUnderstanding(
        memberKey="member-1",
        nickname="单人旅客",
        budgetCapCents=35_000,
        interests=["历史文化"],
        mustVisit=[],
        avoidPlaces=[],
        careDraft=CareDraft(
            assistanceTypeHint="LOW_STAMINA",
            childAge=None,
            walkLimits=CareWalkLimits(
                maxContinuousMeters=800,
                maxDailyMeters=None,
            ),
            maxTransfers=1,
            restIntervalMinutes=60,
            napWindow=None,
            avoidStairs=False,
        ),
    )
    evidence_specs = (
        ("trip.cityName", None, "北京"),
        ("trip.travelDate", None, "2026-09-05"),
        ("trip.startTime", None, "09:00"),
        ("trip.endTime", None, "18:00"),
        ("trip.startLocationText", None, "北京市中心"),
        ("trip.endLocationText", None, "北京市中心"),
        ("trip.budgetCents", None, "35000"),
        ("participants[0].nickname", "member-1", "单人旅客"),
        ("participants[0].budgetCapCents", "member-1", "35000"),
        ("participants[0].interests[0]", "member-1", "历史文化"),
        (
            "participants[0].careDraft.assistanceTypeHint",
            "member-1",
            "LOW_STAMINA",
        ),
        (
            "participants[0].careDraft.walkLimits.maxContinuousMeters",
            "member-1",
            "800",
        ),
        ("participants[0].careDraft.maxTransfers", "member-1", "1"),
        (
            "participants[0].careDraft.restIntervalMinutes",
            "member-1",
            "60",
        ),
        ("participants[0].careDraft.avoidStairs", "member-1", "false"),
    )
    return TripUnderstandingProposal(
        schemaVersion="1.0",
        trip=trip,
        participants=[participant],
        fieldEvidence=[
            FieldEvidence(
                fieldPath=path,
                memberKey=member_key,
                sourceType="USER_TEXT",
                sourceText=source_text,
            )
            for path, member_key, source_text in evidence_specs
        ],
        missingFields=[],
        ambiguities=[],
        confirmationQuestions=[],
    )


def _conversation_payload(proposal: TripUnderstandingProposal) -> dict[str, object]:
    evidence = " ".join(item.source_text for item in proposal.field_evidence)
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-26",
        "naturalLanguageRequest": evidence,
        "answers": [
            {"questionId": question_id, "answer": evidence}
            for question_id in QUESTION_IDS
        ],
    }


def _canonical_trip(
    *,
    trip_id: str,
    participant_id: str,
    city_context: dict[str, object],
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "tripId": trip_id,
        "mode": "SINGLE",
        "status": "DRAFT",
        "cityContext": city_context,
        "startDate": "2026-09-05",
        "endDate": "2026-09-05",
        "currency": "CNY",
        "totalBudgetCents": 35_000,
        "participants": [
            {
                "participantId": participant_id,
                "nickname": "单人旅客",
                "budgetCapCents": 35_000,
                "preferences": [
                    {
                        "type": "INTEREST",
                        "value": "历史文化",
                        "weight": 4,
                        "isHard": False,
                    }
                ],
                "assistanceProfile": {
                    "type": "LOW_STAMINA",
                    "childAge": None,
                    "walkLimits": {
                        "maxContinuousMeters": 800,
                        "maxDailyMeters": None,
                    },
                    "maxTransfers": 1,
                    "restInterval": 60,
                    "napWindow": None,
                    "avoidStairs": False,
                },
            }
        ],
        "days": [
            {
                "dayIndex": 0,
                "date": "2026-09-05",
                "dailyBudgetCents": 35_000,
                "startLocationText": "北京市中心",
                "endLocationText": "北京市中心",
                "timeWindow": {"start": "09:00:00", "end": "18:00:00"},
            }
        ],
    }


@pytest.mark.asyncio
async def test_single_ready_collaboration_reuses_canonical_trip_through_v1_start(
    tmp_path: Path,
) -> None:
    """One production-composed ASGI/SQLite chain crosses T002/T003 into V1."""

    database_path = tmp_path / "s2-t024-single.sqlite3"
    provider = SingleTripProvider()
    proposal = _ready_low_stamina_proposal()
    gateway = CountingGateway(proposal)
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=provider,  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": "s2-t024-create-single-0001"},
            json=_conversation_payload(proposal),
        )
        assert created.status_code == 200, created.text
        created_data = created.json()["data"]
        revision = created_data["revision"]
        access = created_data["organizerAccess"]
        trip_id = revision["tripId"]
        organizer_token = access["organizerToken"]
        organizer_id = access["organizerParticipantId"]
        assert gateway.calls == 1

        city_response = await client.post(
            "/api/v1/cities/resolve",
            json={"schemaVersion": "1.0", "cityName": "北京"},
        )
        assert city_response.status_code == 200, city_response.text
        city_resolution = city_response.json()["data"]

        blocked = await client.post(
            "/api/v1/places/search",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t024-provider-blocked-0001",
            },
            json=_provider_search_payload(trip_id),
        )
        assert (blocked.status_code, blocked.json()["code"]) == (
            409,
            "COLLABORATION_NOT_READY",
        )
        assert provider.search_calls == 0

        blocked_planning_trip = await client.get(
            f"/api/v2/trips/{trip_id}/planning-trip",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t024-planning-trip-blocked-0001",
            },
        )
        assert (
            blocked_planning_trip.status_code,
            blocked_planning_trip.json()["code"],
        ) == (409, "COLLABORATION_NOT_READY")
        assert provider.resolve_calls == 1

        confirmed = await client.post(
            f"/api/v2/trips/{trip_id}/participants/{organizer_id}/confirm",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t024-confirm-single-0001",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": 1,
                "expectedVersion": 1,
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["data"]["status"] == "READY_TO_PLAN"
        assert confirmed.json()["data"]["progress"] == {
            "confirmedCount": 1,
            "expectedCount": 1,
            "openIssueCount": 0,
        }

        provider_result = await client.post(
            "/api/v1/places/search",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t024-provider-ready-0001",
            },
            json=_provider_search_payload(trip_id),
        )
        assert provider_result.status_code == 200, provider_result.text
        assert provider.search_calls == 1
        assert len(provider_result.json()["data"]["places"]) == 6

        recommendation = await client.get(
            f"/api/v2/trips/{trip_id}/recommendations",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t024-recommend-ready-0001",
            },
        )
        assert recommendation.status_code == 200, recommendation.text
        recommendation_data = recommendation.json()["data"]
        assert len(recommendation_data["candidates"]) == 6
        assert len(recommendation_data["trustedPlan"]["tasks"]) in {3, 4}
        assert provider.resolve_calls == 2
        assert provider.search_calls == 2

        expected_trip = _canonical_trip(
            trip_id=trip_id,
            participant_id=organizer_id,
            city_context=city_resolution["cityContext"],
        )
        planning_trip_response = await client.get(
            f"/api/v2/trips/{trip_id}/planning-trip",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "s2-t024-planning-trip-0001",
            },
        )
        assert planning_trip_response.status_code == 200, planning_trip_response.text
        assert planning_trip_response.headers["Cache-Control"] == "no-store"
        assert planning_trip_response.headers["Vary"] == "X-Organizer-Token"
        planning_trip = planning_trip_response.json()["data"]
        assert planning_trip == expected_trip
        assert provider.resolve_calls == 3
        with sqlite3.connect(database_path) as connection:
            stored_trip = connection.execute(
                "SELECT trip_json FROM confirmed_trip_inputs WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()
            stored_constraint = connection.execute(
                "SELECT status, profile_json FROM constraint_profiles WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()
        assert stored_trip is not None
        assert json.loads(stored_trip[0]) == expected_trip
        assert stored_constraint is not None
        assert stored_constraint[0] == "CONSTRAINT_CONFIRMED"
        assert json.loads(stored_constraint[1]) == expected_trip["participants"][0][
            "assistanceProfile"
        ]

        client.headers["X-Organizer-Token"] = organizer_token
        planning_request = await _candidate_request_from_provider(
            client,
            trip=deepcopy(planning_trip),
            city_resolution=city_resolution,
            fixture=_fixture(),
        )
        v1 = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            headers={
                "Idempotency-Key": "s2-t024-generate-v1-0001",
            },
            json=planning_request,
        )
        assert v1.status_code == 422, v1.text
        assert v1.json()["code"] == "CANDIDATE_CONFIRMATION_REQUIRED"
        review = v1.json()["errors"][0]["review"]
        confirmed_review = await client.post(
            f"/api/v1/trips/{trip_id}/plan-reviews/{review['reviewId']}/confirm",
            headers={"Idempotency-Key": "s2-t024-confirm-review-0001"},
            json={
                "schemaVersion": "1.0",
                "confirmations": _review_confirmations(review, _fixture()),
            },
        )
        assert confirmed_review.status_code == 200, confirmed_review.text
        v1_data = confirmed_review.json()["data"]
        assert v1_data["version"] == 1
        assert v1_data["status"] == "PROPOSED"
        assert v1_data["tripSnapshot"]["participants"][0][
            "participantId"
        ] == organizer_id

        v1_confirmed = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{v1_data['planId']}/confirm",
            headers={"Idempotency-Key": "s2-t024-confirm-v1-0001"},
        )
        assert v1_confirmed.status_code == 200, v1_confirmed.text
        assert v1_confirmed.json()["data"]["planId"] == v1_data["planId"]
        assert v1_confirmed.json()["data"]["planStatus"] == "CURRENT"

        started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
        assert started.status_code == 200, started.text
        assert started.json()["data"]["tripStatus"] == "EXECUTING"

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE trip_id = ?",
            (trip_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT flow_kind FROM trip_flow_registry WHERE trip_id = ?",
            (trip_id,),
        ).fetchone()[0] == "COLLABORATION_V2"
