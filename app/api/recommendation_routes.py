from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.planning_access import build_planning_access
from app.application.collaboration_ports import PlanningOperation
from app.application.recommendation_service import (
    MemberPreference,
    ProviderFactRestoreError,
    RecommendationOrchestrationError,
    RecommendationOrchestrationService,
    TrustedRecommendationService,
    project_collaboration_recommendation_trip,
)
from app.core.errors import AppError
from app.domain.hard_conflicts import merged_constraints_for_revision
from app.domain.models import ApiResponse
from app.domain.recommendation import CandidateFactProvenance
from app.infrastructure.provider_fact_registry import SqliteProviderFactRegistry
from app.services.planning.models import CandidateEndpointFact
from app.services.recommendation import (
    ProviderFactSetSummary,
    RecommendationOrchestrationRequest,
    RecommendationOrchestrationResult,
)


router = APIRouter(tags=["S2 可信候选推荐"])


def _provider_search_terms(
    must_visit: list[str],
    interests: list[str],
) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in [*must_visit, *interests, "景点"]:
        normalized = value.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(value.strip())
        if len(terms) == 8:
            break
    return tuple(terms) or ("景点",)


async def _provider_endpoint_fact(
    provider: object,
    *,
    city_resolution: object,
    address: str,
) -> CandidateEndpointFact:
    """Resolve an endpoint while retaining compatibility with legacy adapters.

    Production adapters expose ``forward_geocode``.  Older deterministic test
    adapters predate that method, so their already Provider-backed city-center
    fact remains a valid conservative endpoint instead of accepting coordinates
    from the browser or model.
    """

    city_context = city_resolution.cityContext
    forward_geocode = getattr(provider, "forward_geocode", None)
    if callable(forward_geocode):
        endpoint = await forward_geocode(city_context, address=address)
        return CandidateEndpointFact(
            location_text=address or endpoint.formattedAddress,
            city_code=endpoint.cityCode,
            location=endpoint.location,
            provenance=endpoint.provenance,
        )
    return CandidateEndpointFact(
        location_text=address or city_context.city_name,
        city_code=city_context.city_code,
        location=city_context.center,
        provenance=city_resolution.provenance,
    )


def get_recommendation_service(
    request: Request,
) -> RecommendationOrchestrationService:
    service = request.app.state.recommendation_service
    if not isinstance(service, RecommendationOrchestrationService) or (
        service.readiness_guard is not request.app.state.collaboration_readiness_guard
    ):
        raise AppError(
            code="RECOMMENDATION_SERVICE_UNAVAILABLE",
            message="推荐编排依赖尚未配置",
            http_status=503,
            retryable=True,
        )
    return service


def get_provider_fact_registry(request: Request) -> SqliteProviderFactRegistry:
    registry = request.app.state.provider_fact_registry
    if not isinstance(registry, SqliteProviderFactRegistry):
        raise AppError(
            code="PROVIDER_FACT_REGISTRY_UNAVAILABLE",
            message="FactRef 注册表尚未配置",
            http_status=503,
            retryable=True,
        )
    return registry


@router.get(
    "/api/v1/trips/{trip_id}/provider-fact-sets/{fact_set_id}",
    summary="核验服务端签发的 FactRef 摘要",
    description=(
        "只按 factSetId/digest 恢复服务端快照并返回来源摘要；不接受客户端"
        "内嵌地点、路线、价格或 Provenance。"
    ),
)
async def get_provider_fact_set_summary(
    trip_id: UUID,
    fact_set_id: str,
    request: Request,
    provider_fact_digest: str = Query(alias="providerFactDigest"),
    registry: SqliteProviderFactRegistry = Depends(get_provider_fact_registry),
) -> ApiResponse[ProviderFactSetSummary]:
    access = build_planning_access(
        request,
        trip_id,
        PlanningOperation.PROVIDER_FACTS,
    )
    with request.app.state.collaboration_readiness_guard.operation(access):
        try:
            snapshot = registry.restore_snapshot(trip_id, fact_set_id)
        except ProviderFactRestoreError as error:
            raise AppError(
                code=error.code,
                message=error.message,
                http_status=409,
            ) from error
        if snapshot.provider_fact_digest != provider_fact_digest:
            raise AppError(
                code="PROVIDER_FACT_DIGEST_MISMATCH",
                message="请求摘要与服务端签发的 FactRef 摘要不一致",
                http_status=409,
            )
        return ApiResponse[ProviderFactSetSummary](data=snapshot.summary())


@router.post(
    "/api/v1/trips/{trip_id}/recommendations",
    summary="从服务端 FactRef 生成唯一公平推荐",
)
async def recommend_unique_plan(
    trip_id: UUID,
    command: RecommendationOrchestrationRequest,
    http_request: Request,
    service: RecommendationOrchestrationService = Depends(
        get_recommendation_service
    ),
) -> ApiResponse[RecommendationOrchestrationResult]:
    access = build_planning_access(
        http_request, trip_id, PlanningOperation.RECOMMENDATION
    )
    try:
        result = await service.recommend(
            trip_id=trip_id,
            request=command,
            access=access,
        )
    except RecommendationOrchestrationError as error:
        raise AppError(
            code=error.code,
            message=error.message,
            http_status=error.http_status,
        ) from error
    return ApiResponse[RecommendationOrchestrationResult](data=result)


