from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ActiveTaskPhoto:
    media_id: UUID
    task_id: str
    data_url: str
    mime_type: str
    byte_size: int
    created_at: datetime


class SqliteMemoryMediaReader:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def list_active(self, trip_id: UUID) -> list[ActiveTaskPhoto]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            table = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'task_media'
                """
            ).fetchone()
            if table is None:
                return []
            rows = connection.execute(
                """
                SELECT media_id, task_id, data_url, mime_type, byte_size,
                       created_at
                FROM task_media
                WHERE trip_id = ? AND deleted_at IS NULL
                ORDER BY created_at, media_id
                """,
                (str(trip_id),),
            ).fetchall()
        return [
            ActiveTaskPhoto(
                media_id=UUID(row[0]),
                task_id=row[1],
                data_url=row[2],
                mime_type=row[3],
                byte_size=row[4],
                created_at=datetime.fromisoformat(row[5]),
            )
            for row in rows
        ]


__all__ = ["ActiveTaskPhoto", "SqliteMemoryMediaReader"]
