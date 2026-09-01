from __future__ import annotations

from unicodedata import normalize
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
    required_meal_kinds,
)
from app.core.errors import AppError
from app.domain.collaboration import TripFlowKind
from app.domain.hard_conflicts import merged_constraints_for_revision
from app.domain.models import ApiResponse, GeoPoint, Place
from app.domain.recommendation import CandidateFactProvenance
from app.infrastructure.provider_fact_registry import SqliteProviderFactRegistry
from app.services.planning.models import CandidateEndpointFact
from app.services.recommendation import (
    ProviderFactPlaceSet,
    ProviderFactSetSummary,
    RecommendationOrchestrationRequest,
    RecommendationOrchestrationResult,
)


router = APIRouter(tags=["S2 可信候选推荐"])
PROVIDER_SEARCH_RADIUS_METERS = 25_000


def _normalized_place_identity(value: str) -> str:
    return " ".join(normalize("NFKC", value).strip().casefold().split())


def _mark_private_organizer_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "X-Organizer-Token"


def _provider_search_terms(
    must_visit: list[str],
    interests: list[str],
    *,
    include_dining: bool,
) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    prioritized = [
        *must_visit,
        *(["美食街", "餐厅"] if include_dining else []),
        *interests,
        "景点",
    ]
    for value in prioritized:
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


async def _provider_places_for_term(
    provider: object,
    *,
    city_resolution: object,
    center: GeoPoint,
    keywords: str,
    citywide: bool = False,
) -> list[Place]:
    """按搜索用途选择高德检索范围。

    普通兴趣词仍以已确认起点为中心做附近检索，保证推荐地点不会离出发地过远；
    硬性必去地点则使用全城关键词检索，因为硬约束不能仅因它位于起点 25 公里外
    就被候选阶段漏掉。两条路径都只接收 Provider 返回的真实地点，不自行造点。
    """

    city_context = city_resolution.cityContext
    place_types = ["050000"] if keywords.strip() == "餐厅" else []
    search_places = getattr(provider, "search_places", None)
    if citywide and callable(search_places):
        result = await search_places(
            city_context,
            keywords=keywords,
            types=place_types,
            page=1,
            page_size=25,
        )
        return result.places

    nearby_places = getattr(provider, "nearby_places", None)
    if callable(nearby_places):
        result = await nearby_places(
            city_context,
            center=center,
            radius_meters=PROVIDER_SEARCH_RADIUS_METERS,
            keywords=keywords,
            types=place_types,
            page=1,
            page_size=25,
        )
        return result.places

    result = await provider.search_places(
        city_context,
        keywords=keywords,
        types=place_types,
        page=1,
        page_size=25,
    )
    return result.places


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
    response: Response,
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
        _mark_private_organizer_response(response)
        return ApiResponse[ProviderFactSetSummary](data=snapshot.summary())


