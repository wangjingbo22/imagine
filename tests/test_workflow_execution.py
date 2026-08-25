import copy
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.infrastructure.plan_store import PlanStoreError, SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.execution import CreateExecutionEvent, ExecutionEventType
from app.schemas.plan import ProposedPlanVersion
from app.schemas.trip import AssistanceProfile
from app.schemas.workflow import ConstraintProfileStatus
from tests.test_plan_versions import UnusedLocationService, proposal_payload


def low_stamina_profile() -> AssistanceProfile:
    path = (
        Path(__file__).parents[1]
        / "backend"
        / "tests"
        / "fixtures"
        / "assistance_profiles"
        / "low_stamina.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AssistanceProfile.model_validate_json(
        json.dumps(
            payload["participants"][0]["assistanceProfile"],
            ensure_ascii=False,
        ),
        strict=True,
    )


def build_services(tmp_path: Path) -> tuple[PlanVersionService, WorkflowService]:
    database_path = tmp_path / "workflow.sqlite3"
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    plan = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    return plan, workflow


def proposal_with_profile(profile: AssistanceProfile) -> ProposedPlanVersion:
    payload = copy.deepcopy(proposal_payload())
    payload["tripSnapshot"]["participants"][0][  # type: ignore[index]
        "assistanceProfile"
    ] = profile.model_dump(mode="json", by_alias=True)
    return ProposedPlanVersion.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def setup_execution(tmp_path: Path):
    plan_service, workflow_service = build_services(tmp_path)
    profile = low_stamina_profile()
    proposal = proposal_with_profile(profile)
    workflow_service.save_constraint_draft(
        proposal.trip_snapshot.trip_id,
        profile,
    )
    workflow_service.confirm_constraints(proposal.trip_snapshot.trip_id)
    plan_service.register_proposed(proposal)
    plan_service.confirm(proposal.trip_snapshot.trip_id, proposal.plan_id)
    plan_service.start_execution(proposal.trip_snapshot.trip_id)
    return plan_service, workflow_service, proposal


def event_request(
    proposal: ProposedPlanVersion,
    task_id: str,
    event_type: ExecutionEventType,
    key: str,
    amount_cents: int | None = None,
) -> CreateExecutionEvent:
    return CreateExecutionEvent(
        task_id=task_id,
        plan_version_id=proposal.plan_id,
        event_type=event_type,
        amount_cents=amount_cents,
        idempotency_key=key,
    )


def test_constraint_confirmation_is_idempotent_and_edit_returns_draft(
    tmp_path: Path,
) -> None:
    plan_service, workflow = build_services(tmp_path)
    profile = low_stamina_profile()
    trip_id = proposal_with_profile(profile).trip_snapshot.trip_id

    with pytest.raises(PlanStoreError) as missing:
        workflow.repository.require_constraint_confirmed(trip_id, profile)
    assert missing.value.code == "CONSTRAINTS_NOT_CONFIRMED"

    draft = workflow.save_constraint_draft(trip_id, profile)
    assert draft.status is ConstraintProfileStatus.DRAFT
    first = workflow.confirm_constraints(trip_id)
    second = workflow.confirm_constraints(trip_id)
    assert first.confirmed_at == second.confirmed_at

    changed = profile.model_copy(
        update={"max_transfers": 1},
    )
    reverted = workflow.save_constraint_draft(trip_id, changed)
    assert reverted.status is ConstraintProfileStatus.DRAFT
    with pytest.raises(PlanStoreError):
        workflow.repository.require_constraint_confirmed(trip_id, changed)

    with pytest.raises(Exception, match="尚未确认"):
        plan_service.register_proposed(proposal_with_profile(changed))


def test_confirmed_profile_allows_plan_and_mismatch_is_rejected(tmp_path: Path) -> None:
    plan_service, workflow = build_services(tmp_path)
    profile = low_stamina_profile()
    proposal = proposal_with_profile(profile)
    workflow.save_constraint_draft(proposal.trip_snapshot.trip_id, profile)
    workflow.confirm_constraints(proposal.trip_snapshot.trip_id)

    registered = plan_service.register_proposed(proposal)
    assert registered.plan_id == proposal.plan_id

    different = profile.model_copy(update={"rest_interval": 60})
    mismatch = proposal_with_profile(different)
    mismatch = mismatch.model_copy(
        update={"plan_id": UUID("20000000-0000-4000-8000-000000000099")}
    )
    with pytest.raises(Exception, match="不一致"):
        plan_service.register_proposed(mismatch)


