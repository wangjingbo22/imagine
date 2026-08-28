from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from uuid import UUID

import pytest

from app.application.collaboration_ports import TripDraftRevisionUnavailable
from app.application.collaboration_readiness import SqliteCollaborationReadinessGuard
from app.application.trip_draft_revision_service import TripDraftRevisionService
from app.core.config import Settings
from app.domain.collaboration import OrganizerConversationRequest, QUESTION_IDS
from app.main import create_app
from app.domain.collaboration import published_collaboration_schema


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "s2-t003-collaboration.schema.json"


@pytest.mark.asyncio
async def test_default_runtime_uses_concrete_revision_port_with_unavailable_gateway(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=tmp_path / "plans.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
    )

    creator = app.state.trip_draft_revision_creator
    assert isinstance(creator, TripDraftRevisionService)
    assert app.state.collaboration_service.revisions is creator
    with pytest.raises(TripDraftRevisionUnavailable):
        creator.get_current(UUID("30000000-0000-4000-8000-000000000001"))
    request = OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate=date(2026, 8, 27),
        naturalLanguageRequest="minimal request",
        answers=[
            {"questionId": question_id, "answer": "answer"}
            for question_id in QUESTION_IDS
        ],
    )
    outcome = await creator.create_initial(
        request,
        idempotency_key="runtime-default-0001",
    )
    assert outcome.recognition.failure_code == "LLM_NOT_CONFIGURED"
    assert outcome.recognition.call_count == 0
    assert outcome.understanding is None
    assert outcome.can_plan is False
    assert isinstance(
        app.state.collaboration_readiness_guard,
        SqliteCollaborationReadinessGuard,
    )
    assert app.state.planning_boundary_service.readiness_guard is (
        app.state.collaboration_readiness_guard
    )


def test_published_collaboration_schema_is_canonical() -> None:
    expected = json.dumps(
        published_collaboration_schema(),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    assert SCHEMA_PATH.read_text(encoding="utf-8") == expected
