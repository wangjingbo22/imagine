from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.domain.trip_draft import TripUnderstandingGatewayResult, TripUnderstandingProposal
from app.main import create_app


FIXTURE = Path(__file__).parent / "fixtures" / "trip_understanding" / "one_participant.json"


def _reviewed_request() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-31",
        "naturalLanguageRequest": "想在北京轻松玩一天，参观历史景点并品尝北京特色美食。",
        "reviewedFallback": True,
        "answers": [
            {
                "questionId": "trip",
                "answer": "目的城市：北京；出行日期：2026-09-06；可用时间：09:00到18:00",
            },
            {
                "questionId": "party",
                "answer": "1个人出行；组织者昵称：测试用户",
            },
            {
                "questionId": "endpoints_budget",
                "answer": "从北京站出发；结束地：北京站；共享预算：500",
            },
            {
                "questionId": "preferences",
                "answer": "喜欢历史文化和美食，必去故宫和天坛，不去酒吧。",
            },
            {
                "questionId": "assistance",
                "answer": "组织者个人预算上限：500元；关怀模式：ORDINARY（普通出行）。",
            },
            {
                "questionId": "confirm",
                "answer": "确认；没有其他不可妥协限制。",
            },
        ],
    }


def _model_request() -> dict[str, object]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    evidence = " ".join(item["sourceText"] for item in fixture["fieldEvidence"])
    evidence = " ".join((evidence, "ordinary assistance no stair restriction"))
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-31",
        "naturalLanguageRequest": evidence,
        "answers": [
            {"questionId": question_id, "answer": evidence}
            for question_id in (
                "trip",
                "party",
                "endpoints_budget",
                "preferences",
                "assistance",
                "confirm",
            )
        ],
    }


class CountingGateway:
    def __init__(self, result: TripUnderstandingGatewayResult) -> None:
        self.result = result
        self.calls = 0

    async def understand(self, request: Any) -> TripUnderstandingGatewayResult:
        del request
        self.calls += 1
        return self.result


def _failure_result(code: str = "LLM_UNAVAILABLE") -> TripUnderstandingGatewayResult:
    return TripUnderstandingGatewayResult(
        decision="FIXED_QUESTIONS",
        proposal=None,
        failureCode=code,
        callCount=2,
        model="fixture-qwen",
    )


def _model_result() -> TripUnderstandingGatewayResult:
    return TripUnderstandingGatewayResult(
        decision="MODEL_PROPOSAL",
        proposal=TripUnderstandingProposal.model_validate_json(
            FIXTURE.read_text(encoding="utf-8"),
            strict=True,
        ),
        failureCode=None,
        callCount=1,
        model="fixture-qwen",
    )


def _app(tmp_path: Path, gateway: CountingGateway | None = None):
    return create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=tmp_path / "planning.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )


async def _post(app, payload: dict[str, object], key: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": key},
            json=payload,
        )


@pytest.mark.asyncio
async def test_reviewed_fallback_creation_projects_authoritative_degradation(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=tmp_path / "planning.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": "s3-t008-red-0001"},
            json=_reviewed_request(),
        )

    assert response.status_code == 200
    assert response.json()["data"]["recognition"] == {
        "source": "REVIEWED_FIXED_QUESTIONS",
        "model": None,
        "degradedReason": "LLM_NOT_CONFIGURED",
        "callCount": 0,
    }


@pytest.mark.asyncio
async def test_unreviewed_failure_keeps_fixed_question_response_without_revision(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_failure_result("LLM_TIMEOUT"))
    app = _app(tmp_path, gateway)
    payload = _reviewed_request()
    payload["reviewedFallback"] = False

    response = await _post(app, payload, "s3-t008-fixed-0001")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["recognition"] == {
        "source": "FIXED_QUESTIONS",
        "model": "fixture-qwen",
        "failureCode": "LLM_TIMEOUT",
        "callCount": 2,
    }
    assert data["understanding"] is None
    assert data["canPlan"] is False
    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_sessions"
        ).fetchone()[0] == 0
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_model_success_projects_model_source_without_degraded_reason(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_model_result())
    response = await _post(
        _app(tmp_path, gateway),
        _model_request(),
        "s3-t008-model-0001",
    )

    assert response.status_code == 200
    assert response.json()["data"]["recognition"] == {
        "source": "MODEL_PROPOSAL",
        "model": "fixture-qwen",
        "degradedReason": None,
        "callCount": 1,
    }
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_reviewed_fallback_replay_projects_stored_metadata_without_new_revision(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_failure_result())
    app = _app(tmp_path, gateway)
    payload = _reviewed_request()

    first = await _post(app, payload, "s3-t008-replay-0001")
    replay = await _post(app, payload, "s3-t008-replay-0001")

    assert first.status_code == replay.status_code == 200
    assert first.json()["data"]["revision"] == replay.json()["data"]["revision"]
    assert replay.json()["data"]["recognition"] == {
        "source": "REVIEWED_FIXED_QUESTIONS",
        "model": "fixture-qwen",
        "degradedReason": "LLM_UNAVAILABLE",
        "callCount": 2,
    }
    assert gateway.calls == 1

    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0] == 1
