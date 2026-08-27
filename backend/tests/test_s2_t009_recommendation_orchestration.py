from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from app.application.recommendation_service import (
    CandidateProposalGatewayError,
    ProviderFactRestoreError,
    RawCandidateProposal,
    RecommendationOrchestrationError,
    RecommendationOrchestrationService,
    RouteCandidateBuildError,
)
from app.core.config import Settings
from app.domain.models import SourceStatus
from app.main import create_app
from app.schemas.trip import Participant, Preference, PreferenceType, TripMode
from app.services.planning import (
    CandidatePlanRejected,
    CandidatePlanRequest,
    DeterministicCandidatePlanner,
)
from app.services.recommendation import (
    BuiltRouteCandidate,
    ProviderCandidateFactView,
    ProviderCandidateSelectionProposal,
    ProviderFactBundle,
    RecommendationOrchestrationRequest,
)


FIXTURE = Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
DIGEST = "c" * 64
FACT_SET_ID = "facts-beijing-group-v1"


def _base_request() -> CandidatePlanRequest:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["request"]
    return CandidatePlanRequest.model_validate_json(
        json.dumps(raw, ensure_ascii=False),
        strict=True,
    )


def _group_request() -> CandidatePlanRequest:
    base = _base_request()
    first = base.trip.participants[0].model_copy(
        update={
            "preferences": [
                Preference(
                    type=PreferenceType.INTEREST,
                    value="MUSEUM",
                    weight=5,
                    is_hard=False,
                ),
                Preference(
                    type=PreferenceType.INTEREST,
                    value="PARK",
                    weight=4,
                    is_hard=False,
                ),
            ]
        }
    )
    second = Participant(
        participant_id=UUID("33333333-3333-4333-8333-333333333333"),
        nickname="成员乙",
        budget_cap_cents=35_000,
        preferences=[
            Preference(
                type=PreferenceType.INTEREST,
                value="FOOD",
                weight=5,
                is_hard=False,
            ),
            Preference(
                type=PreferenceType.INTEREST,
                value="SHOPPING",
                weight=4,
                is_hard=False,
            ),
        ],
        assistance_profile=None,
    )
    trip = base.trip.model_copy(
        update={"mode": TripMode.GROUP, "participants": [first, second]}
    )
    candidate = base.model_copy(update={"trip": trip})
    return CandidatePlanRequest.model_validate_json(
        candidate.model_dump_json(by_alias=True),
        strict=True,
    )


def _fact_bundle() -> ProviderFactBundle:
    request = _group_request()
    task_place_ids = [item.place.placeId for item in request.task_facts]
    provider_ids = [*task_place_ids, "poi-extra-5", "poi-extra-6"]
    labels = ["MUSEUM", "FOOD", "PARK", "SHOPPING", "ART", "NATURE"]
    facts = tuple(
        ProviderCandidateFactView(
            place_fact_id=f"fact-{index}",
            provider_place_id=provider_id,
            name=label,
            category="TEST",
            source_status=SourceStatus.ONLINE,
            known_attributes={"cityCode": request.trip.city_context.city_code},
        )
        for index, (provider_id, label) in enumerate(
            zip(provider_ids, labels),
            start=1,
        )
    )
    return ProviderFactBundle(
        fact_set_id=FACT_SET_ID,
        provider_fact_digest=DIGEST,
        trip=request.trip,
        start_location=request.start_location,
        end_location=request.end_location,
        confirmed_constraints=request.confirmed_constraints,
        confirmed_trip_summary={
            "cityCode": request.trip.city_context.city_code,
            "participantCount": len(request.trip.participants),
        },
        candidate_facts=facts,
    )


class StubFactRegistry:
    def __init__(self, facts: ProviderFactBundle) -> None:
        self.facts = facts
        self.calls: list[tuple[UUID, str]] = []
        self.error: ProviderFactRestoreError | None = None

    def restore(self, trip_id: UUID, fact_set_id: str) -> ProviderFactBundle:
        self.calls.append((trip_id, fact_set_id))
        if self.error is not None:
            raise self.error
        return self.facts


