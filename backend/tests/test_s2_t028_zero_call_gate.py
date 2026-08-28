from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.application.collaboration_ports import PlanningAccess, PlanningOperation
from app.application.planning_boundary_service import PlanningBoundaryService
from app.application.recommendation_service import RecommendationOrchestrationService
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import CollaborationStatus
from app.infrastructure.provider_fact_registry import SqliteProviderFactRegistry
from app.main import create_app
from app.services.replanning import DeterministicRetainedSuffixPlanner


TRIP_ID = UUID("28282828-2828-4828-8828-282828282828")
ORGANIZER_TOKEN = "s2-t028-organizer-token"
NON_READY_STATUSES = (
    CollaborationStatus.DRAFT_CONVERSATION,
    CollaborationStatus.INVITING,
    CollaborationStatus.COLLECTING_MEMBERS,
    CollaborationStatus.CONFLICT_REVIEW,
)
CITY_CONTEXT = {
    "countryCode": "CN",
    "cityCode": "110000",
    "cityName": "北京",
    "center": {"longitude": 116.407387, "latitude": 39.904179},
    "providerConfig": {"provider": "AMAP", "coordinateSystem": "GCJ02"},
}


class StatusRejectingReadinessGuard:
    def __init__(self, status: CollaborationStatus) -> None:
        self.status = status
        self.operations: list[PlanningOperation] = []

    @contextmanager
    def operation(self, access: PlanningAccess):
        self.operations.append(access.operation)
        raise AppError(
            code="COLLABORATION_NOT_READY",
            message=(
                f"协作状态 {self.status.value} 非 READY_TO_PLAN，"
                "已拒绝 Provider、推荐或规划调用"
            ),
            http_status=409,
            retryable=False,
        )
        yield


class CountingLocationService:
    def __init__(self) -> None:
        self.calls = 0

    async def suggestions(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("non-ready collaboration must not call Provider")


class CountingProviderFactRegistry(SqliteProviderFactRegistry):
    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.restore_calls = 0

    def restore_snapshot(self, trip_id: UUID, fact_set_id: str):
        self.restore_calls += 1
        raise AssertionError("non-ready collaboration must not restore Provider facts")


class CountingFactRegistry:
    def __init__(self) -> None:
        self.calls = 0

    def restore(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("non-ready collaboration must not restore FactRef")


class CountingProposalGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def propose(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("non-ready collaboration must not call the LLM")


class CountingRouteBuilder:
    def __init__(self) -> None:
        self.calls = 0

    async def build(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("non-ready collaboration must not build routes")


class CountingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("non-ready collaboration must not rank candidates")


class CountingPlanningPort:
    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, name: str):
        def fail(*args, **kwargs):
            self.calls += 1
            raise AssertionError(
                f"non-ready collaboration must not call planning port {name}"
            )

        return fail


def _candidate_request() -> dict[str, object]:
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "planning"
        / "golden_candidate_plan.json"
    )
    payload = deepcopy(json.loads(fixture_path.read_text(encoding="utf-8"))["request"])
    payload["trip"]["tripId"] = str(TRIP_ID)
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", NON_READY_STATUSES, ids=lambda item: item.value)
async def test_non_ready_states_reject_with_zero_provider_recommendation_and_planning_calls(
    status: CollaborationStatus,
    tmp_path: Path,
) -> None:
    guard = StatusRejectingReadinessGuard(status)
    location = CountingLocationService()
    provider_facts = CountingProviderFactRegistry(tmp_path / "provider-facts.sqlite3")
    fact_registry = CountingFactRegistry()
    proposal_gateway = CountingProposalGateway()
    route_builder = CountingRouteBuilder()
    planner = CountingPlanner()
    plan_store = CountingPlanningPort()
    workflow = CountingPlanningPort()
    trust = CountingPlanningPort()
    recommendation = RecommendationOrchestrationService(
        fact_registry=fact_registry,
        proposal_gateway=proposal_gateway,
        route_builder=route_builder,
        planner=planner,
        readiness_guard=guard,
    )
    planning = PlanningBoundaryService(
        plan_service=plan_store,  # type: ignore[arg-type]
        workflow_service=workflow,  # type: ignore[arg-type]
        trust_repository=trust,  # type: ignore[arg-type]
        suffix_planner=DeterministicRetainedSuffixPlanner(),
        readiness_guard=guard,
    )
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
            bailian_request_timeout_seconds=10,
            bailian_candidate_timeout_seconds=10,
        ),
        service=location,  # type: ignore[arg-type]
        planning_boundary_service=planning,
        recommendation_service=recommendation,
        provider_fact_registry=provider_facts,
        collaboration_readiness_guard=guard,
    )
    headers = {
        "X-Organizer-Token": ORGANIZER_TOKEN,
        "Idempotency-Key": f"s2-t028-{status.value.lower()}",
    }
    requests = (
        (
            "POST",
            "/api/v1/places/suggestions",
            {
                "schemaVersion": "1.0",
                "tripId": str(TRIP_ID),
                "cityContext": CITY_CONTEXT,
                "keywords": "博物馆",
            },
        ),
        (
            "GET",
            f"/api/v1/trips/{TRIP_ID}/provider-fact-sets/facts-t028"
            f"?providerFactDigest={'a' * 64}",
            None,
        ),
        (
            "POST",
            f"/api/v1/trips/{TRIP_ID}/recommendations",
            {"factSetId": "facts-t028", "providerFactDigest": "a" * 64},
        ),
        (
            "POST",
            f"/api/v1/trips/{TRIP_ID}/plan-versions/generate",
            _candidate_request(),
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        responses = [
            await client.request(method, path, headers=headers, json=payload)
            for method, path, payload in requests
        ]

    assert [response.status_code for response in responses] == [409] * 4
    assert [response.json()["code"] for response in responses] == [
        "COLLABORATION_NOT_READY"
    ] * 4
    assert guard.operations == [
        PlanningOperation.PROVIDER_FACTS,
        PlanningOperation.PROVIDER_FACTS,
        PlanningOperation.RECOMMENDATION,
        PlanningOperation.GENERATE_V1,
    ]
    assert location.calls == 0
    assert provider_facts.restore_calls == 0
    assert (
        fact_registry.calls,
        proposal_gateway.calls,
        route_builder.calls,
        planner.calls,
    ) == (0, 0, 0, 0)
    assert (plan_store.calls, workflow.calls, trust.calls) == (0, 0, 0)
