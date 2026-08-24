from fastapi import APIRouter, Depends, Request

from app.application.amap_service import AmapLocationService
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
async def health() -> ApiResponse[dict[str, str]]:
    return ApiResponse(data={"status": "UP"})


@router.post("/cities/resolve", summary="解析目标城市", description="根据国内城市名称解析城市编码和中心坐标。")
async def resolve_city(
    request: CityResolveRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.resolve_city(request.city_name)
    return ApiResponse(data=result)


@router.post("/places/suggestions", summary="获取地点输入提示", description="在指定城市范围内获取地点关键词联想。")
async def suggestions(
    request: SuggestionRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.suggestions(
        request.city_context,
        keywords=request.keywords,
        types=request.types,
        limit=request.limit,
    )
    return ApiResponse(data=result)


@router.post("/places/search", summary="搜索城市地点", description="搜索同城地点并返回来源、时间和价格可信状态。")
async def search_places(
    request: PlaceSearchRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.search_places(
        request.city_context,
        keywords=request.keywords,
        types=request.types,
        page=request.page,
        page_size=request.page_size,
    )
    return ApiResponse(data=result)


@router.post("/places/nearby", summary="搜索附近地点", description="以指定坐标为中心搜索同城地点。")
async def nearby_places(
    request: NearbySearchRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.nearby_places(
        request.city_context,
        center=request.center,
        radius_meters=request.radius_meters,
        keywords=request.keywords,
        types=request.types,
        page=request.page,
        page_size=request.page_size,
    )
    return ApiResponse(data=result)


@router.post("/places/detail", summary="查询地点详情", description="根据高德地点 ID 查询详情并核对城市。")
async def place_detail(
    request: PlaceDetailRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.place_detail(request.city_context, place_id=request.place_id)
    return ApiResponse(data=result)


@router.post("/geocoding/forward", summary="地址解析为坐标", description="将城市内的地址转换为坐标。")
async def forward_geocoding(
    request: ForwardGeocodingRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.forward_geocode(request.city_context, address=request.address)
    return ApiResponse(data=result)


@router.post("/geocoding/reverse", summary="坐标解析为地址", description="将坐标转换为地址并核对城市编码。")
async def reverse_geocoding(
    request: ReverseGeocodingRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.reverse_geocode(request.city_context, location=request.location)
    return ApiResponse(data=result)


@router.post("/routes/plan", summary="规划城市路线", description="规划步行、公交、驾车或骑行路线。")
async def plan_route(
    request: RoutePlanRequest,
    service: AmapLocationService = Depends(get_location_service),
) -> ApiResponse:
    result = await service.plan_route(
        request.city_context,
        origin=request.origin,
        destination=request.destination,
        mode=request.mode,
        strategy=request.strategy,
    )
    return ApiResponse(data=result)