class StubProposalGateway:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        digest: str = DIGEST,
        error: CandidateProposalGatewayError | None = None,
    ) -> None:
        self.payload = payload or _proposal_payload()
        self.digest = digest
        self.error = error
        self.requests = []

    async def propose(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return RawCandidateProposal(
            payload=json.dumps(self.payload, ensure_ascii=False).encode("utf-8"),
            provider_fact_digest=self.digest,
        )


class StubRouteBuilder:
    LABELS = {
        "fact-1": "MUSEUM",
        "fact-2": "FOOD",
        "fact-3": "PARK",
        "fact-4": "SHOPPING",
    }

    def __init__(self) -> None:
        self.orders: list[tuple[str, ...]] = []

    async def build(
        self,
        facts: ProviderFactBundle,
        selected_place_fact_ids: tuple[str, ...],
    ) -> BuiltRouteCandidate:
        self.orders.append(selected_place_fact_ids)
        if any(item not in self.LABELS for item in selected_place_fact_ids):
            raise RouteCandidateBuildError("stub has no signed route for this order")

        payload = _group_request().model_dump(mode="python")
        tasks = list(payload["task_facts"])
        labels = [self.LABELS[item] for item in selected_place_fact_ids]
        labels.extend("OTHER" for _ in range(len(tasks) - len(labels)))
        for task, label in zip(tasks, labels):
            task["title"] = label
            task["category"] = label
        tasks[0]["note"] = "selected-order:" + ",".join(selected_place_fact_ids)
        payload["task_facts"] = tuple(tasks)
        request = CandidatePlanRequest.model_validate(payload)
        return BuiltRouteCandidate(
            request=request,
            selected_place_fact_ids=selected_place_fact_ids,
            detour_meters=sum(
                (index + 1) * int(fact_id.rsplit("-", 1)[1]) * 100
                for index, fact_id in enumerate(selected_place_fact_ids)
            ),
        )


def _proposal_payload(
    selected: list[str] | None = None,
    *,
    rationale: str = "兼顾两位成员的兴趣，并交由程序核验路线与公平性。",
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "selectedPlaceFactIds": selected or ["fact-1", "fact-2", "fact-3"],
        "selectionRationale": rationale,
        "riskNotes": ["价格与路线以服务端事实为准。"],
    }


def _service(
    *,
    gateway: StubProposalGateway | None = None,
) -> tuple[
    RecommendationOrchestrationService,
    StubFactRegistry,
    StubProposalGateway,
    StubRouteBuilder,
]:
    facts = _fact_bundle()
    registry = StubFactRegistry(facts)
    resolved_gateway = gateway or StubProposalGateway()
    builder = StubRouteBuilder()
    service = RecommendationOrchestrationService(
        fact_registry=registry,
        proposal_gateway=resolved_gateway,
        route_builder=builder,
    )
    return service, registry, resolved_gateway, builder


def _command() -> RecommendationOrchestrationRequest:
    return RecommendationOrchestrationRequest(
        fact_set_id=FACT_SET_ID,
        provider_fact_digest=DIGEST,
    )


@pytest.mark.asyncio
async def test_valid_qwen_proposal_builds_routes_and_returns_one_fair_plan() -> None:
    service, registry, gateway, builder = _service()
    trip_id = registry.facts.trip.trip_id

    result = await service.recommend(trip_id=trip_id, request=_command())

    assert result.strategy == "LLM_PROPOSAL"
    assert result.fallback_reason is None
    assert result.provider_fact_digest == DIGEST
    assert len(result.decision.selected_plan.tasks) == 4
    assert result.decision.selected_plan.candidate_id in (
        result.decision.evaluated_candidate_ids
    )
    assert len(result.decision.selected_evaluation.participant_scores) == 2
    assert len(gateway.requests) == 1
    assert len(gateway.requests[0].candidate_facts) == 6
    assert gateway.requests[0].allowed_task_count == (3, 4)
    assert builder.orders[0] == ("fact-1", "fact-2", "fact-3")


@pytest.mark.parametrize(
    ("gateway", "expected_reason"),
    [
        (
            StubProposalGateway(
                error=CandidateProposalGatewayError("LLM_TIMEOUT", "timeout")
            ),
            "LLM_TIMEOUT",
        ),
        (StubProposalGateway(digest="d" * 64), "LLM_DIGEST_MISMATCH"),
        (
            StubProposalGateway(_proposal_payload(["fact-1", "fact-outside"])),
            "LLM_ALLOWLIST_VIOLATION",
        ),
        (
            StubProposalGateway(_proposal_payload(["fact-1", "fact-1"])),
            "LLM_FORMAT_INVALID",
        ),
    ],
)
@pytest.mark.asyncio
async def test_model_failures_use_deterministic_enumeration(
    gateway: StubProposalGateway,
    expected_reason: str,
) -> None:
    service, registry, _, builder = _service(gateway=gateway)

    result = await service.recommend(
        trip_id=registry.facts.trip.trip_id,
        request=_command(),
    )

    assert result.strategy == "DETERMINISTIC_FALLBACK"
    assert result.fallback_reason == expected_reason
    assert result.selected_place_fact_ids == ("fact-2", "fact-4")
    assert builder.orders[0] == ("fact-1", "fact-2")
    assert len(result.decision.selected_plan.tasks) == 4


@pytest.mark.asyncio
async def test_forbidden_model_cost_field_is_strictly_rejected_and_falls_back() -> None:
    payload = _proposal_payload()
    payload["cost"] = 1
    gateway = StubProposalGateway(payload)
    service, registry, _, _ = _service(gateway=gateway)

    result = await service.recommend(
        trip_id=registry.facts.trip.trip_id,
        request=_command(),
    )

    assert result.strategy == "DETERMINISTIC_FALLBACK"
    assert result.fallback_reason == "LLM_FORMAT_INVALID"


@pytest.mark.asyncio
async def test_allowlisted_but_unroutable_model_proposal_falls_back() -> None:
    gateway = StubProposalGateway(
        _proposal_payload(["fact-5", "fact-6"])
    )
    service, registry, _, builder = _service(gateway=gateway)

    result = await service.recommend(
        trip_id=registry.facts.trip.trip_id,
        request=_command(),
    )

    assert result.strategy == "DETERMINISTIC_FALLBACK"
    assert result.fallback_reason == "LLM_PROPOSAL_UNUSABLE"
    assert builder.orders[0] == ("fact-5", "fact-6")
    assert ("fact-1", "fact-2") in builder.orders


@pytest.mark.asyncio
async def test_repeated_same_input_returns_identical_unique_decision() -> None:
    gateway = StubProposalGateway(
        error=CandidateProposalGatewayError("LLM_UNAVAILABLE", "disabled")
    )
    service, registry, _, _ = _service(gateway=gateway)

    first = await service.recommend(
        trip_id=registry.facts.trip.trip_id,
        request=_command(),
    )
    second = await service.recommend(
        trip_id=registry.facts.trip.trip_id,
        request=_command(),
    )

    assert first == second
    assert len(first.decision.selected_plan.tasks) in {3, 4}


@pytest.mark.asyncio
async def test_same_input_and_different_model_wording_cannot_change_winner() -> None:
    first_gateway = StubProposalGateway(
        _proposal_payload(rationale="措辞甲不会影响程序排序。")
    )
    second_gateway = StubProposalGateway(
        _proposal_payload(rationale="完全不同的措辞乙也不会影响程序排序。")
    )
    first_service, first_registry, _, _ = _service(gateway=first_gateway)
    second_service, second_registry, _, _ = _service(gateway=second_gateway)

    first = await first_service.recommend(
        trip_id=first_registry.facts.trip.trip_id,
        request=_command(),
    )
    second = await second_service.recommend(
        trip_id=second_registry.facts.trip.trip_id,
        request=_command(),
    )

    assert first.decision.selected_plan.candidate_id == (
        second.decision.selected_plan.candidate_id
    )
    assert first.selected_place_fact_ids == second.selected_place_fact_ids
    assert first.selection_rationale != second.selection_rationale


@pytest.mark.asyncio
async def test_tampered_client_digest_stops_before_model_and_route_calls() -> None:
    service, registry, gateway, builder = _service()
    tampered = RecommendationOrchestrationRequest(
        fact_set_id=FACT_SET_ID,
        provider_fact_digest="e" * 64,
    )

    with pytest.raises(RecommendationOrchestrationError) as captured:
        await service.recommend(
            trip_id=registry.facts.trip.trip_id,
            request=tampered,
        )

    assert captured.value.code == "PROVIDER_FACT_DIGEST_MISMATCH"
    assert gateway.requests == []
    assert builder.orders == []


def test_public_request_and_model_contract_forbid_client_scores_and_facts() -> None:
    request_properties = RecommendationOrchestrationRequest.model_json_schema()[
        "properties"
    ]
    proposal_properties = ProviderCandidateSelectionProposal.model_json_schema()[
        "properties"
    ]

    for forbidden in (
        "satisfactionLoss",
        "satisfaction_loss",
        "route",
        "cost",
        "score",
        "PASS",
    ):
        assert forbidden not in request_properties
        assert forbidden not in proposal_properties


def test_unknown_provider_fact_cannot_enter_orchestration() -> None:
    payload = _fact_bundle().model_dump(mode="python")
    facts = list(payload["candidate_facts"])
    facts[0]["source_status"] = SourceStatus.UNKNOWN
    payload["candidate_facts"] = tuple(facts)

    with pytest.raises(ValidationError):
        ProviderFactBundle.model_validate(payload)


def test_group_planner_deduplicates_identical_confirmed_care_constraints() -> None:
    request = _group_request()
    first_profile = request.trip.participants[0].assistance_profile
    second = request.trip.participants[1].model_copy(
        update={"assistance_profile": first_profile}
    )
    trip = request.trip.model_copy(
        update={"participants": [request.trip.participants[0], second]}
    )
    group_request = CandidatePlanRequest.model_validate_json(
        request.model_copy(update={"trip": trip}).model_dump_json(by_alias=True),
        strict=True,
    )

    plan = DeterministicCandidatePlanner().generate(group_request)

    assert len(group_request.confirmed_constraints) == 6
    assert plan.metrics.validation_status == "PASS"


def test_group_planner_uses_the_lowest_member_budget_cap() -> None:
    request = _group_request()
    second = request.trip.participants[1].model_copy(
        update={"budget_cap_cents": 1_000}
    )
    trip = request.trip.model_copy(
        update={"participants": [request.trip.participants[0], second]}
    )
    group_request = CandidatePlanRequest.model_validate_json(
        request.model_copy(update={"trip": trip}).model_dump_json(by_alias=True),
        strict=True,
    )

    with pytest.raises(CandidatePlanRejected) as captured:
        DeterministicCandidatePlanner().generate(group_request)

    assert captured.value.results[-1].rule_id == "PLAN.BUDGET.KNOWN_SUBTOTAL"


@pytest.mark.asyncio
async def test_http_interface_rejects_client_satisfaction_loss(tmp_path: Path) -> None:
    service, registry, gateway, _ = _service()
    settings = Settings(
        _env_file=None,
        plan_version_db_path=tmp_path / "plans.sqlite3",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
    )
    app = create_app(
        settings=settings,
        service=object(),  # type: ignore[arg-type]
        recommendation_service=service,
    )
    transport = httpx.ASGITransport(app=app)
    body = _command().model_dump(mode="json", by_alias=True)
    body["satisfactionLoss"] = 0

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/trips/{registry.facts.trip.trip_id}/recommendations",
            json=body,
        )

    assert response.status_code == 422
    assert response.json()["code"] == "TRIP_SCHEMA_INVALID"
    assert gateway.requests == []


def test_openapi_exposes_t009_route_without_candidate_or_score_input(
    tmp_path: Path,
) -> None:
    service, _, _, _ = _service()
    app = create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=tmp_path / "plans.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
        recommendation_service=service,
    )

    operation = app.openapi()["paths"][
        "/api/v1/trips/{trip_id}/recommendations"
    ]["post"]
    assert operation["summary"] == "从服务端 FactRef 生成唯一公平推荐"
    assert "satisfactionLoss" not in json.dumps(operation, ensure_ascii=False)
    request_ref = operation["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    response_ref = operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert request_ref.endswith("RecommendationOrchestrationRequest")
    assert "RecommendationOrchestrationResult" in response_ref
