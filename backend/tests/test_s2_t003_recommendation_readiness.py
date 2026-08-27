from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.application.collaboration_ports import PlanningAccess, PlanningOperation
from app.application.recommendation_service import RecommendationOrchestrationService
from app.application.collaboration_ports import UnavailableTripDraftRevisionPort
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from backend.tests.s2_t003_support import load_revision
from app.services.recommendation import RecommendationOrchestrationRequest


TRIP_ID = UUID("55555555-5555-4555-8555-555555555555")


class CountingFactRegistry:
    def __init__(self) -> None:
        self.calls = 0

    def restore(self, trip_id, fact_set_id):
        self.calls += 1
        raise AssertionError("fact restore must not run")


class CountingProposalGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def propose(self, request):
        self.calls += 1
        raise AssertionError("proposal gateway must not run")


class CountingRouteBuilder:
    def __init__(self) -> None:
        self.calls = 0

    async def build(self, facts, selected_place_fact_ids):
        self.calls += 1
        raise AssertionError("route builder must not run")


class CountingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        raise AssertionError("planner must not run")


class RejectingReadinessGuard:
    @contextmanager
    def operation(self, access: PlanningAccess):
        raise AppError(
            "COLLABORATION_NOT_READY",
            "全部成员确认并解决冲突后才能继续",
            409,
            False,
        )
        yield


@pytest.mark.asyncio
async def test_recommendation_not_ready_touches_no_downstream_port() -> None:
    registry = CountingFactRegistry()
    gateway = CountingProposalGateway()
    builder = CountingRouteBuilder()
    planner = CountingPlanner()
    service = RecommendationOrchestrationService(
        fact_registry=registry,
        proposal_gateway=gateway,
        route_builder=builder,
        planner=planner,
        readiness_guard=RejectingReadinessGuard(),
    )

    with pytest.raises(AppError, match="全部成员确认"):
        await service.recommend(
            trip_id=TRIP_ID,
            request=RecommendationOrchestrationRequest(
                factSetId="facts-test",
                providerFactDigest="a" * 64,
            ),
            access=PlanningAccess(
                trip_id=TRIP_ID,
                organizer_capability="organizer-token",
                operation_id="recommendation-test",
                operation=PlanningOperation.RECOMMENDATION,
            ),
        )

    assert (registry.calls, gateway.calls, builder.calls, planner.calls) == (
        0,
        0,
        0,
        0,
    )


@pytest.mark.asyncio
async def test_t002_unavailable_v2_recommendation_calls_no_provider(tmp_path: Path) -> None:
    class LocationSpy:
        calls = 0

        async def resolve_city(self, city_name: str):
            self.calls += 1
            raise AssertionError("provider must not run")

    location = LocationSpy()
    settings = Settings(
        amap_web_service_key="test-amap",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
        plan_version_db_path=tmp_path / "plan.sqlite3",
    )
    app = create_app(
        settings=settings,
        service=location,  # type: ignore[arg-type]
        trip_draft_revision_port=UnavailableTripDraftRevisionPort(),
    )
    revision = load_revision()
    bootstrap = app.state.collaboration_service.repository.bootstrap_collaboration(
        revision, "bootstrap-recommendation-test"
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{revision.trip_id}/recommendations",
            headers={"X-Organizer-Token": bootstrap.organizer_token},
        )

    assert (response.status_code, response.json()["code"]) == (
        503,
        "TRIP_DRAFT_REVISION_UNAVAILABLE",
    )
    assert location.calls == 0
