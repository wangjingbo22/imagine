from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Protocol
from uuid import UUID

from app.application.arrival_evidence_service import ArrivalEvidenceService
from app.core.errors import AppError
from app.schemas.arrival_decision import (
    ArrivalDecision,
    ArrivalDecisionRequest,
    ArrivalDecisionResult,
    LocationAttemptOutcome,
    TargetTaskLocation,
)
from app.schemas.arrival_evidence import LocationEvidence


class DistanceCalculatorPort(Protocol):
    def meters_between(
        self,
        reading: LocationEvidence,
        target: TargetTaskLocation,
    ) -> float: ...


class HaversineDistanceCalculator:
    EARTH_RADIUS_METERS = 6_371_008.8

    def meters_between(
        self,
        reading: LocationEvidence,
        target: TargetTaskLocation,
    ) -> float:
        latitude_1 = radians(reading.latitude)
        latitude_2 = radians(target.latitude)
        delta_latitude = latitude_2 - latitude_1
        delta_longitude = radians(target.longitude - reading.longitude)
        haversine = (
            sin(delta_latitude / 2) ** 2
            + cos(latitude_1)
            * cos(latitude_2)
            * sin(delta_longitude / 2) ** 2
        )
        normalized = min(1.0, max(0.0, haversine))
        return 2 * self.EARTH_RADIUS_METERS * asin(sqrt(normalized))


class ArrivalDecisionService:
    MAX_AUTO_ACCURACY_METERS = 100.0
    MIN_AUTO_DISTANCE_METERS = 150.0

    def __init__(
        self,
        evidence_service: ArrivalEvidenceService,
        *,
        distance_calculator: DistanceCalculatorPort | None = None,
    ) -> None:
        self._evidence_service = evidence_service
        self._distance_calculator = (
            distance_calculator or HaversineDistanceCalculator()
        )

    def assess(
        self,
        trip_id: UUID,
        request: ArrivalDecisionRequest,
    ) -> ArrivalDecision:
        if request.attempt_outcome is LocationAttemptOutcome.PERMISSION_DENIED:
            return self._failure(
                trip_id,
                request,
                ArrivalDecisionResult.PERMISSION_DENIED,
                "LOCATION_PERMISSION_DENIED",
                "定位权限被拒绝，无法自动判断到达；可进行人工确认。",
            )
        if request.attempt_outcome is LocationAttemptOutcome.TIMEOUT:
            return self._failure(
                trip_id,
                request,
                ArrivalDecisionResult.TIMEOUT,
                "LOCATION_TIMEOUT",
                "单次定位请求超时，无法自动判断到达；可进行人工确认。",
            )

        assert request.arrival_evidence_id is not None
        evidence = self._evidence_service.get(
            trip_id,
            request.arrival_evidence_id,
        )
        if evidence.task_id != request.task_id:
            raise AppError(
                code="ARRIVAL_EVIDENCE_TASK_MISMATCH",
                message="到达证据绑定的 taskId 与目标任务不一致",
                http_status=409,
                retryable=False,
            )
        if evidence.location_evidence.source is not request.source:
            raise AppError(
                code="ARRIVAL_EVIDENCE_SOURCE_MISMATCH",
                message="请求来源与已保存定位证据来源不一致",
                http_status=409,
                retryable=False,
            )

        reading = evidence.location_evidence
        distance = self._distance_calculator.meters_between(
            reading,
            request.target_location,
        )
        allowed_distance = max(
            self.MIN_AUTO_DISTANCE_METERS,
            2 * reading.accuracy,
        )
        shared = {
            "trip_id": trip_id,
            "task_id": request.task_id,
            "arrival_evidence_id": evidence.evidence_id,
            "source": reading.source,
            "distance_meters": round(distance, 3),
            "accuracy": reading.accuracy,
            "allowed_distance_meters": round(allowed_distance, 3),
        }
        if reading.accuracy > self.MAX_AUTO_ACCURACY_METERS:
            return ArrivalDecision(
                **shared,
                result=ArrivalDecisionResult.LOW_ACCURACY,
                reason_code="ACCURACY_EXCEEDS_100_METERS",
                message="定位精度超过 100 米，不能自动确认到达。",
                auto_confirmed=False,
                manual_confirmation_allowed=True,
            )
        if distance > allowed_distance:
            return ArrivalDecision(
                **shared,
                result=ArrivalDecisionResult.TOO_FAR,
                reason_code="DISTANCE_EXCEEDS_THRESHOLD",
                message="当前位置超过自动到达距离阈值，不能自动确认到达。",
                auto_confirmed=False,
                manual_confirmation_allowed=True,
            )
        return ArrivalDecision(
            **shared,
            result=ArrivalDecisionResult.ARRIVED,
            reason_code="WITHIN_ARRIVAL_THRESHOLD",
            message="定位精度与距离均满足自动到达条件。",
            auto_confirmed=True,
            manual_confirmation_allowed=False,
        )

    @staticmethod
    def _failure(
        trip_id: UUID,
        request: ArrivalDecisionRequest,
        result: ArrivalDecisionResult,
        reason_code: str,
        message: str,
    ) -> ArrivalDecision:
        return ArrivalDecision(
            trip_id=trip_id,
            task_id=request.task_id,
            result=result,
            reason_code=reason_code,
            message=message,
            source=request.source,
            auto_confirmed=False,
            manual_confirmation_allowed=True,
        )


__all__ = [
    "ArrivalDecisionService",
    "DistanceCalculatorPort",
    "HaversineDistanceCalculator",
]