@router.get("/api/v2/trips/{trip_id}/recommendations")
async def recommendations(trip_id: UUID, request: Request) -> ApiResponse:
    """Build recommendations only from the guarded current revision."""
    organizer_token = request.headers.get("X-Organizer-Token")
    access = build_planning_access(
        request, trip_id, PlanningOperation.RECOMMENDATION
    )
    guard = request.app.state.collaboration_readiness_guard
    collaboration = request.app.state.collaboration_service
    with guard.operation(access):
        revision = collaboration.ready_revision(trip_id, organizer_token)
        # Resolve the shared v1/v2 orchestrator only after the authoritative
        # collaboration check, so an unavailable T002 revision still stops all
        # Provider/model calls with its original error.
        orchestration = get_recommendation_service(request)
        shared = revision.understanding.trip
        city = await request.app.state.location_service.resolve_city(
            shared.city_name or ""
        )
        trip = project_collaboration_recommendation_trip(
            revision, city.cityContext
        )
        members = revision.understanding.participants
        interests = [interest for item in members for interest in item.interests]
        must_visit = [place for item in members for place in item.must_visit]
        avoid_places = [place for item in members for place in item.avoid_places]
        start_fact = await _provider_endpoint_fact(
            request.app.state.location_service,
            city_resolution=city,
            address=shared.start_location_text or "",
        )
        end_fact = await _provider_endpoint_fact(
            request.app.state.location_service,
            city_resolution=city,
            address=shared.end_location_text or "",
        )
        provider_places = []
        for keywords in _provider_search_terms(must_visit, interests):
            result = await request.app.state.location_service.search_places(
                city.cityContext,
                keywords=keywords,
                types=[],
                page=1,
                page_size=25,
            )
            provider_places.extend(result.places)
            try:
                TrustedRecommendationService.pre_filter_provider_places(
                    provider_places,
                    trip=trip,
                )
            except RecommendationOrchestrationError as error:
                if error.code not in {
                    "HARD_MUST_VISIT_FACT_MISSING",
                    "INSUFFICIENT_TRUSTED_PROVIDER_CANDIDATES",
                }:
                    raise AppError(
                        code=error.code,
                        message=error.message,
                        http_status=error.http_status,
                    ) from error
            else:
                break
        try:
            issuance = orchestration.issue_provider_candidate_facts(
                trip=trip,
                start_location=start_fact,
                end_location=end_fact,
                confirmed_constraints=merged_constraints_for_revision(
                    revision
                ).constraints,
                confirmed_trip_summary={
                    "cityCode": city.cityContext.city_code,
                    "participantCount": len(members),
                    "collaborationRevision": revision.revision,
                    "sourceDigest": revision.source_digest,
                },
                provider_places=provider_places,
            )
        except RecommendationOrchestrationError as error:
            raise AppError(
                code=error.code,
                message=error.message,
                http_status=error.http_status,
            ) from error
        member_preferences = [
            MemberPreference(
                participant_id=str(revision.member_bindings[item.member_key]),
                interests=tuple(item.interests),
                must_visit=tuple(item.must_visit),
            )
            for item in members
        ]
        care_need_labels = [
            label
            for item in members
            if item.care_draft is not None
            for label in (
                item.care_draft.assistance_type_hint,
                "避开楼梯" if item.care_draft.avoid_stairs else None,
            )
            if label is not None
        ]
        try:
            bundle = await orchestration.recommend_preview_from_provider_facts(
                trip_id=trip_id,
                facts=issuance.facts,
                city_code=city.cityContext.city_code,
                interests=interests,
                must_visit=must_visit,
                avoid_places=avoid_places,
                care_need_labels=care_need_labels,
                members=member_preferences,
            )
        except RecommendationOrchestrationError as error:
            raise AppError(
                code=error.code,
                message=error.message,
                http_status=error.http_status,
            ) from error
        provenance = [
            CandidateFactProvenance(
                fact_ref_id=item.fact_ref_id,
                provider_object_id=item.provider_object_id,
                source_status=item.source_status,
                fetched_at=item.fetched_at,
                is_stale=item.is_stale,
            )
            for item in issuance.summary.references
            if item.kind == "PLACE"
        ]
        return ApiResponse(
            data=bundle.model_copy(
                update={
                    "fact_set_id": issuance.summary.fact_set_id,
                    "provider_fact_digest": (
                        issuance.summary.provider_fact_digest
                    ),
                    "provenance": provenance,
                }
            )
        )


@router.get("/api/v2/trips/{trip_id}/planning-trip")
async def collaboration_planning_trip(
    trip_id: UUID,
    request: Request,
    response: Response,
) -> ApiResponse:
    """Return the server-materialized Trip for the READY single flow.

    The browser must not rebuild or reconfirm a collaboration-owned Trip.  The
    same readiness lease used by recommendation/planning binds this response to
    the current confirmed revision, while the bridge keeps persistence and
    constraint confirmation deterministic and idempotent.
    """

    organizer_token = request.headers.get("X-Organizer-Token")
    access = build_planning_access(
        request,
        trip_id,
        PlanningOperation.GENERATE_V1,
    )
    guard = request.app.state.collaboration_readiness_guard
    collaboration = request.app.state.collaboration_service
    with guard.operation(access):
        revision = collaboration.ready_revision(trip_id, organizer_token)
        if len(revision.understanding.participants) != 1:
            raise AppError(
                code="COLLABORATION_SINGLE_PLANNING_UNAVAILABLE",
                message="多人协作 Trip 的规划投影由 S2-T032 提供",
                http_status=409,
                retryable=False,
            )
        shared = revision.understanding.trip
        city = await request.app.state.location_service.resolve_city(
            shared.city_name or ""
        )
        trip = request.app.state.collaboration_planning_bridge.materialize(
            revision,
            city.cityContext,
        )
        if trip is None:
            raise AppError(
                code="COLLABORATION_SINGLE_PLANNING_UNAVAILABLE",
                message="当前协作 Trip 无法投影为单人规划输入",
                http_status=409,
                retryable=False,
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Organizer-Token"
        return ApiResponse(data=trip)


__all__ = ["router"]
