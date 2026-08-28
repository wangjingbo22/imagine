from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
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
        revision = self.collaboration.ready_revision(
            access.trip_id,
            access.organizer_capability,
        )
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
            # A collaboration mutation can race between the initial readiness
            # check and lease acquisition.  Once the lease exists, mutations
            # are blocked; re-reading here binds the permit to that exact ready
            # revision or fails before any Provider/planner/state call.
            leased_revision = self.collaboration.ready_revision(
                access.trip_id,
                access.organizer_capability,
            )
            leased_digest = self.collaboration.require_ready(
                access.trip_id,
                access.organizer_capability,
            )
            if (
                leased_digest != digest
                or leased_revision.revision != revision.revision
            ):
                raise AppError(
                    "COLLABORATION_READY_CONTEXT_STALE",
                    "协作需求在规划操作开始前已变化，请重新生成候选",
                    409,
                    False,
                )
            yield replace(
                permit,
                readiness_digest=leased_digest,
                current_revision=leased_revision.revision,
            )
        finally:
            self.repository.complete_lease(permit.operation_id)


__all__ = [
    "CollaborationReadinessGuard",
    "SqliteCollaborationReadinessGuard",
]
