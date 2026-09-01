from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.application.reviewed_fallback_understanding import (
    reviewed_fallback_proposal,
    reviewed_member_fallback_proposal,
)
from app.application.collaboration_planning_bridge import CollaborationPlanningBridge
from app.application.planning_boundary_service import PlanningBoundaryService
from app.application.recommendation_service import project_collaboration_recommendation_trip
from app.application.trip_draft_revision_service import TripDraftRevisionService
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import ConversationSubmission, OrganizerConversationRequest, QUESTION_IDS
from app.domain.trip_draft import (
    TripDraftRevision,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
)
from app.infrastructure.trip_draft_revision_store import (
    SqliteTripDraftRevisionRepository,
)
from app.main import create_app
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig


FIXTURE = Path(__file__).parent / "fixtures" / "trip_understanding" / "one_participant.json"


def _proposal() -> TripUnderstandingProposal:
    return TripUnderstandingProposal.model_validate_json(
        FIXTURE.read_text(encoding="utf-8"),
        strict=True,
    )


def _two_participant_proposal() -> TripUnderstandingProposal:
    fixture = FIXTURE.with_name("two_participants.json")
    return TripUnderstandingProposal.model_validate_json(
        fixture.read_text(encoding="utf-8"),
        strict=True,
    )


def _request(
    *extra: str,
    fixture_path: Path = FIXTURE,
) -> OrganizerConversationRequest:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    evidence = " ".join(item["sourceText"] for item in fixture["fieldEvidence"])
    evidence = " ".join((evidence, "ordinary assistance no stair restriction", *extra))
    return OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate="2026-08-27",
        naturalLanguageRequest=evidence,
        answers=[
            {"questionId": question_id, "answer": evidence}
            for question_id in QUESTION_IDS
        ],
    )


def _reviewed_request(*, participant_count: int = 2) -> OrganizerConversationRequest:
    time_label = "出行时间" if participant_count == 1 else "可用时间"
    budget_label = "单人预算" if participant_count == 1 else "共享预算"
    return OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate="2026-08-31",
        naturalLanguageRequest="想在北京轻松玩一天，参观历史景点并品尝北京特色美食。",
        reviewedFallback=True,
        answers=[
            {"questionId": "trip", "answer": f"目的城市：北京；出行日期：2026-09-06；{time_label}：09:00到18:00"},
            {"questionId": "party", "answer": f"{participant_count}个人出行；组织者昵称：测试用户"},
            {"questionId": "endpoints_budget", "answer": f"从北京站出发；结束地：北京站；{budget_label}：500"},
            {"questionId": "preferences", "answer": "喜欢历史文化和美食，必去故宫和天坛，不去酒吧。"},
            {"questionId": "assistance", "answer": "组织者个人预算上限：500元；关怀模式：ORDINARY（普通出行（无额外关怀限制））。"},
            {"questionId": "confirm", "answer": "确认；没有其他不可妥协限制。"},
        ],
    )


def _reviewed_member_submission() -> ConversationSubmission:
    return ConversationSubmission(
        naturalLanguageRequest="参加组织者创建的北京行程，并独立确认我的个人偏好与关怀限制。",
        reviewedFallback=True,
        answers=[
            {"questionId": "trip", "answer": "城市：北京；日期：2026-09-06；时间：09:00到18:00"},
            {"questionId": "party", "answer": "同行信息由组织者管理；我是通过成员邀请链接加入的成员。"},
            {"questionId": "endpoints_budget", "answer": "从北京站出发；结束地：北京站；共享预算：500元"},
            {"questionId": "preferences", "answer": "兴趣：；必去：；避开："},
            {"questionId": "assistance", "answer": "个人预算上限：未设置；没有额外关怀限制。"},
            {"questionId": "confirm", "answer": "我已查看共同信息，并确认这里填写的是我本人的需求。"},
        ],
    )


@pytest.mark.parametrize("budget_label", ["本次行程总预算", "同行行程总预算"])
def test_reviewed_fallback_accepts_contextual_trip_budget_labels(
    budget_label: str,
) -> None:
    request = _reviewed_request(participant_count=1)
    request.answers[2].answer = (
        f"从北京站出发；结束地：北京站；{budget_label}：500"
    )

    proposal = reviewed_fallback_proposal(request)

    assert proposal.trip.budget_cents == 50_000


def test_reviewed_fallback_keeps_all_members_beyond_the_old_three_person_limit() -> None:
    # 降级整理同样不能把大团队静默裁剪成三人，否则后续邀请数量会与表单不一致。
    proposal = reviewed_fallback_proposal(_reviewed_request(participant_count=12))

    assert len(proposal.participants) == 12
    assert proposal.participants[-1].member_key == "member-12"


