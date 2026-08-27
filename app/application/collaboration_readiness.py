from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator
from uuid import UUID

from app.application.collaboration_ports import (
    CollaborationReadinessGuard,
    PlanningAccess,
    ReadinessPermit,
)
from app.application.collaboration_service import CollaborationService
from app.core.errors import AppError
from app.domain.collaboration import TripFlowKind
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.infrastructure.trip_flow_store import SqliteTripFlowRegistry


class SqliteCollaborationReadinessGuard:
    def __init__(
        self,
        *,
        database_path: Path | None,
        repository: SqliteCollaborationRepository,
        collaboration: CollaborationService,
        flow_registry: object | None = None,
        provider_timeout_seconds: float = 8.0,
        candidate_timeout_seconds: float = 10.0,
    ) -> None:
        self.repository = repository
        self.collaboration = collaboration
        self.flow_registry = flow_registry or SqliteTripFlowRegistry(
            database_path or repository._path
        )
        self.lease_ttl = timedelta(
            seconds=max(provider_timeout_seconds, candidate_timeout_seconds, 55) + 5
        )

    @staticmethod
    def _unknown_flow(trip_id: UUID) -> AppError:
        return AppError(
            "TRIP_FLOW_SCOPE_UNKNOWN",
            "TRIP_FLOW_SCOPE_UNKNOWN: 行程流程范围未显式登记，已拒绝继续",
            409,
            False,
        )

    @staticmethod
    def _legacy_permit(access: PlanningAccess, ttl: timedelta) -> ReadinessPermit:
        return ReadinessPermit(
            trip_id=access.trip_id,
            readiness_digest="legacy",
            operation_id=access.operation_id,
            operation=access.operation,
            flow_kind=TripFlowKind.LEGACY_SINGLE,
            expires_at=datetime.now(UTC) + ttl,
        )

    @contextmanager
    def operation(self, access: PlanningAccess) -> Iterator[ReadinessPermit]:
        flow = self.flow_registry.get(access.trip_id)
        if flow is TripFlowKind.LEGACY_SINGLE:
            if not self.flow_registry.is_strict_confirmed_single(access.trip_id):
                raise self._unknown_flow(access.trip_id)
            yield self._legacy_permit(access, self.lease_ttl)
            return
        if flow is not TripFlowKind.COLLABORATION_V2:
            raise self._unknown_flow(access.trip_id)
        digest = self.collaboration.require_ready(
            access.trip_id,
            access.organizer_capability,
        )
        permit = self.repository.acquire_lease(
            access=access,
            readiness_digest=digest,
            ttl=self.lease_ttl,
        )
        try:
            yield permit
        finally:
            self.repository.complete_lease(permit.operation_id)


__all__ = [
    "CollaborationReadinessGuard",
    "SqliteCollaborationReadinessGuard",
]
