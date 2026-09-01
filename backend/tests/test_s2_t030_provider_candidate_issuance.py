from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time
import json
import sqlite3
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.application.llm_gateway import StrictCandidateSelectionGateway
from app.application.recommendation_service import (
    TrustedRecommendationService,
    _required_match_sort_key,
    _strict_candidate_request,
    required_meal_kinds,
)
from app.core.config import Settings
from app.domain.collaboration_digest import member_digest, shared_digest
from app.domain.models import (
    AddressResolution,
    CityResolution,
    Place,
    PlaceCollection,
    PriceFact,
    Provenance,
    SourceStatus,
)
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.infrastructure.provider_fact_registry import SqliteProviderFactRegistry
from app.infrastructure.trusted_planning_store import proposal_digest
from app.main import create_app
from app.services.planning import CandidatePlanRequest, generate_candidate_plan
from app.services.recommendation import BuiltRouteCandidate, ProviderFactBundle
from app.schemas.trip import Trip
from backend.tests.s2_t003_support import (
    FakeTripDraftRevisionPort,
    revision_with_places,
    revision_with_times,
    revision_with_trip_budget,
)
from backend.tests.test_s2_t003_collaboration_service import (
    _advance_harness_revision,
    _ready_harness,
    _reconfirm_members,
)
from backend.tests.test_s2_t005_unified_plan_version import (
    _authoritative_revision_for_request,
    _state_machine_request,
)


FETCHED_AT = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
CITY_CONTEXT = {
    "countryCode": "CN",
    "cityCode": "310000",
    "cityName": "上海市",
    "center": {"longitude": 121.473701, "latitude": 31.230416},
    "providerConfig": {"provider": "AMAP", "coordinateSystem": "GCJ02"},
}


def _provenance(
    status: SourceStatus,
    *,
    stale: bool = False,
) -> Provenance:
    return Provenance(
        provider="AMAP",
        sourceStatus=status,
        fetchedAt=FETCHED_AT,
        isStale=stale,
    )


def _place(
    place_id: str,
    name: str,
    *,
    category: str = "景点",
    city_code: str = "310000",
    status: SourceStatus = SourceStatus.ONLINE,
    price_cents: int | None = 2_000,
    stale: bool = False,
    longitude: float = 121.47,
    latitude: float = 31.23,
) -> Place:
    price_status = status if price_cents is not None else SourceStatus.UNKNOWN
    return Place(
        placeId=place_id,
        name=name,
        address=f"上海市 {name}",
        cityCode=city_code,
        adCode="310101",
        location={"longitude": longitude, "latitude": latitude},
        category=category,
        telephone=None,
        rating=4.5,
        priceReference=PriceFact(
            amountCents=price_cents,
            currency="CNY",
            kind="门票参考",
            provenance=_provenance(price_status, stale=stale),
        ),
        provenance=_provenance(status, stale=stale),
    )


def _provider_pool() -> list[Place]:
    return [
        _place("poi-bund", "The Bund", category="architecture"),
        _place(
            "poi-furniture",
            "天坛家具(实木)安贞店",
            category="购物服务;家居建材市场;家具城",
        ),
        _place("poi-architecture", "Shanghai Architecture Museum", category="architecture"),
        _place(
            "poi-lunch",
            "Shanghai Local Cuisine",
            category="餐饮服务;中餐厅",
        ),
        _place(
            "poi-dinner",
            "Riverside Restaurant",
            category="餐饮服务;中餐厅",
            status=SourceStatus.VERIFIED_CACHE,
        ),
        _place("poi-garden", "Yu Garden"),
        _place("poi-temple", "City God Temple"),
        _place(
            "poi-art",
            "Shanghai Art Center",
            status=SourceStatus.VERIFIED_CACHE,
            stale=True,
        ),
        _place("poi-science", "Shanghai Science Center"),
        _place("poi-park", "People's Park"),
        _place("poi-hotel", "Shanghai Business Hotel", category="住宿服务;宾馆酒店"),
        _place("poi-avoid", "crowded malls"),
        _place("poi-over-budget", "Luxury Theme Park", price_cents=35_000),
        _place("poi-cross-city", "Hangzhou Museum", city_code="330100"),
        _place(
            "poi-estimated",
            "Estimated Place",
            status=SourceStatus.ESTIMATED,
        ),
    ]


def test_meals_follow_complete_confirmed_meal_windows() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "trips" / "beijing.json"
    trip = Trip.model_validate_json(fixture_path.read_text(encoding="utf-8"))
    trip = trip.model_copy(
        update={
            "city_context": trip.city_context.model_copy(
                update={"city_code": "310000"}
            )
        }
    )

    def with_window(start: time, end: time) -> Trip:
        day = trip.days[0]
        window = day.time_window.model_copy(update={"start": start, "end": end})
        return trip.model_copy(
            update={"days": [day.model_copy(update={"time_window": window})]}
        )

    morning = with_window(time(6, 0), time(11, 0))
    until_dinner = with_window(time(9, 0), time(18, 0))
    full_day = with_window(time(9, 0), time(20, 0))

    assert required_meal_kinds(morning) == ()
    assert required_meal_kinds(until_dinner) == ("LUNCH",)
    assert required_meal_kinds(full_day) == ("LUNCH", "DINNER")

    filtered = TrustedRecommendationService.pre_filter_provider_places(
        _provider_pool(),
        trip=morning,
    )
    assert all("餐饮服务" not in (place.category or "") for place in filtered)


