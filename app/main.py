from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.routes import router
from app.api.plan_routes import router as plan_router
from app.api.trip_draft_routes import router as trip_draft_router
from app.application.amap_service import AmapLocationService
from app.application.plan_service import PlanVersionService
from app.application.trip_draft_service import TripDraftParserService
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.domain.models import ErrorResponse
from app.infrastructure.amap import AmapClient
from app.infrastructure.cache import SqliteProviderCache
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.schemas.validation_error import TripSchemaError, issues_from_pydantic


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
) -> FastAPI:
    resolved_settings = settings or get_settings()
    managed_client: AmapClient | None = None

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

    if plan_service is None:
        plan_service = PlanVersionService(
            SqlitePlanVersionRepository(resolved_settings.plan_version_db_path)
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if managed_client is not None:
            await managed_client.close()

    app = FastAPI(
        title="行知旅伴——张琪 Sprint 1 接口",
        description="城市地点与可信来源，以及 PlanVersion 确认、V1/V2 Diff、接受拒绝和执行状态守卫。",
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
                "description": "登记不可变候选、确认唯一 CURRENT、查看 V1/V2 Diff，并原子接受或拒绝 V2。",
            },
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.state.location_service = service
    app.state.trip_draft_service = TripDraftParserService(service)
    app.state.plan_version_service = plan_service
    app.include_router(router)
    app.include_router(plan_router)
    app.include_router(trip_draft_router)

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
