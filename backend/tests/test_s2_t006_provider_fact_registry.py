from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.application.recommendation_service import (
    ProviderFactRestoreError,
    RecommendationOrchestrationService,
)
from app.core.config import Settings
from app.domain.models import SourceStatus
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.provider_fact_registry import (
    ProviderFactIssuanceError,
    SqliteProviderFactRegistry,
)
from app.main import create_app
from app.services.planning import CandidatePlanRequest
from app.services.recommendation import (
    ProviderFactIssueDraft,
    RecommendationOrchestrationRequest,
)


FIXTURE = Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
ISSUED_AT = datetime(2026, 8, 27, 9, 30, tzinfo=UTC)


def _candidate_request() -> CandidatePlanRequest:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["request"]
    return CandidatePlanRequest.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def _draft() -> ProviderFactIssueDraft:
    request = _candidate_request()
    places = [item.place for item in request.task_facts]
    for suffix, source in (("extra-5", places[0]), ("extra-6", places[1])):
        places.append(
            source.model_copy(
                update={
                    "placeId": suffix,
                    "name": f"服务端候选 {suffix}",
                }
            )
        )
    return ProviderFactIssueDraft(
        trip=request.trip,
        start_location=request.start_location,
        end_location=request.end_location,
        confirmed_constraints=request.confirmed_constraints,
        confirmed_trip_summary={
            "cityCode": request.trip.city_context.city_code,
            "participantCount": len(request.trip.participants),
        },
        places=tuple(places),
        routes=tuple(item.route for item in request.task_facts),
    )


def _count(database_path: Path, table: str) -> int:
    with closing(sqlite3.connect(database_path)) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_issue_register_restore_and_idempotent_summary(tmp_path: Path) -> None:
    database_path = tmp_path / "facts.sqlite3"
    registry = SqliteProviderFactRegistry(database_path)
    draft = _draft()

    first = registry.issue(draft, issued_at=ISSUED_AT)
    repeated = registry.issue(
        draft,
        issued_at=datetime(2026, 8, 27, 10, 0, tzinfo=UTC),
    )
    snapshot = registry.restore_snapshot(draft.trip.trip_id, first.fact_set_id)
    bundle = registry.restore(draft.trip.trip_id, first.fact_set_id)

    assert first == repeated
    assert first.provider_fact_digest == registry.content_digest(draft)
    assert first.issued_at == ISSUED_AT
    assert len(first.references) == 10
    assert {item.kind for item in first.references} == {"PLACE", "ROUTE"}
    assert all(item.fetched_at.tzinfo is not None for item in first.references)
    assert all(
        item.source_status in {SourceStatus.ONLINE, SourceStatus.VERIFIED_CACHE}
        for item in first.references
    )
    assert snapshot.summary() == first
    assert bundle.fact_set_id == first.fact_set_id
    assert bundle.provider_fact_digest == first.provider_fact_digest
    assert len(bundle.candidate_facts) == 6
    place_digests = {
        item.payload_digest
        for item in first.references
        if item.kind == "PLACE"
    }
    assert {item.fact_digest for item in bundle.candidate_facts} == place_digests
    assert _count(database_path, "provider_fact_sets") == 1
    assert _count(database_path, "provider_fact_refs") == 10


def test_untrusted_server_fact_is_rejected_before_any_write(tmp_path: Path) -> None:
    database_path = tmp_path / "facts.sqlite3"
    registry = SqliteProviderFactRegistry(database_path)
    draft = _draft()
    first = draft.places[0]
    forged = first.model_copy(
        update={
            "provenance": first.provenance.model_copy(
                update={"sourceStatus": SourceStatus.USER_CONFIRMED}
            )
        }
    )
    bypassed = draft.model_copy(update={"places": (forged, *draft.places[1:])})

    with pytest.raises(ProviderFactIssuanceError) as captured:
        registry.issue(bypassed)

    assert captured.value.code == "PROVIDER_FACT_ISSUANCE_INVALID"
    assert _count(database_path, "provider_fact_sets") == 0
    assert _count(database_path, "provider_fact_refs") == 0