def test_landmark_name_suffix_beats_a_prefix_lookalike() -> None:
    actual_landmark = _required_match_sort_key(
        name="八达岭长城",
        provider_id="poi-badaling",
        label="长城",
    )
    prefix_lookalike = _required_match_sort_key(
        name="长城公园",
        provider_id="poi-great-wall-park",
        label="长城",
    )
    nested_attraction = _required_match_sort_key(
        name="天坛公园花海",
        provider_id="poi-tianta-flowers",
        label="天坛",
    )
    canonical_attraction = _required_match_sort_key(
        name="天坛公园",
        provider_id="poi-tianta-park",
        label="天坛",
    )

    assert actual_landmark < prefix_lookalike
    assert canonical_attraction < nested_attraction


class StubLocationService:
    def __init__(self, places: list[Place]) -> None:
        self.places = places
        self.resolve_calls = 0
        self.geocode_calls = 0
        self.search_calls = 0
        self.search_requests: list[tuple[str, tuple[str, ...]]] = []

    async def resolve_city(self, city_name: str) -> CityResolution:
        self.resolve_calls += 1
        return CityResolution(
            cityContext=CITY_CONTEXT,
            adCode="310000",
            formattedAddress=city_name,
            provenance=_provenance(SourceStatus.ONLINE),
        )

    async def forward_geocode(self, city, *, address: str) -> AddressResolution:
        self.geocode_calls += 1
        return AddressResolution(
            formattedAddress=address,
            cityCode="310000",
            adCode="310000",
            location={"longitude": 121.47, "latitude": 31.23},
            provenance=_provenance(
                SourceStatus.ONLINE
                if self.geocode_calls == 1
                else SourceStatus.VERIFIED_CACHE
            ),
        )

    async def search_places(
        self,
        city,
        *,
        keywords: str,
        types: list[str],
        page: int,
        page_size: int,
    ) -> PlaceCollection:
        self.search_calls += 1
        self.search_requests.append((keywords, tuple(types)))
        dining = [
            place for place in self.places
            if "餐饮服务" in (place.category or "")
        ]
        result_places = dining if types == ["050000"] else [
            place for place in self.places if place not in dining
        ]
        return PlaceCollection(
            cityCode="310000",
            total=len(result_places),
            places=result_places,
            provenance=_provenance(SourceStatus.ONLINE),
        )


