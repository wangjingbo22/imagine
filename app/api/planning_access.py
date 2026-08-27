from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Request

from app.application.collaboration_ports import PlanningAccess, PlanningOperation


def build_planning_access(
    request: Request,
    trip_id: UUID,
    operation: PlanningOperation,
) -> PlanningAccess:
    return PlanningAccess(
        trip_id=trip_id,
        organizer_capability=request.headers.get("X-Organizer-Token"),
        operation_id=request.headers.get("Idempotency-Key") or f"http-{uuid4()}",
        operation=operation,
    )


__all__ = ["build_planning_access"]
