from __future__ import annotations

from uuid import UUID

from app.core.errors import AppError
from app.infrastructure.arrival_evidence_store import (
    ArrivalEvidenceStoreError,
    SqliteArrivalEvidenceRepository,
)
from app.schemas.arrival_evidence import ArrivalEvidence, CreateArrivalEvidence


class ArrivalEvidenceService:
    def __init__(self, repository: SqliteArrivalEvidenceRepository) -> None:
        self.repository = repository

    @staticmethod
    def _as_app_error(error: ArrivalEvidenceStoreError) -> AppError:
        return AppError(
            code=error.code,
            message=error.message,
            http_status=(
                404 if error.code == "ARRIVAL_EVIDENCE_NOT_FOUND" else 409
            ),
            retryable=False,
        )

    def save(
        self,
        trip_id: UUID,
        request: CreateArrivalEvidence,
    ) -> ArrivalEvidence:
        try:
            return self.repository.save(trip_id, request)
        except ArrivalEvidenceStoreError as error:
            raise self._as_app_error(error) from error

    def get(self, trip_id: UUID, evidence_id: UUID) -> ArrivalEvidence:
        try:
            return self.repository.get(trip_id, evidence_id)
        except ArrivalEvidenceStoreError as error:
            raise self._as_app_error(error) from error

    def list_for_trip(
        self,
        trip_id: UUID,
        *,
        task_id: str | None = None,
    ) -> list[ArrivalEvidence]:
        return self.repository.list_for_trip(trip_id, task_id=task_id)


__all__ = ["ArrivalEvidenceService"]