class NeverRouteBuilder:
    def __init__(self) -> None:
        self.calls = 0

    async def build(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("invalid digest must not build routes")


class LinkedLocationService:
    """Provider stub whose endpoint/place facts match one planning request."""

    def __init__(self, request: CandidatePlanRequest, places: list[Place]) -> None:
        self.request = request
        self.places = places

    async def resolve_city(self, city_name: str) -> CityResolution:
        return CityResolution(
            cityContext=self.request.trip.city_context,
            adCode="110000",
            formattedAddress=city_name,
            provenance=self.request.start_location.provenance,
        )

    async def forward_geocode(self, city, *, address: str) -> AddressResolution:
        endpoint = (
            self.request.start_location
            if address == self.request.trip.days[0].start_location_text
            else self.request.end_location
        )
        return AddressResolution(
            formattedAddress=address,
            cityCode=endpoint.city_code,
            adCode="110000",
            location=endpoint.location,
            provenance=endpoint.provenance,
        )

    async def search_places(
        self,
        city,
        *,
        keywords: str,
        types: list[str],
        page: int,
        page_size: int,
    ) -> PlaceCollection:
        return PlaceCollection(
            cityCode=self.request.trip.city_context.city_code,
            total=len(self.places),
            places=self.places,
            provenance=self.request.start_location.provenance,
        )


class OrderedSelectionModelClient:
    """Select three non-return facts in a visibly non-default order."""

    model = "qwen-t030-v1-link-fixture"

    def __init__(self, selected_names: tuple[str, str, str]) -> None:
        self.selected_names = selected_names
        self.calls = 0
        self.requests = []

    async def propose_candidate_selection(self, request) -> str:
        self.calls += 1
        self.requests.append(request)
        by_name = {item.display_name: item for item in request.candidate_facts}
        selected = [by_name[name] for name in self.selected_names]
        return json.dumps(
            {
                "schemaVersion": "1.0",
                "selectedPlaceFactIds": [item.place_fact_id for item in selected],
                "selectionRationale": "；".join(
                    item.display_name for item in selected
                ),
                "riskNotes": [],
            },
            ensure_ascii=False,
        )


class CapturingInvalidSelectionModelClient:
    model = "qwen-t008-canonical-summary-fixture"

    def __init__(self) -> None:
        self.requests = []

    async def propose_candidate_selection(self, request) -> str:
        self.requests.append(request)
        return "not-json"


class TraceableRouteBuilder:
    """Build route-backed requests while retaining the selected FactRef order."""

    def __init__(
        self,
        template: CandidatePlanRequest,
        places: list[Place],
    ) -> None:
        self.template = template
        self.places_by_id = {item.placeId: item for item in places}
        self.requests_by_order: dict[tuple[str, ...], CandidatePlanRequest] = {}

    async def build(
        self,
        facts: ProviderFactBundle,
        selected_place_fact_ids: tuple[str, ...],
    ) -> BuiltRouteCandidate:
        provider_id_by_ref = {
            item.place_fact_id: item.provider_place_id
            for item in facts.candidate_facts
        }
        selected_places = [
            self.places_by_id[provider_id_by_ref[fact_ref_id]]
            for fact_ref_id in selected_place_fact_ids
        ]
        end_place = next(
            item
            for item in self.places_by_id.values()
            if item.name == facts.end_location.location_text
            and item.location == facts.end_location.location
        )
        assert end_place.placeId not in {
            item.placeId for item in selected_places
        }

        ordered_places = [*selected_places, end_place]
        tasks = []
        origin = facts.start_location.location
        order_seed = "-".join(
            provider_id_by_ref[item] for item in selected_place_fact_ids
        )
        for index, (template_task, place) in enumerate(
            zip(self.template.task_facts, ordered_places, strict=True),
            start=1,
        ):
            route_id = f"trace-route-{index}-{order_seed}"
            facility_evidence = [
                item.model_copy(update={"referenceId": route_id})
                for item in template_task.route.facilityEvidence
            ]
            route = template_task.route.model_copy(
                update={
                    "routeId": route_id,
                    "origin": origin,
                    "destination": place.location,
                    "facilityEvidence": facility_evidence,
                }
            )
            tasks.append(
                template_task.model_copy(
                    update={
                        "task_id": f"trace-task-{index}-{place.placeId}",
                        "order": index,
                        "title": place.name,
                        "category": (
                            "RETURN"
                            if index == len(ordered_places)
                            else place.category or "PLACE"
                        ),
                        "end_location_text": place.name,
                        "city_code": facts.trip.city_context.city_code,
                        "place": place,
                        "route": route,
                    }
                )
            )
            origin = place.location

        candidate = self.template.model_copy(
            update={
                "trip": facts.trip,
                "start_location": facts.start_location,
                "end_location": facts.end_location,
                "task_facts": tuple(tasks),
                "confirmed_constraints": facts.confirmed_constraints,
            }
        )
        request = CandidatePlanRequest.model_validate_json(
            candidate.model_dump_json(by_alias=True),
            strict=True,
        )
        self.requests_by_order[selected_place_fact_ids] = request
        return BuiltRouteCandidate(
            request=request,
            selected_place_fact_ids=selected_place_fact_ids,
            detour_meters=0,
        )


def _count(database_path: Path, table: str) -> int:
    with sqlite3.connect(database_path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _app(tmp_path: Path, places: list[Place], *, candidate_gateway=None):
    harness = _ready_harness(tmp_path)
    database_path = harness.repository._path
    registry = SqliteProviderFactRegistry(database_path)
    location = StubLocationService(places)
    route_builder = NeverRouteBuilder()
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=location,  # type: ignore[arg-type]
        route_candidate_builder=route_builder,
        provider_fact_registry=registry,
        collaboration_repository=harness.repository,
        trip_draft_revision_port=harness.revisions,
        candidate_selection_gateway=candidate_gateway,
    )
    return app, harness, registry, location, route_builder, database_path


@pytest.mark.asyncio
async def test_ready_group_signs_six_to_eight_filtered_provider_fact_refs(
    tmp_path: Path,
) -> None:
    app, harness, registry, location, route_builder, database_path = _app(
        tmp_path,
        _provider_pool(),
    )
    headers = {
        "X-Organizer-Token": harness.organizer_token,
        "Idempotency-Key": "s2-t030-issue-candidates",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert 6 <= len(payload["candidates"]) <= 8
    assert payload["usedDeterministicFallback"] is True
    assert len(payload["trustedPlan"]["tasks"]) == 5
    assert [
        "餐饮服务" in (item["category"] or "")
        for item in payload["trustedPlan"]["tasks"]
    ] == [False, False, True, False, True]
    assert len(payload["factSetId"]) > 0
    assert len(payload["providerFactDigest"]) == 64
    assert len(payload["provenance"]) == len(payload["candidates"])
    assert all(
        item["factRefId"].startswith("AMAP:")
        for item in payload["candidates"]
    )
    assert {item["sourceStatus"] for item in payload["provenance"]} == {
        "ONLINE",
        "VERIFIED_CACHE",
    }
    selected_ids = {item["placeId"] for item in payload["candidates"]}
    assert "poi-bund" in selected_ids
    assert selected_ids.isdisjoint(
        {
            "poi-furniture",
            "poi-hotel",
            "poi-avoid",
            "poi-over-budget",
            "poi-cross-city",
            "poi-estimated",
        }
    )
    restored = registry.restore(
        harness.revision.trip_id,
        payload["factSetId"],
    )
    assert restored.provider_fact_digest == payload["providerFactDigest"]
    assert len(restored.candidate_facts) == len(payload["candidates"])
    assert restored.trip.mode.value == "GROUP"
    assert len(restored.trip.participants) == 2
    assert location.resolve_calls == 1
    assert location.geocode_calls == 2
    assert location.search_calls >= 1
    assert ("美食街", ()) in location.search_requests
    assert ("餐厅", ("050000",)) in location.search_requests

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        signed_fact_url = (
            f"/api/v1/trips/{harness.revision.trip_id}/provider-fact-sets/"
            f"{payload['factSetId']}"
        )
        missing_token_response = await client.get(
            f"{signed_fact_url}/places",
            params={"providerFactDigest": payload["providerFactDigest"]},
        )
        wrong_token_response = await client.get(
            f"{signed_fact_url}/places",
            params={"providerFactDigest": payload["providerFactDigest"]},
            headers={"X-Organizer-Token": "wrong-organizer-capability"},
        )
        signed_summary_response = await client.get(
            signed_fact_url,
            params={"providerFactDigest": payload["providerFactDigest"]},
            headers={
                **headers,
                "Idempotency-Key": "s2-t030-restore-signed-summary",
            },
        )
        signed_places_response = await client.get(
            f"{signed_fact_url}/places",
            params={"providerFactDigest": payload["providerFactDigest"]},
            headers={
                **headers,
                "Idempotency-Key": "s2-t030-restore-signed-places",
            },
        )
        rejected = await client.post(
            f"/api/v1/trips/{harness.revision.trip_id}/recommendations",
            headers={
                **headers,
                "Idempotency-Key": "s2-t030-invalid-digest",
            },
            json={
                "factSetId": payload["factSetId"],
                "providerFactDigest": "f" * 64,
            },
        )

        changed = revision_with_trip_budget(harness.revision, 31_000)
        _advance_harness_revision(harness, changed)
        not_ready_response = await client.get(
            f"{signed_fact_url}/places",
            params={"providerFactDigest": payload["providerFactDigest"]},
            headers={
                **headers,
                "Idempotency-Key": "s2-t030-old-facts-not-ready",
            },
        )
        _reconfirm_members(harness, ("member-1", "member-2"))
        stale_revision_response = await client.get(
            f"{signed_fact_url}/places",
            params={"providerFactDigest": payload["providerFactDigest"]},
            headers={
                **headers,
                "Idempotency-Key": "s2-t030-old-facts-new-revision",
            },
        )

    assert (
        missing_token_response.status_code,
        missing_token_response.json()["code"],
    ) == (
        403,
        "ORGANIZER_PERMISSION_REQUIRED",
    )
    assert (
        wrong_token_response.status_code,
        wrong_token_response.json()["code"],
    ) == (
        403,
        "ORGANIZER_PERMISSION_REQUIRED",
    )
    assert signed_summary_response.status_code == 200, signed_summary_response.text
    assert signed_places_response.status_code == 200, signed_places_response.text
    for private_response in (signed_summary_response, signed_places_response):
        assert private_response.headers["Cache-Control"] == "no-store"
        assert private_response.headers["Vary"] == "X-Organizer-Token"
    signed_places = signed_places_response.json()["data"]
    assert signed_places["factSetId"] == payload["factSetId"]
    assert signed_places["providerFactDigest"] == payload["providerFactDigest"]
    assert {
        (item["factRefId"], item["providerObjectId"], item["place"]["placeId"])
        for item in signed_places["places"]
    } == {
        (item.place_fact_id, item.provider_place_id, item.provider_place_id)
        for item in restored.candidate_facts
    }
    assert (rejected.status_code, rejected.json()["code"]) == (
        409,
        "PROVIDER_FACT_DIGEST_MISMATCH",
    )
    assert (not_ready_response.status_code, not_ready_response.json()["code"]) == (
        409,
        "COLLABORATION_NOT_READY",
    )
    assert (
        stale_revision_response.status_code,
        stale_revision_response.json()["code"],
    ) == (409, "PROVIDER_FACT_READY_CONTEXT_STALE")
    for denied in (
        missing_token_response,
        wrong_token_response,
        not_ready_response,
        stale_revision_response,
    ):
        assert "data" not in denied.json()
    assert route_builder.calls == 0
    assert _count(database_path, "plan_versions") == 0


@pytest.mark.asyncio
async def test_attraction_labels_ignore_similarly_named_restaurants_and_use_nearby_food_street(
    tmp_path: Path,
) -> None:
    places = [
        _place(
            "poi-palace",
            "故宫博物院",
            category="风景名胜;博物馆",
            longitude=121.4700,
        ),
        _place(
            "poi-temple",
            "天坛公园",
            category="风景名胜;公园",
            longitude=121.4900,
        ),
        _place(
            "poi-museum",
            "城市历史博物馆",
            category="科教文化服务;博物馆",
            longitude=121.4750,
        ),
        _place(
            "poi-food-street",
            "老城美食街",
            category="购物服务;特色商业街",
            longitude=121.4705,
        ),
        _place(
            "poi-palace-restaurant",
            "景运门故宫餐厅",
            category="餐饮服务;中餐厅",
            longitude=121.6000,
        ),
        _place(
            "poi-temple-restaurant",
            "天坛福宴",
            category="餐饮服务;中餐厅",
            longitude=121.6100,
        ),
        _place("poi-park", "城市公园", longitude=121.4800),
        _place("poi-science", "城市科技馆", longitude=121.5000),
    ]
    app, harness, _registry, location, _route_builder, _database_path = _app(
        tmp_path,
        places,
    )
    changed = revision_with_places(
        harness.revision,
        must_visit=["故宫", "天坛"],
        avoid_places=[],
    )
    changed = revision_with_times(changed, "09:00", "18:00")
    _advance_harness_revision(harness, changed)
    _reconfirm_members(harness, ("member-1", "member-2"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers={
                "X-Organizer-Token": harness.organizer_token,
                "Idempotency-Key": "t030-attractions-plus-nearby-food-street",
            },
        )

    assert response.status_code == 200, response.text
    tasks = response.json()["data"]["trustedPlan"]["tasks"]
    assert [item["name"] for item in tasks] == [
        "城市历史博物馆",
        "故宫博物院",
        "老城美食街",
        "天坛公园",
    ]
    assert "景运门故宫餐厅" not in {item["name"] for item in tasks}
    assert ("美食街", ()) in location.search_requests


@pytest.mark.asyncio
async def test_three_hard_must_visit_attractions_coexist_with_two_meals(
    tmp_path: Path,
) -> None:
    places = [
        _place("poi-bund", "The Bund", longitude=121.4700),
        _place(
            "poi-architecture",
            "Shanghai Architecture Museum",
            category="architecture",
            longitude=121.4900,
        ),
        _place("poi-garden", "Yu Garden", longitude=121.5100),
        _place(
            "poi-lunch-street",
            "博物馆美食街",
            category="购物服务;特色商业街",
            longitude=121.4901,
        ),
        _place(
            "poi-dinner-market",
            "豫园夜市",
            category="购物服务;特色商业街",
            status=SourceStatus.VERIFIED_CACHE,
            longitude=121.5101,
        ),
        _place("poi-temple", "City God Temple", longitude=121.5200),
        _place("poi-science", "Shanghai Science Center", longitude=121.5300),
    ]
    app, harness, _registry, _location, _route_builder, _database_path = _app(
        tmp_path,
        places,
    )
    required_names = {
        "The Bund",
        "Shanghai Architecture Museum",
        "Yu Garden",
    }
    changed = revision_with_places(
        harness.revision,
        must_visit=sorted(required_names),
        avoid_places=["crowded malls"],
    )
    _advance_harness_revision(harness, changed)
    _reconfirm_members(harness, ("member-1", "member-2"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers={
                "X-Organizer-Token": harness.organizer_token,
                "Idempotency-Key": "t030-three-required-plus-two-meals",
            },
        )

    assert response.status_code == 200, response.text
    tasks = response.json()["data"]["trustedPlan"]["tasks"]
    assert len(tasks) == 5
    assert required_names <= {item["name"] for item in tasks}
    assert [item["name"] for item in tasks] == [
        "The Bund",
        "Shanghai Architecture Museum",
        "博物馆美食街",
        "Yu Garden",
        "豫园夜市",
    ]


@pytest.mark.asyncio
async def test_short_must_visit_label_does_not_exempt_a_furniture_store(
    tmp_path: Path,
) -> None:
    places = [
        *_provider_pool(),
        _place(
            "poi-tianta-park",
            "天坛公园",
            category="风景名胜;公园广场;公园",
        ),
    ]
    app, harness, _registry, _location, _route_builder, _database_path = _app(
        tmp_path,
        places,
    )
    changed = revision_with_places(
        harness.revision,
        must_visit=["天坛"],
        avoid_places=[],
    )
    _advance_harness_revision(harness, changed)
    _reconfirm_members(harness, ("member-1", "member-2"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers={
                "X-Organizer-Token": harness.organizer_token,
                "Idempotency-Key": "t030-tianta-furniture-collision",
            },
        )

    assert response.status_code == 200, response.text
    selected_ids = {
        item["placeId"] for item in response.json()["data"]["candidates"]
    }
    assert "poi-tianta-park" in selected_ids
    assert "poi-furniture" not in selected_ids


@pytest.mark.asyncio
async def test_exact_must_visit_hotel_is_rejected_as_a_day_activity(
    tmp_path: Path,
) -> None:
    app, harness, _registry, _location, _route_builder, database_path = _app(
        tmp_path,
        _provider_pool(),
    )
    changed = revision_with_places(
        harness.revision,
        must_visit=["Shanghai Business Hotel"],
        avoid_places=[],
    )
    _advance_harness_revision(harness, changed)
    _reconfirm_members(harness, ("member-1", "member-2"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers={
                "X-Organizer-Token": harness.organizer_token,
                "Idempotency-Key": "t030-reject-hotel-day-activity",
            },
        )

    assert (response.status_code, response.json()["code"]) == (
        422,
        "LODGING_NOT_ALLOWED_IN_DAY_PLAN",
    )
    assert _count(database_path, "provider_fact_sets") == 0
    assert _count(database_path, "plan_versions") == 0


@pytest.mark.asyncio
async def test_fewer_than_six_after_hard_filter_issues_no_fact_set(
    tmp_path: Path,
) -> None:
    sparse = [
        _place("poi-bund", "The Bund"),
        _place("poi-garden", "Yu Garden"),
        _place("sparse-lunch", "Sparse Lunch", category="餐饮服务;中餐厅"),
        _place("sparse-dinner", "Sparse Dinner", category="餐饮服务;中餐厅"),
        _place("sparse-hotel", "Sparse Hotel", category="住宿服务;宾馆酒店"),
    ]
    app, harness, _registry, _location, _builder, database_path = _app(
        tmp_path,
        sparse,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers={
                "X-Organizer-Token": harness.organizer_token,
                "Idempotency-Key": "s2-t030-insufficient",
            },
        )

    assert (response.status_code, response.json()["code"]) == (
        422,
        "INSUFFICIENT_TRUSTED_PROVIDER_CANDIDATES",
    )
    assert _count(database_path, "provider_fact_sets") == 0
    assert _count(database_path, "plan_versions") == 0


@pytest.mark.asyncio
async def test_signed_places_never_exposes_legacy_single_trip_facts(
    tmp_path: Path,
) -> None:
    planning_request = _state_machine_request("SINGLE", 1)
    database_path = tmp_path / "legacy-signed-places.sqlite3"
    registry = SqliteProviderFactRegistry(database_path)
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "legacy-amap.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=StubLocationService(_provider_pool()),  # type: ignore[arg-type]
        route_candidate_builder=NeverRouteBuilder(),
        provider_fact_registry=registry,
    )
    app.state.collaboration_readiness_guard.flow_registry.register_confirmed_single(
        planning_request.trip
    )
    signed_places_url = (
        f"/api/v1/trips/{planning_request.trip.trip_id}/"
        "provider-fact-sets/nonexistent-fact-set/places"
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        missing_token_response = await client.get(
            signed_places_url,
            params={"providerFactDigest": "a" * 64},
        )
        bogus_token_response = await client.get(
            signed_places_url,
            params={"providerFactDigest": "a" * 64},
            headers={"X-Organizer-Token": "legacy-bogus-organizer-token"},
        )

    for denied in (missing_token_response, bogus_token_response):
        assert (denied.status_code, denied.json()["code"]) == (
            403,
            "ORGANIZER_PERMISSION_REQUIRED",
        )
        assert "data" not in denied.json()


@pytest.mark.asyncio
async def test_preview_and_formal_gateway_share_mobility_default_summary(
    tmp_path: Path,
) -> None:
    model_client = CapturingInvalidSelectionModelClient()
    app, harness, registry, _location, _builder, _database_path = _app(
        tmp_path,
        _provider_pool(),
        candidate_gateway=StrictCandidateSelectionGateway(model_client),
    )
    participants = list(harness.revision.understanding.participants)
    care = participants[0].care_draft
    assert care is not None
    participants[0] = participants[0].model_copy(
        update={
            "care_draft": care.model_copy(
                update={
                    "assistance_type_hint": "MOBILITY_ASSISTANCE_BETA",
                    "avoid_stairs": None,
                }
            )
        }
    )
    changed = replace(
        harness.revision,
        understanding=harness.revision.understanding.model_copy(
            update={"participants": participants}
        ),
    )
    _advance_harness_revision(harness, changed)
    _reconfirm_members(harness, ("member-1", "member-2"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        issued_response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers={
                "X-Organizer-Token": harness.organizer_token,
                "Idempotency-Key": "s2-t008-mobility-canonical-preview",
            },
        )

    assert issued_response.status_code == 200, issued_response.text
    issued = issued_response.json()["data"]
    assert len(model_client.requests) == 1
    preview_gateway_request = model_client.requests[0]
    formal_gateway_request = _strict_candidate_request(
        UUID("00000000-0000-4000-8000-000000000008"),
        registry.restore(harness.revision.trip_id, issued["factSetId"]),
    )
    preview_contract = preview_gateway_request.model_dump(mode="json", by_alias=True)
    formal_contract = formal_gateway_request.model_dump(mode="json", by_alias=True)
    assert preview_contract.pop("traceId") != formal_contract.pop("traceId")
    assert preview_contract == formal_contract
    assert "MOBILITY_ASSISTANCE_BETA" in (
        preview_gateway_request.confirmed_trip_summary.care_need_labels
    )
    assert "避开楼梯" in (
        preview_gateway_request.confirmed_trip_summary.care_need_labels
    )


@pytest.mark.asyncio
async def test_signed_factref_order_is_the_issued_v1_plan_order(
    tmp_path: Path,
) -> None:
    """T024 closes T030 -> T009 -> T011 without trusting client place facts."""

    planning_request = _state_machine_request("GROUP", 2)
    # This test exercises the legacy formal 2-3 selection contract. Keep its
    # fixture outside meal windows; meal-aware full-day issuance is covered by
    # the dedicated test above.
    source_day = planning_request.trip.days[0]
    day = source_day.model_copy(
        update={
            "time_window": source_day.time_window.model_copy(
                update={"start": time(6, 0), "end": time(11, 0)}
            )
        }
    )
    trip = planning_request.trip.model_copy(update={"days": [day]})
    task_ranges = (
        (time(6, 30), time(7, 10)),
        (time(7, 20), time(8, 0)),
        (time(8, 20), time(9, 0)),
        (time(9, 30), time(10, 10)),
    )
    task_facts = tuple(
        task.model_copy(update={"start_at": start, "end_at": end})
        for task, (start, end) in zip(
            planning_request.task_facts,
            task_ranges,
            strict=True,
        )
    )
    planning_request = CandidatePlanRequest.model_validate_json(
        planning_request.model_copy(
            update={"trip": trip, "task_facts": task_facts}
        ).model_dump_json(by_alias=True),
        strict=True,
    )
    revision = _authoritative_revision_for_request(planning_request)
    database_path = tmp_path / "t030-to-v1.sqlite3"
    repository = SqliteCollaborationRepository(database_path)
    bootstrap = repository.bootstrap_collaboration(
        revision,
        "t030-v1-bootstrap-0001",
    )
    assert bootstrap.organizer_token is not None
    expected_version = 1
    for index, member_key in enumerate(sorted(revision.member_bindings), start=1):
        expected_version = repository.record_confirmation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings[member_key],
            revision=revision.revision,
            source_digest=revision.source_digest,
            shared_digest=shared_digest(revision),
            member_digest=member_digest(revision, member_key),
            expected_version=expected_version,
            idempotency_key=f"t030-v1-confirm-{index:04d}",
        )

    places = [item.place for item in planning_request.task_facts]
    places.extend(
        [
            places[0].model_copy(
                update={
                    "placeId": "poi-trace-extra-one",
                    "name": "Trace Extra One",
                    "location": places[0].location.model_copy(
                        update={"longitude": places[0].location.longitude + 0.001}
                    ),
                }
            ),
            places[1].model_copy(
                update={
                    "placeId": "poi-trace-extra-two",
                    "name": "Trace Extra Two",
                    "location": places[1].location.model_copy(
                        update={"latitude": places[1].location.latitude + 0.001}
                    ),
                }
            ),
            places[2].model_copy(
                update={
                    "placeId": "poi-trace-extra-three",
                    "name": "Trace Extra Three",
                    "location": places[2].location.model_copy(
                        update={"longitude": places[2].location.longitude - 0.001}
                    ),
                }
            ),
            places[0].model_copy(
                update={
                    "placeId": "poi-trace-extra-four",
                    "name": "Trace Extra Four",
                    "location": places[0].location.model_copy(
                        update={"latitude": places[0].location.latitude - 0.001}
                    ),
                }
            ),
        ]
    )
    registry = SqliteProviderFactRegistry(database_path)
    route_builder = TraceableRouteBuilder(planning_request, places)
    model_client = OrderedSelectionModelClient(
        (
            planning_request.task_facts[2].place.name,
            planning_request.task_facts[0].place.name,
            "Trace Extra One",
        )
    )
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap-linked.sqlite3",
            plan_version_db_path=database_path,
            bailian_api_key=None,
        ),
        service=LinkedLocationService(planning_request, places),  # type: ignore[arg-type]
        route_candidate_builder=route_builder,
        provider_fact_registry=registry,
        collaboration_repository=repository,
        trip_draft_revision_port=FakeTripDraftRevisionPort(revision),
        candidate_selection_gateway=StrictCandidateSelectionGateway(model_client),
    )
    headers = {"X-Organizer-Token": bootstrap.organizer_token}

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            issued_response = await client.get(
                f"/api/v2/trips/{revision.trip_id}/recommendations",
                headers={
                    **headers,
                    "Idempotency-Key": "t030-v1-issue-facts-0001",
                },
            )
            assert issued_response.status_code == 200, issued_response.text
            issued = issued_response.json()["data"]

            selected_response = await client.post(
                f"/api/v1/trips/{revision.trip_id}/recommendations",
                headers={
                    **headers,
                    "Idempotency-Key": "t030-v1-select-0001",
                },
                json={
                    "schemaVersion": "1.0",
                    "factSetId": issued["factSetId"],
                    "providerFactDigest": issued["providerFactDigest"],
                },
            )
            assert selected_response.status_code == 200, selected_response.text
            selected = selected_response.json()["data"]
            selected_refs = tuple(selected["selectedPlaceFactIds"])
            selected_request = route_builder.requests_by_order[selected_refs]

            generated_response = await client.post(
                f"/api/v1/trips/{revision.trip_id}/plan-versions/generate",
                headers={
                    **headers,
                    "Idempotency-Key": "t030-v1-generate-0001",
                },
                json=selected_request.model_dump(mode="json", by_alias=True),
            )
            assert generated_response.status_code == 200, generated_response.text
            v1 = generated_response.json()["data"]

            planning_facts_response = await client.get(
                f"/api/v1/trips/{revision.trip_id}/planning-facts",
                headers={
                    **headers,
                    "Idempotency-Key": "t030-v1-restore-planning-facts-0001",
                },
            )
            assert planning_facts_response.status_code == 200, (
                planning_facts_response.text
            )
            restored_planning_facts = planning_facts_response.json()["data"]

    snapshot = registry.restore_snapshot(revision.trip_id, issued["factSetId"])
    assert snapshot.provider_fact_digest == issued["providerFactDigest"]
    assert selected["providerFactDigest"] == issued["providerFactDigest"]
    provider_id_by_ref = {
        item.fact_ref_id: item.provider_object_id
        for item in snapshot.references
        if item.kind == "PLACE"
    }
    selected_provider_ids = [provider_id_by_ref[item] for item in selected_refs]
    request_place_ids = [item.place.placeId for item in selected_request.task_facts]
    candidate = generate_candidate_plan(selected_request)
    candidate_json = selected["decision"]["selectedPlan"]
    candidate_place_ids = [item["placeId"] for item in candidate_json["tasks"]]
    candidate_task_ids = [item["taskId"] for item in candidate_json["tasks"]]
    v1_task_ids = [item["taskId"] for item in v1["days"][0]["tasks"]]
    trusted_tasks = issued["trustedPlan"]["tasks"]
    trusted_refs = [item["factRefId"] for item in trusted_tasks]
    trusted_place_ids = [item["placeId"] for item in trusted_tasks]
    restored_place_ids = [
        item["place"]["placeId"]
        for item in restored_planning_facts["taskFacts"]
    ]

    assert list(selected_refs) == trusted_refs
    assert selected_provider_ids == trusted_place_ids
    assert model_client.calls == 2
    preview_gateway_request, formal_gateway_request = model_client.requests
    preview_contract = preview_gateway_request.model_dump(mode="json", by_alias=True)
    formal_contract = formal_gateway_request.model_dump(mode="json", by_alias=True)
    assert preview_contract.pop("traceId") != formal_contract.pop("traceId")
    assert preview_contract == formal_contract
    assert request_place_ids[: len(selected_refs)] == selected_provider_ids
    assert candidate_place_ids == request_place_ids
    assert restored_place_ids == request_place_ids
    assert v1_task_ids == candidate_task_ids
    assert selected_request.task_facts[-1].category == "RETURN"
    assert candidate_json["tasks"][-1]["category"] == "RETURN"
    assert v1["days"][0]["tasks"][-1]["category"] == "RETURN"
    assert candidate_json["candidateId"] == candidate.candidate_id

    plan_id = UUID(v1["planId"])
    plan = app.state.plan_version_service.get_plan_version(revision.trip_id, plan_id)
    trusted_request = (
        app.state.planning_boundary_service.trust_repository.get_candidate_request(
            plan_id
        )
    )
    assert trusted_request == selected_request
    with sqlite3.connect(database_path) as connection:
        fact_row = connection.execute(
            "SELECT provider_fact_digest FROM provider_fact_sets "
            "WHERE fact_set_id=? AND trip_id=?",
            (issued["factSetId"], str(revision.trip_id)),
        ).fetchone()
        issuance_row = connection.execute(
            "SELECT issuance_state, proposal_digest, candidate_facts_json "
            "FROM trusted_plan_issuances WHERE plan_id=? AND trip_id=?",
            (str(plan_id), str(revision.trip_id)),
        ).fetchone()
    assert fact_row == (issued["providerFactDigest"],)
    assert issuance_row is not None
    assert issuance_row[0] == "ISSUED"
    assert issuance_row[1] == proposal_digest(plan)
    persisted_request = CandidatePlanRequest.model_validate_json(
        issuance_row[2],
        strict=True,
    )
    assert [item.place.placeId for item in persisted_request.task_facts] == (
        request_place_ids
    )
