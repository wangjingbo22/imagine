from fastapi import APIRouter, Depends, Request

from app.application.amap_service import AmapLocationService
from app.application.collaboration_ports import PlanningOperation
from app.api.planning_access import build_planning_access
from app.domain.models import (
    ApiResponse,
    CityResolveRequest,
    ForwardGeocodingRequest,
    NearbySearchRequest,
    PlaceDetailRequest,
    PlaceSearchRequest,
    ReverseGeocodingRequest,
    RoutePlanRequest,
    SuggestionRequest,
)


router = APIRouter(prefix="/api/v1", tags=["城市地点、路线与可信来源"])


def get_location_service(request: Request) -> AmapLocationService:
    return request.app.state.location_service


@router.get("/health", summary="服务健康检查", description="确认本地接口服务是否正常运行。")
async def health(request: Request) -> ApiResponse[dict[str, str]]:
    settings = request.app.state.settings
    return ApiResponse(
        data={
            "status": "UP",
            "buildSha": settings.build_sha or "unavailable",
            "naturalLanguageParser": request.app.state.natural_language_parser,
            "replanDifferenceExplainer": (
                request.app.state.replan_difference_explainer
            ),
        }
    )


@router.post("/cities/resolve", summary="解析目标城市", description="根据国内城市名称解析城市编码和中心坐标。")
async def resolve_city(
    request: CityResolveRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.resolve_city(request.city_name)
    return ApiResponse(data=result)


@router.post("/places/suggestions", summary="获取地点输入提示", description="在指定城市范围内获取地点关键词联想。")
async def suggestions(
    command: SuggestionRequest,
    http_request: Request,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    access = build_planning_access(
        http_request, command.trip_id, PlanningOperation.PROVIDER_FACTS
    )
    with http_request.app.state.collaboration_readiness_guard.operation(access):
        result = await service.suggestions(
            command.city_context,
            keywords=command.keywords,
            types=command.types,
            limit=command.limit,
        )
    return ApiResponse(data=result)


@router.post("/places/search", summary="搜索城市地点", description="搜索同城地点并返回来源、时间和价格可信状态。")
async def search_places(
    command: PlaceSearchRequest,
    http_request: Request,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    access = build_planning_access(
        http_request, command.trip_id, PlanningOperation.PROVIDER_FACTS
    )
    with http_request.app.state.collaboration_readiness_guard.operation(access):
        result = await service.search_places(
            command.city_context,
            keywords=command.keywords,
            types=command.types,
            page=command.page,
            page_size=command.page_size,
        )
    return ApiResponse(data=result)


@router.post("/places/nearby", summary="搜索附近地点", description="以指定坐标为中心搜索同城地点。")
async def nearby_places(
    command: NearbySearchRequest,
    http_request: Request,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    access = build_planning_access(
        http_request, command.trip_id, PlanningOperation.PROVIDER_FACTS
    )
    with http_request.app.state.collaboration_readiness_guard.operation(access):
        result = await service.nearby_places(
            command.city_context,
            center=command.center,
            radius_meters=command.radius_meters,
            keywords=command.keywords,
            types=command.types,
            page=command.page,
            page_size=command.page_size,
        )
    return ApiResponse(data=result)


@router.post("/places/detail", summary="查询地点详情", description="根据高德地点 ID 查询详情并核对城市。")
async def place_detail(
    command: PlaceDetailRequest,
    http_request: Request,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    access = build_planning_access(
        http_request, command.trip_id, PlanningOperation.PROVIDER_FACTS
    )
    with http_request.app.state.collaboration_readiness_guard.operation(access):
        result = await service.place_detail(
            command.city_context, place_id=command.place_id
        )
    return ApiResponse(data=result)


@router.post("/geocoding/forward", summary="地址解析为坐标", description="将城市内的地址转换为坐标。")
async def forward_geocoding(
    command: ForwardGeocodingRequest,
    http_request: Request,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    access = build_planning_access(
        http_request, command.trip_id, PlanningOperation.PROVIDER_FACTS
    )
    with http_request.app.state.collaboration_readiness_guard.operation(access):
        result = await service.forward_geocode(
            command.city_context, address=command.address
        )
    return ApiResponse(data=result)


@router.post("/geocoding/reverse", summary="坐标解析为地址", description="将坐标转换为地址并核对城市编码。")
async def reverse_geocoding(
    command: ReverseGeocodingRequest,
    http_request: Request,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    access = build_planning_access(
        http_request, command.trip_id, PlanningOperation.PROVIDER_FACTS
    )
    with http_request.app.state.collaboration_readiness_guard.operation(access):
        result = await service.reverse_geocode(
            command.city_context, location=command.location
        )
    return ApiResponse(data=result)


@router.post(
    "/routes/plan",
    summary="规划城市路线",
    description="规划步行、公交、自驾、骑行或打车路线。",
)
async def plan_route(
    command: RoutePlanRequest,
    http_request: Request,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    access = build_planning_access(
        http_request, command.trip_id, PlanningOperation.PROVIDER_FACTS
    )
    with http_request.app.state.collaboration_readiness_guard.operation(access):
        result = await service.plan_route(
            command.city_context,
            origin=command.origin,
            destination=command.destination,
            mode=command.mode,
            strategy=command.strategy,
        )
    return ApiResponse(data=result)