@pytest.mark.parametrize(
    "mutation",
    ("place", "route", "price", "provenance"),
)
def test_tampered_signed_fact_is_rejected_and_plan_table_stays_empty(
    tmp_path: Path,
    mutation: str,
) -> None:
    database_path = tmp_path / f"tamper-{mutation}.sqlite3"
    SqlitePlanVersionRepository(database_path)
    registry = SqliteProviderFactRegistry(database_path)
    summary = registry.issue(_draft(), issued_at=ISSUED_AT)

    with closing(sqlite3.connect(database_path)) as connection, connection:
        raw = connection.execute(
            "SELECT snapshot_json FROM provider_fact_sets WHERE fact_set_id = ?",
            (summary.fact_set_id,),
        ).fetchone()[0]
        payload = json.loads(raw)
        if mutation == "place":
            payload["draft"]["places"][0]["name"] += "（伪造）"
        elif mutation == "route":
            payload["draft"]["routes"][0]["distanceMeters"] += 1
        elif mutation == "price":
            payload["draft"]["places"][0]["priceReference"]["kind"] += "_FAKE"
        else:
            payload["draft"]["places"][0]["provenance"]["isStale"] = not payload[
                "draft"
            ]["places"][0]["provenance"]["isStale"]
        connection.execute(
            "UPDATE provider_fact_sets SET snapshot_json = ? WHERE fact_set_id = ?",
            (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                summary.fact_set_id,
            ),
        )

    with pytest.raises(ProviderFactRestoreError) as captured:
        registry.restore(_draft().trip.trip_id, summary.fact_set_id)

    assert captured.value.code == "PROVIDER_FACT_INTEGRITY_ERROR"
    assert _count(database_path, "plan_versions") == 0


class _NeverGateway:
    async def propose(self, request):  # pragma: no cover - must not be called
        raise AssertionError("invalid client facts reached the model")


class _NeverRouteBuilder:
    async def build(self, facts, selected_place_fact_ids):  # pragma: no cover
        raise AssertionError("invalid client facts reached route construction")


class _NeverReadinessGuard:
    def operation(self, access):  # pragma: no cover - must not be called
        raise AssertionError("invalid client facts reached readiness guard")


@pytest.mark.asyncio
async def test_http_client_cannot_embed_place_route_price_or_provenance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "http.sqlite3"
    registry = SqliteProviderFactRegistry(database_path)
    readiness_guard = _NeverReadinessGuard()
    recommendation = RecommendationOrchestrationService(
        fact_registry=registry,
        proposal_gateway=_NeverGateway(),
        route_builder=_NeverRouteBuilder(),
        readiness_guard=readiness_guard,
    )
    app = create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=database_path,
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
        recommendation_service=recommendation,
        collaboration_readiness_guard=readiness_guard,
        provider_fact_registry=registry,
    )
    command = RecommendationOrchestrationRequest(
        fact_set_id="fact-set-does-not-matter",
        provider_fact_digest="a" * 64,
    ).model_dump(mode="json", by_alias=True)
    command.update(
        {
            "place": {"placeId": "forged"},
            "route": {"routeId": "forged"},
            "price": 1,
            "provenance": {"sourceStatus": "ONLINE"},
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/trips/{_draft().trip.trip_id}/recommendations",
            json=command,
        )

    assert response.status_code == 422
    assert response.json()["code"] == "TRIP_SCHEMA_INVALID"
    assert _count(database_path, "provider_fact_sets") == 0
    assert _count(database_path, "plan_versions") == 0


@pytest.mark.asyncio
async def test_http_summary_restores_only_matching_server_digest(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "summary.sqlite3"
    registry = SqliteProviderFactRegistry(database_path)
    draft = _draft()
    summary = registry.issue(draft, issued_at=ISSUED_AT)
    app = create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=database_path,
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
        provider_fact_registry=registry,
    )

    url = (
        f"/api/v1/trips/{draft.trip.trip_id}/provider-fact-sets/"
        f"{summary.fact_set_id}"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        accepted = await client.get(
            url,
            params={"providerFactDigest": summary.provider_fact_digest},
        )
        rejected = await client.get(
            url,
            params={"providerFactDigest": "f" * 64},
        )

    assert accepted.status_code == 200
    assert accepted.json()["data"]["providerFactDigest"] == (
        summary.provider_fact_digest
    )
    assert len(accepted.json()["data"]["references"]) == 10
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "PROVIDER_FACT_DIGEST_MISMATCH"
