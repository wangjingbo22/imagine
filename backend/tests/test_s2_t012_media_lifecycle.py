import sqlite3
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


@pytest.mark.asyncio
async def test_media_storage_failure_rolls_back_replacement_and_retry_succeeds(tmp_path) -> None:
    database_path = tmp_path / "plan.sqlite3"
    app = create_app(settings=Settings(
        amap_web_service_key="test-amap",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
        plan_version_db_path=database_path,
    ))
    trip_id = uuid4()
    old_payload = {
        "dataUrl": "data:image/jpeg;base64," + "A" * 64,
        "mimeType": "image/jpeg",
        "byteSize": 64,
    }
    new_payload = {
        "dataUrl": "data:image/jpeg;base64," + "B" * 64,
        "mimeType": "image/jpeg",
        "byteSize": 64,
    }

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/api/v2/trips/{trip_id}/tasks/task-1/media", json=old_payload)
        assert first.status_code == 200
        old_media = first.json()["data"]

        with sqlite3.connect(database_path) as connection:
            connection.execute("""
                CREATE TRIGGER fail_media_insert
                BEFORE INSERT ON task_media
                BEGIN
                    SELECT RAISE(ABORT, 'media insert blocked');
                END
            """)

        failed = await client.post(f"/api/v2/trips/{trip_id}/tasks/task-1/media", json=new_payload)
        assert failed.status_code == 503
        assert failed.json()["code"] == "MEDIA_STORAGE_UNAVAILABLE"
        assert failed.json()["retryable"] is True

        after_failure = await client.get(f"/api/v2/trips/{trip_id}/tasks/task-1/media")
        assert after_failure.status_code == 200
        assert after_failure.json()["data"]["mediaId"] == old_media["mediaId"]
        assert after_failure.json()["data"]["dataUrl"] == old_media["dataUrl"]

        with sqlite3.connect(database_path) as connection:
            connection.execute("DROP TRIGGER fail_media_insert")

        retried = await client.post(f"/api/v2/trips/{trip_id}/tasks/task-1/media", json=new_payload)
        assert retried.status_code == 200
        assert retried.json()["data"]["mediaId"] != old_media["mediaId"]
        assert retried.json()["data"]["dataUrl"] == new_payload["dataUrl"]

        final = await client.get(f"/api/v2/trips/{trip_id}/tasks/task-1/media")
        assert final.status_code == 200
        assert final.json()["data"] == retried.json()["data"]
        with sqlite3.connect(database_path) as connection:
            active_rows = connection.execute(
                "SELECT media_id FROM task_media WHERE trip_id = ? AND task_id = ? AND deleted_at IS NULL",
                (str(trip_id), "task-1"),
            ).fetchall()
        assert active_rows == [(retried.json()["data"]["mediaId"],)]
