from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import DATA_DIR, DB_PATH, EVENTS_DIR


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                rtsp_url TEXT NOT NULL,
                stream_name TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                sync_status TEXT NOT NULL DEFAULT 'pending',
                sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cameras_enabled
                ON cameras(enabled);

            CREATE TABLE IF NOT EXISTS persons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_persons_name
                ON persons(name COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL,
                track_id INTEGER,
                person_id INTEGER,
                event_type TEXT NOT NULL DEFAULT 'person',
                has_face INTEGER NOT NULL DEFAULT 0,
                face_count INTEGER NOT NULL DEFAULT 0,
                confidence REAL,
                snapshot_path TEXT,
                bbox_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_camera_created
                ON events(camera_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_created
                ON events(created_at DESC);

            CREATE TABLE IF NOT EXISTS camera_runtime_settings (
                camera_id INTEGER PRIMARY KEY,
                vision_enabled INTEGER NOT NULL DEFAULT 1,
                auto_follow_enabled INTEGER NOT NULL DEFAULT 0,
                selected_track_id INTEGER,
                home_preset_set INTEGER NOT NULL DEFAULT 0,
                autofollow_max_speed REAL NOT NULL DEFAULT 0.65,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # Existing installations created the events table before identity support
        # existed. Add the new column first, then create any index that references
        # it. Creating the index inside the executescript above would fail on an
        # old database because CREATE TABLE IF NOT EXISTS does not alter schemas.
        _ensure_column(
            conn,
            "events",
            "person_id",
            "person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_person_created ON events(person_id, created_at DESC)"
        )

        _ensure_column(
            conn,
            "camera_runtime_settings",
            "home_preset_set",
            "home_preset_set INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            conn,
            "camera_runtime_settings",
            "autofollow_max_speed",
            "autofollow_max_speed REAL NOT NULL DEFAULT 0.65",
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO camera_runtime_settings(camera_id, updated_at)
            SELECT id, ? FROM cameras
            """,
            (utc_now(),),
        )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
