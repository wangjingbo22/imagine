from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from unicodedata import normalize
from uuid import UUID

from app.application.collaboration_service import CollaborationService
from app.application.plan_service import PlanVersionService
from app.core.errors import AppError
from app.domain.parent_trip import (
    ParentTrip,
    ParentTripCreateRequest,
    ParentTripDay,
    ParentTripDayBudgetUpdate,
    ParentTripInvitationCreated,
    ParentTripInvitationRedeemed,
    ParentTripMemberProfile,
    ParentTripMemberProfileUpdate,
    ParentTripPlaceMemoryItem,
    ParentTripSyncView,
)
from app.infrastructure.parent_trip_store import (
    ParentTripActor,
    ParentTripStoreError,
    SqliteParentTripRepository,
)
from app.infrastructure.trip_draft_revision_store import (
    SqliteTripDraftRevisionRepository,
)


class ParentTripService:
    def __init__(
        self,
        repository: SqliteParentTripRepository,
        revisions: SqliteTripDraftRevisionRepository,
        collaboration: CollaborationService,
        plans: PlanVersionService,
        today: Callable[[], date] | None = None,
    ) -> None:
        self.repository = repository
        self.revisions = revisions
        self.collaboration = collaboration
        self.plans = plans
        self._today = today or date.today

    @staticmethod
    def _error(error: Exception) -> AppError:
        code = str(error)
        status = {
            "PARENT_TRIP_NOT_FOUND": 404,
            "PARENT_TRIP_DAY_NOT_FOUND": 404,
            "PARENT_INVITATION_UNAVAILABLE": 404,
            "PARENT_INVITATION_EXPIRED": 410,
            "PARENT_INVITATION_ACCOUNT_MISMATCH": 403,
            "PARENT_TRIP_PERMISSION_REQUIRED": 403,
            "PARENT_MEMBER_PERMISSION_REQUIRED": 403,
            "PARENT_MEMBER_SESSION_REQUIRED": 401,
            "PARENT_MEMBER_SESSION_INVALID": 401,
            "PARENT_MEMBER_SESSION_EXPIRED": 401,
        }.get(code, 409)
        messages = {
            "PARENT_TRIP_NOT_FOUND": "未找到父行程。",
            "PARENT_TRIP_PERMISSION_REQUIRED": "缺少有效的父行程组织者凭证。",
            "PARENT_TRIP_DAY_NOT_FOUND": "未找到父行程中的对应日期。",
            "PARENT_TRIP_DAY_IMMUTABLE": "该日期已经绑定子行程，不能覆盖。",
            "CHILD_TRIP_ALREADY_LINKED": "该单日行程已经绑定到其他日期。",
            "PARENT_TRIP_VERSION_CONFLICT": "父行程协作版本已更新，请刷新后重试。",
            "PARENT_TRIP_MEMBER_LIMIT": "父行程最多包含组织者和两名成员。",
            "PARENT_IDEMPOTENCY_KEY_REUSED": "幂等键已用于不同的父行程邀请请求。",
            "PARENT_INVITATION_UNAVAILABLE": "父行程邀请不存在或已失效。",
            "PARENT_INVITATION_EXPIRED": "父行程邀请已过期。",
            "PARENT_INVITATION_ALREADY_REDEEMED": "父行程邀请已经被其他会话使用。",
            "PARENT_INVITATION_ACCOUNT_MISMATCH": "该邀请已由其他账号兑换。",
            "PARENT_ACCOUNT_ALREADY_MEMBER": "当前账号已经加入该父行程。",
            "PARENT_MEMBER_SESSION_REQUIRED": "缺少父行程成员会话凭证。",
            "PARENT_MEMBER_SESSION_INVALID": "父行程成员会话无效。",
            "PARENT_MEMBER_SESSION_EXPIRED": "父行程成员会话已过期。",
            "PARENT_MEMBER_PERMISSION_REQUIRED": "当前成员只能修改自己的资料。",
        }
        return AppError(code, messages.get(code, "父行程操作无法完成。"), status, False)

    def create(self, request: ParentTripCreateRequest, token: str) -> ParentTrip:
        if request.start_date < self._today():
            raise AppError(
                "PARENT_TRIP_DATE_IN_PAST",
                "父行程开始日期不能早于今天。",
                422,
                False,
            )
        try:
            self.repository.create(request, token)
            return self.get(request.parent_trip_id, token)
        except ParentTripStoreError as error:
            raise self._error(error) from error

    def link_day(
        self,
        parent_id: UUID,
        day_index: int,
        child_id: UUID,
        parent_token: str,
        child_token: str,
    ) -> ParentTrip:
        try:
            parent, days = self.repository.authorized_rows(parent_id, parent_token)
            if day_index < 0 or day_index >= len(days):
                raise ParentTripStoreError("PARENT_TRIP_DAY_NOT_FOUND")
            self.collaboration.organizer_state(child_id, child_token)
            revision = self.revisions.get_current(child_id)
            trip = revision.understanding.trip
            expected = date.fromisoformat(days[day_index]["travel_date"])
            if trip.city_name != parent["city_name"] or trip.travel_date != expected:
                raise AppError(
                    "PARENT_CHILD_SCOPE_MISMATCH",
                    "子行程必须与父行程同城，并对应所选日期。",
                    422,
                    False,
                )
            if trip.budget_cents is None or trip.budget_cents > days[day_index]["budget_cents"]:
                raise AppError(
                    "PARENT_CHILD_BUDGET_EXCEEDED",
                    "子行程预算不能超过该日分配预算。",
                    422,
                    False,
                )
            self.repository.link(parent_id, day_index, child_id, parent_token)
            return self.get(parent_id, parent_token)
        except ParentTripStoreError as error:
            raise self._error(error) from error

    def update_day_budget(
        self,
        parent_id: UUID,
        day_index: int,
        request: ParentTripDayBudgetUpdate,
        parent_token: str,
    ) -> ParentTrip:
        try:
            _, days = self.repository.authorized_rows(parent_id, parent_token)
            if day_index < 0 or day_index >= len(days):
                raise ParentTripStoreError("PARENT_TRIP_DAY_NOT_FOUND")
            child_id_value = days[day_index]["child_trip_id"]
            if child_id_value:
                revision = self.revisions.get_current(UUID(str(child_id_value)))
                child_budget = revision.understanding.trip.budget_cents
                if child_budget is not None and request.budget_cents < child_budget:
                    raise AppError(
                        "PARENT_DAY_BUDGET_BELOW_CHILD",
                        "新预算不能低于已经创建的当日行程预算。",
                        422,
                        False,
                    )
            self.repository.update_day_budget(
                parent_id,
                day_index,
                request.budget_cents,
                parent_token,
            )
            return self.get(parent_id, parent_token)
        except ParentTripStoreError as error:
            raise self._error(error) from error

    @staticmethod
    def _normalized_place_value(value: str) -> str:
        return " ".join(normalize("NFKC", value).strip().casefold().split())

    @staticmethod
    def _memory_plan(state: object) -> tuple[object, str] | None:
        current = getattr(state, "current_plan", None)
        if current is not None:
            return current, "CURRENT"
        for plan in reversed(getattr(state, "proposed_plans", ())):
            if getattr(plan, "version", None) == 1:
                return plan, "PROPOSED"
        return None

    def _place_memory_from_rows(
        self,
        rows: Sequence[dict[str, object]],
    ) -> tuple[ParentTripPlaceMemoryItem, ...]:
        memory: list[ParentTripPlaceMemoryItem] = []
        seen_ids: set[tuple[int, str]] = set()
        seen_names: set[tuple[int, str]] = set()
        for row in rows:
            if row["child_trip_id"] is None:
                continue
            sibling_id = UUID(str(row["child_trip_id"]))
            try:
                state = self.plans.get_trip_state(sibling_id)
            except AppError as error:
                if error.code == "TRIP_NOT_FOUND":
                    continue
                raise
            selected = self._memory_plan(state)
            if selected is None:
                continue
            plan, plan_status = selected
            for day in plan.days:
                for task in day.tasks:
                    place_id = task.task_id.strip()
                    place_name = task.title.strip()
                    category = task.category.strip().upper()
                    if (
                        not place_id
                        or not place_name
                        or category == "RETURN"
                        or self._normalized_place_value(place_id).startswith("return-")
                    ):
                        continue
                    id_identity = (
                        int(row["day_index"]),
                        self._normalized_place_value(place_id),
                    )
                    name_identity = (
                        int(row["day_index"]),
                        self._normalized_place_value(place_name),
                    )
                    if id_identity in seen_ids or name_identity in seen_names:
                        continue
                    seen_ids.add(id_identity)
                    seen_names.add(name_identity)
                    memory.append(ParentTripPlaceMemoryItem(
                        dayIndex=row["day_index"],
                        date=row["travel_date"],
                        childTripId=sibling_id,
                        planId=plan.plan_id,
                        planStatus=plan_status,
                        placeId=place_id,
                        placeName=place_name,
                    ))
        return tuple(memory)

    def place_memory_for_child(
        self,
        child_id: UUID,
    ) -> tuple[ParentTripPlaceMemoryItem, ...]:
        """Project attraction tasks already assigned to sibling days."""
        return self._place_memory_from_rows(
            self.repository.sibling_rows_for_child(child_id)
        )

    def used_place_names_for_child(self, child_id: UUID) -> tuple[str, ...]:
        """Compatibility projection for callers that only consume names."""
        return tuple(item.place_name for item in self.place_memory_for_child(child_id))

    def require_unique_candidate_places(
        self,
        child_id: UUID,
        task_facts: Sequence[object],
    ) -> None:
        """Reject a plan that reuses an attraction assigned to a sibling day."""
        memory = self.place_memory_for_child(child_id)
        if not memory:
            return
        by_id = {
            self._normalized_place_value(item.place_id): item
            for item in memory
        }
        by_name = {
            self._normalized_place_value(item.place_name): item
            for item in memory
        }
        conflicts: list[dict[str, object]] = []
        for index, task in enumerate(task_facts):
            task_id = str(getattr(task, "task_id", "")).strip()
            title = str(getattr(task, "title", "")).strip()
            category = str(getattr(task, "category", "")).strip().upper()
            place = getattr(task, "place", None)
            provider_id = str(getattr(place, "placeId", task_id)).strip()
            if (
                category == "RETURN"
                or self._normalized_place_value(task_id).startswith("return-")
            ):
                continue
            remembered = by_id.get(self._normalized_place_value(provider_id))
            if remembered is None:
                remembered = by_name.get(self._normalized_place_value(title))
            if remembered is None:
                continue
            conflicts.append({
                "field": f"taskFacts[{index}]",
                "placeId": provider_id,
                "placeName": title,
                "conflictingDayIndex": remembered.day_index,
                "conflictingDate": remembered.date.isoformat(),
                "conflictingChildTripId": str(remembered.child_trip_id),
                "conflictingPlanId": str(remembered.plan_id),
                "conflictingPlaceId": remembered.place_id,
                "conflictingPlaceName": remembered.place_name,
            })
        if conflicts:
            first_day = int(conflicts[0]["conflictingDayIndex"]) + 1
            raise AppError(
                "PARENT_TRIP_PLACE_REUSED",
                f"所选地点已安排在父行程第 {first_day} 天，请更换地点后重试。",
                409,
                False,
                conflicts,
            )

    def _build_parent(
        self,
        parent_id: UUID,
        parent: dict[str, object],
        rows: list[dict[str, object]],
    ) -> ParentTrip:
        output: list[ParentTripDay] = []
        planned_values: list[int] = []
        actual_values: list[int] = []
        for row in rows:
            child_id = UUID(str(row["child_trip_id"])) if row["child_trip_id"] else None
            values: dict[str, object] = {
                "child_budget_cents": None,
                "planned_cost_cents": None,
                "actual_spent_cents": None,
                "remaining_budget_cents": None,
                "child_status": "NOT_CREATED",
                "cost_status": "NOT_AVAILABLE",
            }
            if child_id:
                revision = self.revisions.get_current(child_id)
                child_trip = revision.understanding.trip
                expected_date = date.fromisoformat(str(row["travel_date"]))
                if child_trip.city_name != parent["city_name"] or child_trip.travel_date != expected_date:
                    raise AppError(
                        "PARENT_CHILD_SCOPE_DRIFT",
                        "已绑定的子行程城市或日期已偏离父行程，已停止汇总。",
                        409,
                        False,
                    )
                if child_trip.budget_cents is None or child_trip.budget_cents > row["budget_cents"]:
                    raise AppError(
                        "PARENT_CHILD_BUDGET_DRIFT",
                        "已绑定的子行程预算已超过该日分配预算，已停止汇总。",
                        409,
                        False,
                    )
                values["child_budget_cents"] = child_trip.budget_cents
                try:
                    state = self.plans.get_trip_state(child_id)
                    values["child_status"] = state.trip_status.value
                    if state.current_plan:
                        planned_cost = state.current_plan.metrics.total_cost_cents
                        values["planned_cost_cents"] = planned_cost
                        planned_values.append(planned_cost)
                        values["cost_status"] = "PLANNED"
                    if state.actual_budget and state.actual_budget.expense_event_count > 0:
                        actual_spent = state.actual_budget.actual_spent_cents
                        values["actual_spent_cents"] = actual_spent
                        actual_values.append(actual_spent)
                        values["remaining_budget_cents"] = int(row["budget_cents"]) - actual_spent
                        values["cost_status"] = "ACTUAL_RECORDED"
                except AppError as error:
                    if error.code != "TRIP_NOT_FOUND":
                        raise
            output.append(ParentTripDay(
                dayIndex=row["day_index"],
                date=row["travel_date"],
                budgetCents=row["budget_cents"],
                childTripId=child_id,
                **values,
            ))
        start = date.fromisoformat(str(parent["start_date"]))
        return ParentTrip(
            parentTripId=parent_id,
            title=parent["title"],
            cityName=parent["city_name"],
            startDate=start,
            endDate=start + timedelta(days=len(rows) - 1),
            totalBudgetCents=sum(int(row["budget_cents"]) for row in rows),
            plannedCostCents=sum(planned_values) if planned_values else None,
            actualSpentCents=sum(actual_values) if actual_values else None,
            days=output,
            placeMemory=self._place_memory_from_rows(rows),
        )

    def get(self, parent_id: UUID, token: str) -> ParentTrip:
        try:
            parent, rows = self.repository.authorized_rows(parent_id, token)
            return self._build_parent(parent_id, parent, rows)
        except ParentTripStoreError as error:
            raise self._error(error) from error

    @staticmethod
    def _profile(row: dict[str, object]) -> ParentTripMemberProfile:
        interests = json.loads(str(row["interests_json"]))
        if not isinstance(interests, list) or any(not isinstance(item, str) for item in interests):
            raise AppError(
                "PARENT_MEMBER_PROFILE_CORRUPT",
                "成员资料无法读取，已停止同步。",
                500,
                False,
            )
        return ParentTripMemberProfile(
            participantId=row["participant_id"],
            role=row["role"],
            accessStatus=row["access_status"],
            nickname=row["nickname"],
            interests=interests,
            budgetCapCents=row["budget_cap_cents"],
            profileVersion=row["profile_version"],
            updatedAt=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _sync_from_rows(
        self,
        parent_id: UUID,
        parent: dict[str, object],
        rows: list[dict[str, object]],
        actor: ParentTripActor,
        sync: dict[str, object],
        profiles: list[dict[str, object]],
    ) -> ParentTripSyncView:
        return ParentTripSyncView(
            parentTrip=self._build_parent(parent_id, parent, rows),
            syncVersion=sync["version"],
            viewerRole=actor.role,
            viewerParticipantId=actor.participant_id,
            visibleProfiles=[self._profile(row) for row in profiles],
            changedAt=datetime.fromisoformat(str(sync["updated_at"])),
        )

    def sync(
        self,
        parent_id: UUID,
        *,
        organizer_token: str | None = None,
        member_session_token: str | None = None,
    ) -> ParentTripSyncView:
        try:
            return self._sync_from_rows(
                parent_id,
                *self.repository.collaboration_rows(
                    parent_id,
                    organizer_token=organizer_token,
                    member_session_token=member_session_token,
                ),
            )
        except ParentTripStoreError as error:
            raise self._error(error) from error

    def create_invitation(
        self,
        parent_id: UUID,
        *,
        organizer_token: str,
        expected_sync_version: int,
        expires_in_hours: int,
        idempotency_key: str,
    ) -> ParentTripInvitationCreated:
        try:
            row, secret = self.repository.create_invitation(
                parent_trip_id=parent_id,
                organizer_token=organizer_token,
                expected_sync_version=expected_sync_version,
                expires_in_hours=expires_in_hours,
                idempotency_key=idempotency_key,
            )
        except ParentTripStoreError as error:
            raise self._error(error) from error
        return ParentTripInvitationCreated(
            invitationId=row["invitation_id"],
            parentTripId=row["parent_trip_id"],
            participantId=row["participant_id"],
            invitationUrl=f"/parent-join/{secret}" if secret else None,
            expiresAt=datetime.fromisoformat(str(row["expires_at"])),
            linkAvailable=secret is not None,
            syncVersion=row["sync_version"],
        )

    def redeem_invitation(
        self,
        *,
        token: str,
        idempotency_key: str,
        account_user_id: UUID | None,
        display_name: str,
        interests: list[str],
    ) -> ParentTripInvitationRedeemed:
        try:
            row, session_secret = self.repository.redeem_invitation(
                token=token,
                idempotency_key=idempotency_key,
                account_user_id=account_user_id,
                display_name=display_name,
                interests=interests,
            )
        except ParentTripStoreError as error:
            raise self._error(error) from error
        return ParentTripInvitationRedeemed(
            sessionId=row["session_id"],
            parentTripId=row["parent_trip_id"],
            participantId=row["participant_id"],
            memberSessionToken=session_secret,
            expiresAt=datetime.fromisoformat(str(row["expires_at"])),
            sessionTokenAvailable=True,
            syncVersion=row["sync_version"],
        )

    def update_member_profile(
        self,
        parent_id: UUID,
        *,
        member_session_token: str,
        request: ParentTripMemberProfileUpdate,
    ) -> ParentTripSyncView:
        try:
            self.repository.update_member_profile(
                parent_id,
                member_session_token=member_session_token,
                expected_sync_version=request.expected_sync_version,
                nickname=request.nickname,
                interests=request.interests,
                budget_cap_cents=request.budget_cap_cents,
            )
            return self.sync(
                parent_id,
                member_session_token=member_session_token,
            )
        except ParentTripStoreError as error:
            raise self._error(error) from error
