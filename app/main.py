from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.arrival_decision_routes import router as arrival_decision_router
from app.api.arrival_evidence_routes import router as arrival_evidence_router
from app.api.routes import router
from app.api.execution_adjustment_routes import router as execution_adjustment_router
from app.api.plan_routes import router as plan_router
from app.api.planning_routes import router as planning_router
from app.api.trip_draft_routes import router as trip_draft_router
from app.api.workflow_routes import router as workflow_router
from app.api.collaboration_routes import router as collaboration_router
from app.api.recommendation_routes import router as recommendation_router
from app.api.media_routes import router as media_router
from app.application.arrival_decision_service import ArrivalDecisionService
from app.application.arrival_evidence_service import ArrivalEvidenceService
from app.application.collaboration_service import CollaborationService
from app.application.amap_service import AmapLocationService
from app.application.llm_gateway import (
    CandidateSelectionGateway,
    StrictCandidateSelectionGateway,
    UnavailableLlmGateway,
)
from app.application.execution_event_draft_service import ExecutionEventDraftService
from app.application.planning_boundary_service import PlanningBoundaryService
from app.application.plan_service import PlanVersionService
from app.application.recommendation_service import RecommendationOrchestrationService
from app.application.trip_draft_service import TripDraftParserService
from app.application.workflow_service import WorkflowService
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.domain.models import ErrorResponse
from app.infrastructure.amap import AmapClient
from app.infrastructure.arrival_evidence_store import (
    SqliteArrivalEvidenceRepository,
)
from app.infrastructure.bailian import BailianTripDraftExtractor
from app.infrastructure.bailian_execution_event import BailianExecutionEventExtractor
from app.infrastructure.cache import SqliteProviderCache
from app.infrastructure.openai_compatible_llm import (
    OpenAiCompatibleCandidateSelectionClient,
)
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.trusted_planning_store import SqliteTrustedPlanningRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.schemas.validation_error import TripSchemaError, issues_from_pydantic
from app.services.replanning import SuffixPlanner


SWAGGER_CHINESE_SCRIPT = """
<script>
(() => {
  const translations = new Map([
    ["Authorize", "授权"],
    ["Available authorizations", "可用的授权方式"],
    ["Close", "关闭"],
    ["Try it out", "试一试"],
    ["Cancel", "取消"],
    ["Execute", "执行"],
    ["Clear", "清空"],
    ["Parameters", "参数"],
    ["No parameters", "无参数"],
    ["Request body", "请求体"],
    ["Request URL", "请求地址"],
    ["Server response", "服务器响应"],
    ["Responses", "响应"],
    ["Response body", "响应内容"],
    ["Response headers", "响应头"],
    ["Response content type", "响应内容类型"],
    ["Code", "状态码"],
    ["Details", "详情"],
    ["Description", "说明"],
    ["Links", "链接"],
    ["Schemas", "数据模型"],
    ["Models", "数据模型"],
    ["Model", "模型"],
    ["Example Value", "示例值"],
    ["Example", "示例"],
    ["Schema", "结构"],
    ["Download", "下载"],
    ["Copy", "复制"],
    ["Copy to clipboard", "复制到剪贴板"],
    ["Copy path to clipboard", "复制接口路径"],
    ["Expand operation", "展开接口"],
    ["Collapse operation", "收起接口"],
    ["Expand all", "全部展开"],
    ["required", "必填"],
    ["Loading", "加载中"],
    ["Failed to fetch", "请求失败"],
    ["Network Error", "网络错误"]
    ,["Filter by tag", "按接口分组筛选"]
    ,["Filter", "筛选"]
  ]);

  function translate(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const original = node.nodeValue;
      const trimmed = original.trim();
      const translated = translations.get(trimmed);
      if (translated) node.nodeValue = original.replace(trimmed, translated);
    }
    const elements = root.querySelectorAll ? [root, ...root.querySelectorAll("*")] : [];
    for (const element of elements) {
      for (const attribute of ["placeholder", "title", "aria-label"]) {
        const original = element.getAttribute && element.getAttribute(attribute);
        const translated = translations.get(original);
        if (translated) element.setAttribute(attribute, translated);
      }
    }
    document.documentElement.lang = "zh-CN";
  }

  const observer = new MutationObserver((changes) => {
    for (const change of changes) {
      for (const node of change.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) translate(node);
      }
    }
  });

  translate(document.body);
  observer.observe(document.body, {childList: true, subtree: true});
})();
</script>
"""