@router.get(
    "/api/v1/trips/{trip_id}/provider-fact-sets/{fact_set_id}/places",
    summary="恢复服务端签发的不可变地点事实",
    description=(
        "仅向具备组织者权限且协作仍就绪的 Trip 返回签发快照中的地点；"
        "浏览器不能提交或覆盖地点、价格、来源与 payloadDigest。"
    ),
)
async def get_provider_fact_set_places(
    trip_id: UUID,
    fact_set_id: str,
    request: Request,
    response: Response,
    provider_fact_digest: str = Query(alias="providerFactDigest"),
    registry: SqliteProviderFactRegistry = Depends(get_provider_fact_registry),
) -> ApiResponse[ProviderFactPlaceSet]:
    if not request.headers.get("X-Organizer-Token"):
        raise AppError(
            code="ORGANIZER_PERMISSION_REQUIRED",
            message="缺少组织者凭证",
            http_status=403,
        )
    access = build_planning_access(
        request,
        trip_id,
        PlanningOperation.PROVIDER_FACTS,
    )
    with request.app.state.collaboration_readiness_guard.operation(access) as permit:
        if (
            permit.flow_kind is not TripFlowKind.COLLABORATION_V2
            or permit.revision is None
        ):
            raise AppError(
                code="ORGANIZER_PERMISSION_REQUIRED",
                message="组织者权限不足",
                http_status=403,
            )
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
        issued_context = snapshot.draft.confirmed_trip_summary
        if (
            issued_context.get("collaborationRevision")
            != permit.revision.revision
            or issued_context.get("sourceDigest")
            != permit.revision.source_digest
        ):
            raise AppError(
                code="PROVIDER_FACT_READY_CONTEXT_STALE",
                message="FactRef 快照与当前已确认协作版本不一致",
                http_status=409,
            )
        _mark_private_organizer_response(response)
        return ApiResponse[ProviderFactPlaceSet](data=snapshot.place_set())


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
        parent_place_memory = (
            request.app.state.parent_trip_service.place_memory_for_child(trip_id)
        )
        if parent_place_memory:
            existing = {
                _normalized_place_identity(value) for value in avoid_places
            }
            memory_labels = [
                label
                for item in parent_place_memory
                for label in (item.place_id, item.place_name)
            ]
            parent_avoids: list[str] = []
            for value in memory_labels:
                normalized = _normalized_place_identity(value)
                if normalized in existing:
                    continue
                existing.add(normalized)
                parent_avoids.append(value)
            avoid_places.extend(parent_avoids)
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
        # 硬性必去标签使用全城精确搜索；兴趣和兜底“景点”仍使用起点附近搜索。
        # 这样既保证“天坛”等必去地点不会因搜索半径丢失，也避免普通推荐无限扩散。
        required_search_terms = {
            value.strip().casefold()
            for value in must_visit
            if value.strip()
        }
        meal_kinds = required_meal_kinds(trip)
        searched_dining_probe = not meal_kinds
        for keywords in _provider_search_terms(
            must_visit,
            interests,
            include_dining=bool(meal_kinds),
        ):
            provider_places.extend(await _provider_places_for_term(
                request.app.state.location_service,
                city_resolution=city,
                center=start_fact.location,
                keywords=keywords,
                citywide=keywords.strip().casefold() in required_search_terms,
            ))
            if keywords.strip() in {"美食街", "餐厅"}:
                searched_dining_probe = True
            if parent_place_memory:
                remembered_ids = {
                    _normalized_place_identity(item.place_id)
                    for item in parent_place_memory
                }
                remembered_names = {
                    _normalized_place_identity(item.place_name)
                    for item in parent_place_memory
                }
                provider_places = [
                    place for place in provider_places
                    if (
                        _normalized_place_identity(place.placeId)
                        not in remembered_ids
                        and _normalized_place_identity(place.name)
                        not in remembered_names
                    )
                ]
            try:
                TrustedRecommendationService.pre_filter_provider_places(
                    provider_places,
                    trip=trip,
                )
            except RecommendationOrchestrationError as error:
                if error.code not in {
                    "HARD_MUST_VISIT_FACT_MISSING",
                    "INSUFFICIENT_TRUSTED_PROVIDER_CANDIDATES",
                    "INSUFFICIENT_TRUSTED_DINING_CANDIDATES",
                }:
                    raise AppError(
                        code=error.code,
                        message=error.message,
                        http_status=error.http_status,
                    ) from error
            else:
                if not searched_dining_probe:
                    continue
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
        try:
            bundle = await orchestration.recommend_preview_from_provider_facts(
                trip_id=trip_id,
                trip=trip,
                facts=issuance.facts,
                interests=interests,
                must_visit=must_visit,
                avoid_places=avoid_places,
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
                    "parent_place_memory": list(parent_place_memory),
                }
            )
        )


@router.get("/api/v2/trips/{trip_id}/planning-trip")
async def collaboration_planning_trip(
    trip_id: UUID,
    request: Request,
    response: Response,
) -> ApiResponse:
    """Return the server-materialized Trip for a READY multi-member flow.

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
        shared = revision.understanding.trip
        city = await request.app.state.location_service.resolve_city(
            shared.city_name or ""
        )
        trip = request.app.state.collaboration_planning_bridge.materialize(
            revision,
            city.cityContext,
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Organizer-Token"
        return ApiResponse(data=trip)


__all__ = ["router"]
