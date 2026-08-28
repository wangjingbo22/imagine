"""S2 task-bound photo lifecycle.  Images arrive already canvas-reencoded."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, alias_generators

from app.core.errors import AppError
from app.domain.models import ApiResponse


router = APIRouter(prefix="/api/v2", tags=["S2 任务照片"])


class MediaUpload(BaseModel):
    model_config = ConfigDict(extra="forbid", alias_generator=alias_generators.to_camel, populate_by_name=True)
    data_url: str = Field(min_length=20, max_length=2_100_000)
    mime_type: str = Field(pattern=r"^image/(jpeg|webp)$")
    byte_size: int = Field(gt=0, le=1_500_000)


class TaskMedia(BaseModel):
    model_config = ConfigDict(alias_generator=alias_generators.to_camel, populate_by_name=True)
    media_id: str
    task_id: str
    data_url: str
    mime_type: str
    byte_size: int
    created_at: str


def _connection(request: Request) -> sqlite3.Connection:
    return sqlite3.connect(request.app.state.media_database_path)


def _initialize(request: Request) -> None:
    with _connection(request) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS task_media (
            media_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, task_id TEXT NOT NULL,
            data_url TEXT NOT NULL, mime_type TEXT NOT NULL, byte_size INTEGER NOT NULL,
            created_at TEXT NOT NULL, deleted_at TEXT)""")


@router.get("/trips/{trip_id}/tasks/{task_id}/media")
async def list_media(trip_id: UUID, task_id: str, request: Request) -> ApiResponse:
    _initialize(request)
    with _connection(request) as connection:
        row = connection.execute("SELECT * FROM task_media WHERE trip_id = ? AND task_id = ? AND deleted_at IS NULL", (str(trip_id), task_id)).fetchone()
    return ApiResponse(data=None if row is None else TaskMedia(media_id=row[0], task_id=row[2], data_url=row[3], mime_type=row[4], byte_size=row[5], created_at=row[6]))


@router.post("/trips/{trip_id}/tasks/{task_id}/media")
async def replace_media(trip_id: UUID, task_id: str, upload: MediaUpload, request: Request) -> ApiResponse:
    _initialize(request)
    now = datetime.now(UTC).isoformat()
    with _connection(request) as connection:
        active_count = connection.execute("SELECT COUNT(*) FROM task_media WHERE trip_id = ? AND deleted_at IS NULL AND task_id != ?", (str(trip_id), task_id)).fetchone()[0]
        if active_count >= 8:
            raise AppError("TRIP_MEDIA_LIMIT_REACHED", "全程最多保存 8 张照片", 409, False)
        connection.execute("UPDATE task_media SET deleted_at = ? WHERE trip_id = ? AND task_id = ? AND deleted_at IS NULL", (now, str(trip_id), task_id))
        media_id = str(uuid4())
        connection.execute("INSERT INTO task_media VALUES (?, ?, ?, ?, ?, ?, ?, NULL)", (media_id, str(trip_id), task_id, upload.data_url, upload.mime_type, upload.byte_size, now))
    return ApiResponse(data=TaskMedia(media_id=media_id, task_id=task_id, data_url=upload.data_url, mime_type=upload.mime_type, byte_size=upload.byte_size, created_at=now))


@router.delete("/trips/{trip_id}/tasks/{task_id}/media")
async def delete_media(trip_id: UUID, task_id: str, request: Request) -> ApiResponse:
    _initialize(request)
    with _connection(request) as connection:
        changed = connection.execute("UPDATE task_media SET deleted_at = ? WHERE trip_id = ? AND task_id = ? AND deleted_at IS NULL", (datetime.now(UTC).isoformat(), str(trip_id), task_id)).rowcount
    if not changed:
        raise AppError("TASK_MEDIA_NOT_FOUND", "当前任务没有可删除的照片", 404, False)
    return ApiResponse(data={"deleted": True, "taskId": task_id})
