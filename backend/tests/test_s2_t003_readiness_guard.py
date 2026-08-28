from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.application.collaboration_ports import (
    PlanningAccess,
    PlanningOperation,
    ReadinessPermit,
)
from app.application.collaboration_readiness import SqliteCollaborationReadinessGuard
from app.core.errors import AppError
from app.domain.collaboration import TripFlowKind
from app.infrastructure.collaboration_store import CollaborationStoreError
from app.infrastructure.trip_flow_store import SqliteTripFlowRegistry
from backend.tests.test_s2_t003_collaboration_service import _ready_harness


TRIP_ID = UUID("30000000-0000-4000-8000-000000000001")


class FakeFlowRegistry:
    def __init__(self, flow: TripFlowKind | None) -> None:
        self.flow = flow
        self.strict_single = False

    def get(self, trip_id: UUID) -> TripFlowKind | None:
        return self.flow

    def is_strict_confirmed_single(self, trip_id: UUID) -> bool:
        return self.strict_single


class FakeCollaboration:
    def require_ready(self, trip_id: UUID, organizer_capability: str | None) -> str:
        return "a" * 64

    def ready_revision(self, trip_id: UUID, organizer_capability: str | None):
        return SimpleNamespace(revision=1)


class FakeLeaseRepository:
    def __init__(self) -> None:
        self.leases: dict[str, ReadinessPermit] = {}

    def acquire_lease(self, *, access, readiness_digest, ttl):
        permit = ReadinessPermit(
            trip_id=access.trip_id,
            readiness_digest=readiness_digest,
            operation_id=access.operation_id,
            operation=access.operation,
            flow_kind=TripFlowKind.COLLABORATION_V2,
            expires_at=datetime.now(UTC) + ttl,
        )
        self.leases[permit.operation_id] = permit
        return permit

    def complete_lease(self, operation_id: str) -> None:
        self.leases.pop(operation_id, None)


def _access(operation: PlanningOperation = PlanningOperation.PROVIDER_FACTS) -> PlanningAccess:
    return PlanningAccess(
        trip_id=TRIP_ID,
        organizer_capability=None,
        operation_id="op-unknown-0001",
        operation=operation,
    )


def _guard(flow: TripFlowKind | None) -> tuple[SqliteCollaborationReadinessGuard, FakeFlowRegistry, FakeLeaseRepository]:
    registry = FakeFlowRegistry(flow)
    repository = FakeLeaseRepository()
    return (
        SqliteCollaborationReadinessGuard(
            database_path=None,
            repository=repository,
            collaboration=FakeCollaboration(),
            flow_registry=registry,
        ),
        registry,
        repository,
    )


def test_unknown_flow_fails_closed_without_running_body() -> None:
    guard, _, _ = _guard(None)
    calls = 0
    with pytest.raises(AppError) as captured:
        with guard.operation(_access()):
            calls += 1
    assert captured.value.code == "TRIP_FLOW_SCOPE_UNKNOWN"
    assert calls == 0


def test_explicit_legacy_single_passes_but_forged_legacy_group_fails() -> None:
    guard, registry, _ = _guard(TripFlowKind.LEGACY_SINGLE)
    registry.strict_single = True
    with guard.operation(_access()) as permit:
        assert permit.flow_kind is TripFlowKind.LEGACY_SINGLE
    registry.strict_single = False
    with pytest.raises(AppError, match="TRIP_FLOW_SCOPE_UNKNOWN"):
        with guard.operation(_access()):
            raise AssertionError("body must not run")


def test_active_ready_lease_blocks_member_mutation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    guard = SqliteCollaborationReadinessGuard(
        database_path=harness.repository._path,
        repository=harness.repository,
        collaboration=harness.service,
        flow_registry=SqliteTripFlowRegistry(harness.repository._path),
    )
    access = PlanningAccess(
        trip_id=harness.revision.trip_id,
        organizer_capability=harness.organizer_token,
        operation_id="lease-test-00000001",
        operation=PlanningOperation.PROVIDER_FACTS,
    )
    with guard.operation(access):
        assert harness.repository.active_lease(access.trip_id) is not None
        with pytest.raises(CollaborationStoreError, match="COLLABORATION_OPERATION_IN_PROGRESS"):
            harness.repository.assert_mutation_allowed(access.trip_id)
    assert harness.repository.active_lease(access.trip_id) is None


def test_collaboration_permit_binds_exact_ready_revision(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    guard = SqliteCollaborationReadinessGuard(
        database_path=harness.repository._path,
        repository=harness.repository,
        collaboration=harness.service,
        flow_registry=SqliteTripFlowRegistry(harness.repository._path),
    )
    access = PlanningAccess(
        trip_id=harness.revision.trip_id,
        organizer_capability=harness.organizer_token,
        operation_id="revision-binding-0001",
        operation=PlanningOperation.GENERATE_V2,
    )

    with guard.operation(access) as permit:
        assert permit.current_revision == harness.revision.revision
        assert permit.readiness_digest == harness.service.require_ready(
            access.trip_id,
            access.organizer_capability,
        )


def test_source_digest_change_invalidates_ready_guard_before_body(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    guard = SqliteCollaborationReadinessGuard(
        database_path=harness.repository._path,
        repository=harness.repository,
        collaboration=harness.service,
        flow_registry=SqliteTripFlowRegistry(harness.repository._path),
    )
    harness.revisions.current = replace(harness.revision, source_digest="b" * 64)
    access = PlanningAccess(
        trip_id=harness.revision.trip_id,
        organizer_capability=harness.organizer_token,
        operation_id="source-digest-stale-0001",
        operation=PlanningOperation.PROVIDER_FACTS,
    )
    calls = 0

    with pytest.raises(AppError) as captured:
        with guard.operation(access):
            calls += 1

    assert captured.value.code == "COLLABORATION_NOT_READY"
    assert calls == 0


def test_same_operation_lease_retry_is_stable_and_digest_reuse_is_stale(tmp_path) -> None:
    from app.infrastructure.collaboration_store import SqliteCollaborationRepository

    repository = SqliteCollaborationRepository(tmp_path / "leases.sqlite3")
    access = _access()
    first = repository.acquire_lease(
        access=access,
        readiness_digest="a" * 64,
        ttl=timedelta(minutes=1),
    )

    retry = repository.acquire_lease(
        access=access,
        readiness_digest="a" * 64,
        ttl=timedelta(minutes=1),
    )
    assert retry == first

    with pytest.raises(CollaborationStoreError, match="COLLABORATION_OPERATION_STALE"):
        repository.acquire_lease(
            access=access,
            readiness_digest="b" * 64,
            ttl=timedelta(minutes=1),
        )

    repository.complete_lease(access.operation_id)
    assert repository.acquire_lease(
        access=access,
        readiness_digest="a" * 64,
        ttl=timedelta(minutes=1),
    ) == first