def _result(
    *,
    proposal: TripUnderstandingProposal | None = None,
    failure_code: str | None = None,
    call_count: int = 2,
    model: str | None = "test-model",
) -> TripUnderstandingGatewayResult:
    return TripUnderstandingGatewayResult(
        decision="FIXED_QUESTIONS" if failure_code else "MODEL_PROPOSAL",
        proposal=proposal if failure_code is None else None,
        failureCode=failure_code,
        callCount=call_count,
        model=model,
    )


class CountingGateway:
    def __init__(self, result: TripUnderstandingGatewayResult) -> None:
        self.result = result
        self.calls = 0

    async def understand(self, request: Any) -> TripUnderstandingGatewayResult:
        self.calls += 1
        return self.result


def _service(
    tmp_path: Path,
    gateway: CountingGateway,
) -> tuple[TripDraftRevisionService, SqliteTripDraftRevisionRepository]:
    repository = SqliteTripDraftRevisionRepository(tmp_path / "planning.sqlite3")
    return TripDraftRevisionService(repository=repository, gateway=gateway), repository


def _app(tmp_path: Path, gateway: CountingGateway | None = None):
    settings = Settings(
        _env_file=None,
        plan_version_db_path=tmp_path / "planning.sqlite3",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
    )
    return create_app(
        settings=settings,
        service=object(),  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )


async def _post(app, request: OrganizerConversationRequest, key: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": key},
            json=request.model_dump(mode="json", by_alias=True),
        )