def test_execution_events_are_idempotent_and_restore_from_sqlite(tmp_path: Path) -> None:
    _, workflow, proposal = setup_execution(tmp_path)
    trip_id = proposal.trip_snapshot.trip_id
    start = event_request(proposal, "task-1", ExecutionEventType.START, "start-task-1")

    first = workflow.create_event(trip_id, start)
    second = workflow.create_event(trip_id, start)
    assert first.event_id == second.event_id
    assert workflow.list_events(trip_id) == [first]

    conflicting = event_request(
        proposal,
        "task-2",
        ExecutionEventType.START,
        "start-task-1",
    )
    with pytest.raises(Exception, match="不同事件"):
        workflow.create_event(trip_id, conflicting)

    reopened = WorkflowService(
        SqliteWorkflowRepository(tmp_path / "workflow.sqlite3")
    )
    assert reopened.list_events(trip_id)[0].event_id == first.event_id


def test_execution_summary_uses_event_stream_and_completes_trip(tmp_path: Path) -> None:
    plan_service, workflow, proposal = setup_execution(tmp_path)
    trip_id = proposal.trip_snapshot.trip_id
    tasks = proposal.days[0].tasks

    for index, task in enumerate(tasks):
        workflow.create_event(
            trip_id,
            event_request(
                proposal,
                task.task_id,
                ExecutionEventType.START,
                f"start-{task.task_id}",
            ),
        )
        if index != 2:
            workflow.create_event(
                trip_id,
                event_request(
                    proposal,
                    task.task_id,
                    ExecutionEventType.EXPENSE,
                    f"expense-{task.task_id}",
                    task.cost_cents,
                ),
            )
        terminal_type = (
            ExecutionEventType.SKIP if index == 2 else ExecutionEventType.COMPLETE
        )
        workflow.create_event(
            trip_id,
            event_request(
                proposal,
                task.task_id,
                terminal_type,
                f"terminal-{task.task_id}",
            ),
        )

    state = plan_service.get_trip_state(trip_id)
    assert state.trip_status == "COMPLETED"
    assert len(state.events) == 11
    summary = workflow.get_summary(trip_id)
    assert summary.completed_task_ids == ["task-1", "task-2", "task-4"]
    assert summary.skipped_task_ids == ["task-3"]
    assert summary.actual_cost_cents == 29_400
    assert summary.difference_cents == -400
    assert summary.current_plan_version == 1


@pytest.mark.asyncio
async def test_constraint_and_event_http_flow_refreshes_state(tmp_path: Path) -> None:
    plan_service, workflow_service = build_services(tmp_path)
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plan_service,
        workflow_service=workflow_service,
    )
    proposal = proposal_with_profile(low_stamina_profile())
    trip_id = str(proposal.trip_snapshot.trip_id)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        saved = await client.put(
            f"/api/v1/trips/{trip_id}/constraints",
            json=proposal.trip_snapshot.participants[0].assistance_profile.model_dump(
                mode="json",
                by_alias=True,
            ),
        )
        confirmed = await client.post(
            f"/api/v1/trips/{trip_id}/constraints/confirm"
        )
        # This test targets the workflow/event boundary. Plan setup deliberately
        # stays at the application-service layer; HTTP Plan confirmation is
        # covered by the trusted planning-boundary regression suite.
        registered = plan_service.register_proposed(proposal)
        plan_service.confirm(proposal.trip_snapshot.trip_id, proposal.plan_id)
        plan_service.start_execution(proposal.trip_snapshot.trip_id)
        event_payload = {
            "taskId": "task-1",
            "planVersionId": str(proposal.plan_id),
            "eventType": "START",
            "amountCents": None,
            "idempotencyKey": "http-start-task-1",
        }
        first = await client.post(f"/api/v1/trips/{trip_id}/events", json=event_payload)
        second = await client.post(f"/api/v1/trips/{trip_id}/events", json=event_payload)
        restored = await client.get(f"/api/v1/trips/{trip_id}")

    assert saved.json()["data"]["status"] == "DRAFT"
    assert confirmed.json()["data"]["status"] == "CONSTRAINT_CONFIRMED"
    assert registered.status.value == "PROPOSED"
    assert first.json()["data"]["eventId"] == second.json()["data"]["eventId"]
    assert restored.json()["data"]["events"][0]["eventType"] == "START"
