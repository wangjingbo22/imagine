from fastapi import APIRouter, Depends, Request

from app.application.trip_draft_service import TripDraftParserService
from app.application.workflow_service import WorkflowService
from app.domain.models import ApiResponse
from app.domain.trip_draft import TripDraftParseRequest
from app.infrastructure.bailian import BailianTripDraftExtractor


router = APIRouter(prefix="/api/v1", tags=["自然语言行程解析与歧义确认"])


def get_trip_draft_service(request: Request) -> TripDraftParserService:
    return request.app.state.trip_draft_service


def get_workflow_service(request: Request) -> WorkflowService:
    return request.app.state.workflow_service


@router.post(
    "/trips/drafts/parse",
    summary="解析自然语言行程草稿",
    description="解析日期、时间、预算、兴趣和地点限制；缺失或歧义字段返回逐项确认清单。",
)
async def parse_trip_draft(
    payload: TripDraftParseRequest,
    request: Request,
    service: TripDraftParserService = Depends(get_trip_draft_service),
) -> ApiResponse:
    return ApiResponse(data=await _parse_with_user_model(request, service, payload))


@router.post(
    "/trips/drafts/confirm",
    summary="确认解析结果并生成统一 Trip",
    description="确认项未全部解决时返回 TRIP_CONFIRMATION_REQUIRED，禁止进入规划。",
)
async def confirm_trip_draft(
    payload: TripDraftParseRequest,
    request: Request,
    service: TripDraftParserService = Depends(get_trip_draft_service),
    workflow: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    parsed = await _parse_with_user_model(request, service, payload)
    confirmed = service.require_planning_ready(parsed)
    return ApiResponse(data=workflow.confirm_trip(confirmed))


async def _parse_with_user_model(
    request: Request,
    service: TripDraftParserService,
    payload: TripDraftParseRequest,
):
    """Use an optional browser-session key for this request only; never persist it."""
    token = request.cookies.get("account_session")
    if not token:
        return await service.parse(payload)
    credentials = request.app.state.account_service.user_model_credentials(token)
    if credentials is None:
        return await service.parse(payload)
    model, api_key = credentials
    settings = request.app.state.settings
    extractor = BailianTripDraftExtractor(
        api_key=api_key,
        base_url=settings.bailian_base_url,
        model=model,
        timeout_seconds=settings.bailian_request_timeout_seconds,
    )
    ephemeral_service = TripDraftParserService(
        city_resolver=service._city_resolver,
        llm_extractor=extractor,
    )
    try:
        return await ephemeral_service.parse(payload)
    finally:
        await extractor.close()
