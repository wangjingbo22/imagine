from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from app.application.collaboration_service import CollaborationService
from app.application.plan_service import PlanVersionService
from app.core.errors import AppError
from app.domain.parent_trip import ParentTrip, ParentTripCreateRequest, ParentTripDay
from app.infrastructure.parent_trip_store import ParentTripStoreError, SqliteParentTripRepository
from app.infrastructure.trip_draft_revision_store import TripDraftRevisionStoreError, SqliteTripDraftRevisionRepository


class ParentTripService:
    def __init__(self, repository: SqliteParentTripRepository,
                 revisions: SqliteTripDraftRevisionRepository,
                 collaboration: CollaborationService, plans: PlanVersionService) -> None:
        self.repository, self.revisions = repository, revisions
        self.collaboration, self.plans = collaboration, plans

    @staticmethod
    def _error(error: Exception) -> AppError:
        code = str(error)
        status = 404 if code.endswith("NOT_FOUND") else 403 if "PERMISSION" in code else 409
        messages = {
            "PARENT_TRIP_NOT_FOUND": "未找到父行程。",
            "PARENT_TRIP_PERMISSION_REQUIRED": "缺少有效的父行程组织者凭证。",
            "PARENT_TRIP_DAY_IMMUTABLE": "该日期已经绑定子行程，不能覆盖。",
            "CHILD_TRIP_ALREADY_LINKED": "该单日行程已经绑定到其他日期。",
        }
        return AppError(code, messages.get(code, "父行程操作无法完成。"), status, False)

    def create(self, request: ParentTripCreateRequest, token: str) -> ParentTrip:
        try:
            self.repository.create(request, token)
            return self.get(request.parent_trip_id, token)
        except ParentTripStoreError as error:
            raise self._error(error) from error

    def link_day(self, parent_id: UUID, day_index: int, child_id: UUID,
                 parent_token: str, child_token: str) -> ParentTrip:
        try:
            parent, days = self.repository.authorized_rows(parent_id, parent_token)
            if day_index < 0 or day_index >= len(days):
                raise ParentTripStoreError("PARENT_TRIP_DAY_NOT_FOUND")
            self.collaboration.organizer_state(child_id, child_token)
            revision = self.revisions.get_current(child_id)
            trip = revision.understanding.trip
            expected = date.fromisoformat(days[day_index]["travel_date"])
            if trip.city_name != parent["city_name"] or trip.travel_date != expected:
                raise AppError("PARENT_CHILD_SCOPE_MISMATCH",
                    "子行程必须与父行程同城，并对应所选日期。", 422, False)
            if trip.budget_cents is None or trip.budget_cents > days[day_index]["budget_cents"]:
                raise AppError("PARENT_CHILD_BUDGET_EXCEEDED",
                    "子行程预算不能超过该日分配预算。", 422, False)
            self.repository.link(parent_id, day_index, child_id, parent_token)
            return self.get(parent_id, parent_token)
        except ParentTripStoreError as error:
            raise self._error(error) from error

    def get(self, parent_id: UUID, token: str) -> ParentTrip:
        try:
            parent, rows = self.repository.authorized_rows(parent_id, token)
        except ParentTripStoreError as error:
            raise self._error(error) from error
        output, planned_values, actual_values = [], [], []
        for row in rows:
            child_id = UUID(row["child_trip_id"]) if row["child_trip_id"] else None
            values = dict(child_budget_cents=None, planned_cost_cents=None,
                          actual_spent_cents=None, remaining_budget_cents=None,
                          child_status="NOT_CREATED", cost_status="NOT_AVAILABLE")
            if child_id:
                revision = self.revisions.get_current(child_id)
                child_trip = revision.understanding.trip
                expected_date = date.fromisoformat(row["travel_date"])
                if child_trip.city_name != parent["city_name"] or child_trip.travel_date != expected_date:
                    raise AppError("PARENT_CHILD_SCOPE_DRIFT",
                        "已绑定的子行程城市或日期已偏离父行程，已停止汇总。", 409, False)
                if child_trip.budget_cents is None or child_trip.budget_cents > row["budget_cents"]:
                    raise AppError("PARENT_CHILD_BUDGET_DRIFT",
                        "已绑定的子行程预算已超过该日分配预算，已停止汇总。", 409, False)
                values["child_budget_cents"] = child_trip.budget_cents
                try:
                    state = self.plans.get_trip_state(child_id)
                    values["child_status"] = state.trip_status.value
                    if state.current_plan:
                        values["planned_cost_cents"] = state.current_plan.metrics.total_cost_cents
                        planned_values.append(values["planned_cost_cents"])
                        values["cost_status"] = "PLANNED"
                    if state.actual_budget and state.actual_budget.expense_event_count > 0:
                        values["actual_spent_cents"] = state.actual_budget.actual_spent_cents
                        actual_values.append(values["actual_spent_cents"])
                        values["remaining_budget_cents"] = row["budget_cents"] - values["actual_spent_cents"]
                        values["cost_status"] = "ACTUAL_RECORDED"
                except AppError as error:
                    if error.code != "TRIP_NOT_FOUND": raise
            output.append(ParentTripDay(day_index=row["day_index"], date=row["travel_date"],
                budget_cents=row["budget_cents"], child_trip_id=child_id, **values))
        start = date.fromisoformat(parent["start_date"])
        return ParentTrip(parent_trip_id=parent_id, title=parent["title"], city_name=parent["city_name"],
            start_date=start, end_date=start + timedelta(days=len(rows)-1),
            total_budget_cents=sum(row["budget_cents"] for row in rows),
            planned_cost_cents=sum(planned_values) if planned_values else None,
            actual_spent_cents=sum(actual_values) if actual_values else None, days=output)