def create_app(
    *,
    settings: Settings | None = None,
    service: AmapLocationService | None = None,
    plan_service: PlanVersionService | None = None,
    workflow_service: WorkflowService | None = None,
    planning_boundary_service: PlanningBoundaryService | None = None,
    recommendation_service: RecommendationOrchestrationService | None = None,
    suffix_planner: SuffixPlanner | None = None,
    candidate_selection_gateway: CandidateSelectionGateway | None = None,
    execution_event_draft_service: ExecutionEventDraftService | None = None,
    arrival_evidence_service: ArrivalEvidenceService | None = None,
    arrival_decision_service: ArrivalDecisionService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    managed_client: AmapClient | None = None
    managed_bailian_extractor: BailianTripDraftExtractor | None = None
    managed_candidate_selection_client: (
        OpenAiCompatibleCandidateSelectionClient | None
    ) = None
    managed_bailian_execution_extractor: BailianExecutionEventExtractor | None = None
    if service is None:
        managed_client = AmapClient(
            api_key=resolved_settings.amap_web_service_key,
            base_url=resolved_settings.amap_base_url,
            timeout_seconds=resolved_settings.amap_request_timeout_seconds,
        )
        service = AmapLocationService(
            client=managed_client,
            cache=SqliteProviderCache(resolved_settings.amap_cache_db_path),
            place_ttl_seconds=resolved_settings.amap_place_cache_ttl_seconds,
            route_ttl_seconds=resolved_settings.amap_route_cache_ttl_seconds,
        )

    bailian_api_key = (
        resolved_settings.bailian_api_key.get_secret_value().strip()
        if resolved_settings.bailian_api_key is not None
        else ""
    )
    if bailian_api_key:
        managed_bailian_extractor = BailianTripDraftExtractor(
            api_key=bailian_api_key,
            base_url=resolved_settings.bailian_base_url,
            model=resolved_settings.bailian_model,
            timeout_seconds=resolved_settings.bailian_request_timeout_seconds,
        )

    if candidate_selection_gateway is None and bailian_api_key:
        managed_candidate_selection_client = (
            OpenAiCompatibleCandidateSelectionClient(
                api_key=bailian_api_key,
                base_url=resolved_settings.bailian_base_url,
                model=resolved_settings.bailian_model,
                timeout_seconds=(
                    resolved_settings.bailian_candidate_timeout_seconds
                ),
            )
        )
        candidate_selection_gateway = StrictCandidateSelectionGateway(
            managed_candidate_selection_client,
        )
    elif candidate_selection_gateway is None:
        candidate_selection_gateway = UnavailableLlmGateway()

    if bailian_api_key and execution_event_draft_service is None:
        managed_bailian_execution_extractor = BailianExecutionEventExtractor(
            api_key=bailian_api_key,
            base_url=resolved_settings.bailian_base_url,
            model=resolved_settings.bailian_model,
            timeout_seconds=(
                resolved_settings.bailian_execution_event_timeout_seconds
            ),
        )

    if execution_event_draft_service is None:
        execution_event_draft_service = ExecutionEventDraftService(
            managed_bailian_execution_extractor,
            deadline_seconds=(
                resolved_settings.bailian_execution_event_timeout_seconds
            ),
        )

    if workflow_service is None:
        workflow_service = WorkflowService(
            SqliteWorkflowRepository(resolved_settings.plan_version_db_path)
        )

    if plan_service is None:
        plan_service = PlanVersionService(
            SqlitePlanVersionRepository(resolved_settings.plan_version_db_path),
            workflow_service=workflow_service,
        )

    if planning_boundary_service is None and isinstance(
        plan_service,
        PlanVersionService,
    ):
        planning_database_path = getattr(
            plan_service.repository,
            "database_path",
            resolved_settings.plan_version_db_path,
        )
        planning_boundary_service = PlanningBoundaryService(
            plan_service=plan_service,
            workflow_service=workflow_service,
            trust_repository=SqliteTrustedPlanningRepository(
                planning_database_path
            ),
            suffix_planner=suffix_planner,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if managed_client is not None:
            await managed_client.close()
        if managed_bailian_extractor is not None:
            await managed_bailian_extractor.close()
        if managed_candidate_selection_client is not None:
            await managed_candidate_selection_client.close()
        if managed_bailian_execution_extractor is not None:
            await managed_bailian_execution_extractor.close()

    app = FastAPI(
        title="行知旅伴——张琪 Sprint 1 接口",
        description="城市地点与可信来源，以及 PlanVersion、V1/V2 Diff、执行事件和实际预算。",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        openapi_tags=[
            {
                "name": "城市地点、路线与可信来源",
                "description": "地点、路线、价格事实、可信来源和城市隔离缓存。",
            },
            {
                "name": "PlanVersion 状态与 Diff",
                "description": "确认服务端签发候选、维护唯一 CURRENT、查看 V1/V2 Diff、记录执行事件并复算实际预算。",
            },
            {
                "name": "服务端规划与重规划",
                "description": "由 T011 生成可信 V1，并由 T011 + T018 校验和选择 V2。",
            },
            {
                "name": "多人公平推荐编排",
                "description": "恢复 FactRef、校验千问白名单提议、构建真实路线候选并执行公平唯一裁决。",
            },
            {
                "name": "执行中迟到与疲劳调整",
                "description": "S2-T019 草稿解析和 S2-T020 确定性临时约束。",
            },
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Organizer-Token"],
        expose_headers=[
            "X-Recognition-Source",
            "X-Recognition-Model",
            "X-Degraded-Reason",
        ],
    )
    app.state.location_service = service
    app.state.settings = resolved_settings
    app.state.natural_language_parser = (
        "BAILIAN_CONFIGURED"
        if managed_bailian_extractor is not None
        else "DETERMINISTIC_RULES"
    )
    app.state.media_database_path = resolved_settings.plan_version_db_path
    app.state.trip_draft_service = TripDraftParserService(
        service,
        llm_extractor=managed_bailian_extractor,
    )
    app.state.candidate_selection_gateway = candidate_selection_gateway
    app.state.execution_event_draft_service = execution_event_draft_service
    app.state.arrival_evidence_service = (
        arrival_evidence_service
        or ArrivalEvidenceService(
            SqliteArrivalEvidenceRepository(
                resolved_settings.plan_version_db_path
            )
        )
    )
    app.state.arrival_decision_service = (
        arrival_decision_service
        or ArrivalDecisionService(app.state.arrival_evidence_service)
    )
    app.state.collaboration_service = CollaborationService(
        SqliteCollaborationRepository(resolved_settings.plan_version_db_path),
        app.state.trip_draft_service,
        workflow_service,
    )
    app.state.plan_version_service = plan_service
    app.state.workflow_service = workflow_service
    app.state.planning_boundary_service = planning_boundary_service
    app.state.recommendation_service = recommendation_service
    app.include_router(arrival_decision_router)
    app.include_router(arrival_evidence_router)
    app.include_router(router)
    app.include_router(execution_adjustment_router)
    app.include_router(plan_router)
    app.include_router(planning_router)
    app.include_router(trip_draft_router)
    app.include_router(collaboration_router)
    app.include_router(recommendation_router)
    app.include_router(media_router)
    app.include_router(workflow_router)

    @app.get("/health", tags=["系统"], summary="健康检查")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "buildSha": resolved_settings.build_sha or "unavailable",
            "naturalLanguageParser": app.state.natural_language_parser,
            "executionAdjustmentParser": (
                "BAILIAN_CONFIGURED"
                if managed_bailian_execution_extractor is not None
                else "DETERMINISTIC_FORM"
            ),
        }

    @app.get("/docs", include_in_schema=False)
    async def chinese_api_docs() -> HTMLResponse:
        swagger = get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title="行知旅伴接口文档",
            swagger_ui_parameters={
                "defaultModelsExpandDepth": 1,
                "displayRequestDuration": True,
                "docExpansion": "list",
                "filter": True,
            },
        )
        html = swagger.body.decode("utf-8")
        html = html.replace("<html>", '<html lang="zh-CN">')
        html = html.replace("</body>", f"{SWAGGER_CHINESE_SCRIPT}</body>")
        return HTMLResponse(content=html)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, error: AppError) -> JSONResponse:
        body = ErrorResponse(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            errors=error.errors,
        )
        return JSONResponse(status_code=error.http_status, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        normalized_errors = []
        for item in error.errors():
            location = tuple(item.get("loc", ()))
            if location and location[0] in {"body", "query", "path"}:
                location = location[1:]
            normalized_errors.append({**item, "loc": location})
        body = TripSchemaError(issues_from_pydantic(normalized_errors)).as_dict()
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(TripSchemaError)
    async def handle_trip_schema_error(
        _: Request,
        error: TripSchemaError,
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content=error.as_dict())

    return app


app = create_app()
