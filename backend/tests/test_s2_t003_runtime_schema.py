from __future__ import annotations

import json
from pathlib import Path

from app.application.collaboration_ports import UnavailableTripDraftRevisionPort
from app.application.collaboration_readiness import SqliteCollaborationReadinessGuard
from app.core.config import Settings
from app.main import create_app
from app.domain.collaboration import published_collaboration_schema


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "s2-t003-collaboration.schema.json"


def test_default_app_uses_unavailable_revision_port_and_real_guard(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=tmp_path / "plans.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
    )

    assert isinstance(
        app.state.collaboration_service.revisions,
        UnavailableTripDraftRevisionPort,
    )
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
