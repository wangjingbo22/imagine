from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TypeAlias

from fastapi import Request

from app.application.llm_gateway import StrictTripUnderstandingGateway
from app.application.llm_gateway import StrictCandidateSelectionGateway
from app.application.account_service import validate_public_model_base_url
from app.application.recommendation_service import RecommendationOrchestrationService
from app.application.trip_draft_revision_service import TripDraftRevisionService
from app.core.errors import AppError
from app.infrastructure.bailian import BailianTripDraftExtractor
from app.infrastructure.openai_compatible_llm import OpenAiCompatibleCandidateSelectionClient


AccountModelCredentials: TypeAlias = tuple[str, str, str]


def require_account_model_credentials(request: Request) -> AccountModelCredentials:
    token = request.cookies.get("account_session")
    credentials = request.app.state.account_service.user_model_credentials(token)
    if credentials is None:
        raise AppError(
            code="ACCOUNT_MODEL_CONFIGURATION_REQUIRED",
            message="请先在模型设置中绑定 API Key 后再生成行程",
            http_status=403,
            retryable=False,
        )
    return credentials


@asynccontextmanager
async def account_trip_draft_revision_service(request: Request):
    model, api_key, base_url = require_account_model_credentials(request)
    base_url = validate_public_model_base_url(base_url)
    settings = request.app.state.settings
    extractor = BailianTripDraftExtractor(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=settings.bailian_request_timeout_seconds,
    )
    shared = request.app.state.trip_draft_revision_creator
    service = TripDraftRevisionService(
        repository=shared.repository,
        gateway=StrictTripUnderstandingGateway(extractor, max_transport_attempts=1),
    )
    try:
        yield service
    finally:
        await extractor.close()


@asynccontextmanager
async def account_recommendation_service(request: Request):
    model, api_key, base_url = require_account_model_credentials(request)
    base_url = validate_public_model_base_url(base_url)
    settings = request.app.state.settings
    client = OpenAiCompatibleCandidateSelectionClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=settings.bailian_candidate_timeout_seconds,
    )
    shared = request.app.state.recommendation_service
    service = RecommendationOrchestrationService(
        fact_registry=shared._fact_registry,
        route_builder=shared._route_builder,
        readiness_guard=shared.readiness_guard,
        candidate_selection_gateway=StrictCandidateSelectionGateway(client),
        planner=shared._planner,
        fairness=shared._fairness,
    )
    try:
        yield service
    finally:
        await client.close()


__all__ = [
    "AccountModelCredentials",
    "account_recommendation_service",
    "account_trip_draft_revision_service",
    "require_account_model_credentials",
]