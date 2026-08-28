from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_task_media_replaces_deletes_and_enforces_eight_trip_limit(tmp_path) -> None:
    app = create_app(settings=Settings(
        amap_web_service_key="test-amap",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
        plan_version_db_path=tmp_path / "plan.sqlite3",
    ))
    trip_id = uuid4()
    payload = {"dataUrl": "data:image/jpeg;base64," + "A" * 64, "mimeType": "image/jpeg", "byteSize": 64}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/api/v2/trips/{trip_id}/tasks/task-1/media", json=payload)
        assert first.status_code == 200
        replacement = await client.post(f"/api/v2/trips/{trip_id}/tasks/task-1/media", json=payload)
        assert replacement.status_code == 200
        assert replacement.json()["data"]["mediaId"] != first.json()["data"]["mediaId"]
        for index in range(2, 9):
            assert (await client.post(f"/api/v2/trips/{trip_id}/tasks/task-{index}/media", json=payload)).status_code == 200
        limit = await client.post(f"/api/v2/trips/{trip_id}/tasks/task-9/media", json=payload)
        assert limit.status_code == 409
        assert (await client.delete(f"/api/v2/trips/{trip_id}/tasks/task-1/media")).status_code == 200
        assert (await client.get(f"/api/v2/trips/{trip_id}/tasks/task-1/media")).json()["data"] is None
        assert (await client.post(f"/api/v2/trips/{trip_id}/tasks/task-9/media", json=payload)).status_code == 200