def _revision_count(repository: SqliteTripDraftRevisionRepository) -> int:
    with repository._connect() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference_date", "reference_time", "expected_code"),
    [
        (date(2026, 9, 7), "08:00", "TRIP_DATE_IN_PAST"),
        (date(2026, 9, 6), "09:00", "TRIP_START_TIME_IN_PAST"),
    ],
)
async def test_reviewed_fallback_rejects_past_trip_time_before_persisting_revision(
    tmp_path: Path,
    reference_date: date,
    reference_time: str,
    expected_code: str,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_NOT_CONFIGURED", call_count=0))
    service, repository = _service(tmp_path, gateway)
    request = _reviewed_request().model_copy(update={
        "reference_date": reference_date,
        "reference_time": reference_time,
    })

    with pytest.raises(AppError) as caught:
        await service.create_initial(
            request,
            idempotency_key=f"past-time-{expected_code.lower()}",
        )

    assert caught.value.code == expected_code
    assert caught.value.http_status == 422
    assert _revision_count(repository) == 0


@pytest.mark.asyncio
async def test_model_failure_preserves_input_and_six_answers_without_canonical_write(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_TIMEOUT"))
    service, repository = _service(tmp_path, gateway)
    request = _request()

    outcome = await service.create_initial(request, idempotency_key="t004-fallback-0001")

    assert outcome.answer_revision == 1
    assert outcome.natural_language_request == request.natural_language_request
    assert outcome.answers == request.answers
    assert outcome.recognition.source == "FIXED_QUESTIONS"
    assert outcome.recognition.failure_code == "LLM_TIMEOUT"
    assert outcome.recognition.call_count == 2
    assert outcome.recognition.model == "test-model"
    assert outcome.understanding is None
    assert outcome.fallback.mode == "FIXED_QUESTIONS"
    assert len(outcome.fallback.items) == 6
    assert outcome.can_plan is False
    assert _revision_count(repository) == 0

    with repository._connect() as connection:
        stored = connection.execute(
            "SELECT status, outcome_json FROM trip_draft_commands"
        ).fetchone()
    assert stored["status"] == "FAILED"
    assert stored["outcome_json"]
    assert "LLM_TIMEOUT" in stored["outcome_json"]
    assert "rawConversation" not in stored["outcome_json"]


@pytest.mark.asyncio
async def test_reviewed_fixed_answers_create_deterministic_group_revision_when_model_is_unavailable(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_UNAVAILABLE"))
    service, repository = _service(tmp_path, gateway)

    outcome = await service.create_initial(
        _reviewed_request(participant_count=2),
        idempotency_key="t004-reviewed-fallback-01",
    )

    assert isinstance(outcome, TripDraftRevision)
    assert outcome.understanding.trip.city_name == "北京"
    assert outcome.understanding.trip.budget_cents == 50_000
    assert len(outcome.understanding.participants) == 2
    assert outcome.understanding.participants[0].nickname == "测试用户"
    assert outcome.understanding.participants[0].care_draft is not None
    assert outcome.understanding.participants[0].care_draft.assistance_type_hint == "ORDINARY"
    assert outcome.understanding.participants[1].care_draft is None
    assert _revision_count(repository) == 1

    with repository._connect() as connection:
        stored = connection.execute(
            "SELECT recognition_source, degraded_reason, llm_call_count "
            "FROM trip_draft_revisions"
        ).fetchone()
    assert stored["recognition_source"] == "REVIEWED_FIXED_QUESTIONS"
    assert stored["degraded_reason"] == "LLM_UNAVAILABLE"
    assert stored["llm_call_count"] == 2


def test_reviewed_single_answers_accept_travel_time_and_single_budget() -> None:
    proposal = reviewed_fallback_proposal(_reviewed_request(participant_count=1))

    assert proposal.trip.start_time == "09:00"
    assert proposal.trip.end_time == "18:00"
    assert proposal.trip.budget_cents == 50_000
    assert len(proposal.participants) == 1
    evidence = {item.field_path: item.source_text for item in proposal.field_evidence}
    assert evidence["trip.budgetCents"] == "500"


@pytest.mark.asyncio
async def test_group_model_failure_uses_structured_answers_without_repeating_party_question(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_SCHEMA_INVALID"))
    service, _ = _service(tmp_path, gateway)
    request = _reviewed_request(participant_count=3).model_copy(
        update={"reviewed_fallback": False}
    )

    outcome = await service.create_initial(
        request,
        idempotency_key="t004-three-person-no-repeat-01",
    )

    assert isinstance(outcome, TripDraftRevision)
    assert len(outcome.understanding.participants) == 3
    assert set(outcome.member_bindings) == {"member-1", "member-2", "member-3"}


@pytest.mark.asyncio
async def test_explicit_group_count_overrides_single_participant_model_proposal(
    tmp_path: Path,
) -> None:
    single_proposal = reviewed_fallback_proposal(
        _reviewed_request(participant_count=1)
    )
    gateway = CountingGateway(_result(proposal=single_proposal))
    service, _ = _service(tmp_path, gateway)

    outcome = await service.create_initial(
        _reviewed_request(participant_count=2),
        idempotency_key="t004-two-person-model-alignment-01",
    )

    assert isinstance(outcome, TripDraftRevision)
    assert len(outcome.understanding.participants) == 2
    assert set(outcome.member_bindings) == {"member-1", "member-2"}
    assert all(
        item.field_path != "participants"
        for item in outcome.understanding.missing_fields
    )
    assert outcome.understanding.participants[1].care_draft is None


@pytest.mark.asyncio
async def test_reviewed_member_answers_complete_deterministic_organizer_draft(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_NOT_CONFIGURED", call_count=0, model=None))
    service, repository = _service(tmp_path, gateway)
    initial = await service.create_initial(
        _reviewed_request(participant_count=2),
        idempotency_key="t004-reviewed-member-initial-01",
    )
    assert isinstance(initial, TripDraftRevision)
    participant_id = initial.member_bindings["member-2"]
    submission = _reviewed_member_submission()

    current = service.get_current(initial.trip_id)
    proposal = reviewed_member_fallback_proposal(
        current.understanding,
        member_key="member-2",
        submission=submission,
    )
    assert proposal.participants[1].care_draft is not None

    revised = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=1,
        submission=submission,
        idempotency_key="t004-reviewed-member-submit-01",
    )

    assert isinstance(revised, TripDraftRevision)
    assert revised.revision == 2
    assert revised.understanding.trip == initial.understanding.trip
    assert revised.understanding.participants[0] == initial.understanding.participants[0]
    assert revised.understanding.participants[1].care_draft is not None
    assert revised.understanding.participants[1].care_draft.assistance_type_hint == "ORDINARY"
    assert revised.understanding.participants[1].nickname is None
    assert revised.understanding.participants[1].budget_cap_cents is None

    projected = project_collaboration_recommendation_trip(
        revised,
        CityContext(
            countryCode="CN",
            cityCode="110000",
            cityName="北京市",
            center=GeoPoint(longitude=116.407387, latitude=39.904179),
            providerConfig=ProviderConfig(provider="AMAP", coordinateSystem="GCJ02"),
        ),
    )
    assert projected.mode.value == "GROUP"
    assert projected.participants[1].nickname == "成员 2"
    assert projected.participants[1].budget_cap_cents == 50_000

    class RecordingWorkflow:
        def confirm_collaboration_trip(self, trip):
            return trip

    persisted = CollaborationPlanningBridge(
        RecordingWorkflow(),  # type: ignore[arg-type]
    ).materialize(revised, projected.city_context)
    assert persisted.participants[1].nickname == "成员 2"
    assert persisted.participants[1].budget_cap_cents == 50_000

    boundary_projection = PlanningBoundaryService._revision_planning_projection(revised)
    assert boundary_projection["participants"][1]["nickname"] == "成员 2"
    assert boundary_projection["participants"][1]["budgetCents"] == 50_000
    assert _revision_count(repository) == 2


@pytest.mark.asyncio
async def test_same_answer_revision_replay_does_not_call_gateway_again(tmp_path: Path) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_INVALID_JSON"))
    service, repository = _service(tmp_path, gateway)
    request = _request()

    first = await service.create_initial(request, idempotency_key="t004-fallback-0002")
    replay = await service.create_initial(request, idempotency_key="t004-fallback-0002")

    assert replay == first
    assert gateway.calls == 1
    assert _revision_count(repository) == 0


@pytest.mark.asyncio
async def test_same_revision_with_different_source_digest_is_rejected_before_gateway(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_SCHEMA_INVALID"))
    service, repository = _service(tmp_path, gateway)

    await service.create_initial(_request(), idempotency_key="t004-fallback-0003")
    with pytest.raises(AppError) as caught:
        await service.create_initial(
            _request("changed answer"),
            idempotency_key="t004-fallback-0003",
        )

    assert caught.value.code == "ANSWER_REVISION_STALE"
    assert gateway.calls == 1
    assert _revision_count(repository) == 0


@pytest.mark.asyncio
async def test_new_answer_revision_is_the_only_way_to_start_a_new_call(tmp_path: Path) -> None:
    gateway = CountingGateway(_result(proposal=_proposal()))
    service, repository = _service(tmp_path, gateway)
    initial = await service.create_initial(_request(), idempotency_key="t004-model-0001")
    participant_id = initial.member_bindings["member-1"]

    gateway.result = _result(proposal=_proposal())
    revised = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=initial.revision,
        submission=_request(),
        idempotency_key="t004-member-0001",
    )
    replay = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=initial.revision,
        submission=_request(),
        idempotency_key="t004-member-0001",
    )

    assert isinstance(revised, TripDraftRevision)
    assert revised.revision == 2
    assert replay == revised
    assert gateway.calls == 2
    assert _revision_count(repository) == 2


@pytest.mark.asyncio
async def test_success_appends_only_the_strict_non_authoritative_proposal(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(proposal=_proposal()))
    service, repository = _service(tmp_path, gateway)

    revision = await service.create_initial(_request(), idempotency_key="t004-model-0002")

    assert isinstance(revision, TripDraftRevision)
    assert revision.understanding == gateway.result.proposal
    assert _revision_count(repository) == 1


@pytest.mark.asyncio
async def test_fallback_does_not_call_workflow_constraints_plans_confirmations_or_provider(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_TIMEOUT"))
    app = _app(tmp_path, gateway)

    response = await _post(app, _request(), "t004-http-0003-xx")

    assert response.status_code == 200
    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        for table in tables:
            if any(
                marker in table
                for marker in ("workflow", "plan", "provider", "confirmation")
            ):
                assert connection.execute(
                    f"SELECT COUNT(*) FROM [{table}]"
                ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_commands"
        ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_conversation_http_returns_fixed_questions_and_no_store_on_llm_failure(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_SCHEMA_INVALID"))
    app = _app(tmp_path, gateway)
    request = _request()

    response = await _post(app, request, "t004-http-0001-xx")
    replay = await _post(app, request, "t004-http-0001-xx")

    assert response.status_code == replay.status_code == 200
    assert response.headers["Cache-Control"] == replay.headers["Cache-Control"] == "no-store"
    first_data = response.json()["data"]
    replay_data = replay.json()["data"]
    assert first_data == replay_data
    assert first_data["answerRevision"] == 1
    assert first_data["naturalLanguageRequest"] == request.natural_language_request
    assert first_data["answers"] == request.model_dump(mode="json", by_alias=True)["answers"]
    assert first_data["recognition"]["source"] == "FIXED_QUESTIONS"
    assert first_data["recognition"]["failureCode"] == "LLM_SCHEMA_INVALID"
    assert first_data["recognition"]["callCount"] == 2
    assert first_data["understanding"] is None
    assert first_data["canPlan"] is False
    assert len(first_data["fallback"]["items"]) == 6
    assert gateway.calls == 1

    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_sessions"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_http_without_bailian_key_returns_fixed_questions_with_zero_calls(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)

    response = await _post(app, _request(), "t004-http-0002-xx")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["recognition"]["source"] == "FIXED_QUESTIONS"
    assert data["recognition"]["failureCode"] == "LLM_NOT_CONFIGURED"
    assert data["recognition"]["callCount"] == 0
    assert data["recognition"]["model"] is None
    assert data["understanding"] is None
    assert data["canPlan"] is False
    assert len(data["fallback"]["items"]) == 6


@pytest.mark.asyncio
async def test_member_conversation_fallback_returns_200_without_advancing_collaboration(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(proposal=_two_participant_proposal()))
    app = _app(tmp_path, gateway)
    request = _request(fixture_path=FIXTURE.with_name("two_participants.json"))

    created = await _post(app, request, "t004-member-create-01")
    created_data = created.json()["data"]
    trip_id = created_data["revision"]["tripId"]
    member_id = created_data["revision"]["memberBindings"]["member-2"]
    organizer_token = created_data["organizerAccess"]["organizerToken"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        invitation = await client.post(
            f"/api/v2/trips/{trip_id}/participants/{member_id}/invitations",
            headers={
                "X-Organizer-Token": organizer_token,
                "Idempotency-Key": "t004-member-invite-01",
            },
            json={
                "schemaVersion": "1.0",
                "expectedVersion": 1,
            },
        )
        invitation_token = invitation.json()["data"]["invitationUrl"].rsplit("/", 1)[1]
        redeemed = await client.post(
            "/api/v2/participant-invitations/redeem",
            headers={"Idempotency-Key": "t004-member-redeem-01"},
            json={
                "schemaVersion": "1.0",
                "token": invitation_token,
            },
        )
        member_token = redeemed.json()["data"]["participantSessionToken"]

        gateway.result = _result(failure_code="LLM_TIMEOUT")
        response = await client.put(
            "/api/v2/member-session/conversation",
            headers={
                "X-Participant-Session": member_token,
                "Idempotency-Key": "t004-member-fallback-01",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": 1,
                "expectedVersion": 2,
                "naturalLanguageRequest": request.natural_language_request,
                "answers": request.model_dump(mode="json", by_alias=True)["answers"],
            },
        )
        replay = await client.put(
            "/api/v2/member-session/conversation",
            headers={
                "X-Participant-Session": member_token,
                "Idempotency-Key": "t004-member-fallback-01",
            },
            json={
                "schemaVersion": "1.0",
                "baseRevision": 1,
                "expectedVersion": 2,
                "naturalLanguageRequest": request.natural_language_request,
                "answers": request.model_dump(mode="json", by_alias=True)["answers"],
            },
        )

    assert response.status_code == 200
    assert replay.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert replay.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert replay.json()["data"] == data
    assert data["answerRevision"] == 2
    assert data["naturalLanguageRequest"] == request.natural_language_request
    assert data["answers"] == request.model_dump(mode="json", by_alias=True)["answers"]
    assert data["recognition"] == {
        "source": "FIXED_QUESTIONS",
        "model": "test-model",
        "failureCode": "LLM_TIMEOUT",
        "callCount": 2,
    }
    assert data["fallback"]["mode"] == "FIXED_QUESTIONS"
    assert len(data["fallback"]["items"]) == 6
    assert data["understanding"] is None
    assert data["canPlan"] is False
    assert gateway.calls == 2

    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT current_revision, version FROM collaboration_sessions"
        ).fetchone() == (1, 2)
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='ADVANCE_REVISION'"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_failed_member_revision_can_be_reclaimed_with_new_key_and_payload(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(proposal=_two_participant_proposal()))
    service, repository = _service(tmp_path, gateway)
    request = _request(fixture_path=FIXTURE.with_name("two_participants.json"))
    initial = await service.create_initial(request, idempotency_key="t004-reclaim-create-01")
    participant_id = initial.member_bindings["member-2"]

    gateway.result = _result(failure_code="LLM_TIMEOUT")
    fallback = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=1,
        submission=request,
        idempotency_key="t004-reclaim-fail-01",
    )
    assert fallback.answer_revision == 2
    assert gateway.calls == 2

    gateway.result = _result(proposal=_two_participant_proposal())
    revised = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=1,
        submission=_request(
            "corrected answer",
            fixture_path=FIXTURE.with_name("two_participants.json"),
        ),
        idempotency_key="t004-reclaim-retry-01",
    )

    assert isinstance(revised, TripDraftRevision)
    assert revised.revision == 2
    assert gateway.calls == 3
    assert _revision_count(repository) == 2
