from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import DATA_DIR, DB_PATH, EVENTS_DIR, FACES_DIR, VAPID_DIR


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    FACES_DIR.mkdir(parents=True, exist_ok=True)
    VAPID_DIR.mkdir(parents=True, exist_ok=True)
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

            CREATE TABLE IF NOT EXISTS persons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL,
                track_id INTEGER,
                person_id INTEGER,
                probable_person_id INTEGER,
                body_confidence REAL,
                body_identity_source TEXT,
                unknown_cluster_id INTEGER,
                identity_state TEXT NOT NULL DEFAULT 'pending',
                identity_confidence REAL,
                event_type TEXT NOT NULL DEFAULT 'person',
                has_face INTEGER NOT NULL DEFAULT 0,
                face_count INTEGER NOT NULL DEFAULT 0,
                confidence REAL,
                snapshot_path TEXT,
                bbox_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL,
                FOREIGN KEY(probable_person_id) REFERENCES persons(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS unknown_clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                centroid BLOB NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 1,
                representative_crop_path TEXT,
                representative_quality REAL NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                assigned_person_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(assigned_person_id) REFERENCES persons(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS face_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL UNIQUE,
                camera_id INTEGER NOT NULL,
                person_id INTEGER,
                cluster_id INTEGER,
                embedding BLOB NOT NULL,
                crop_path TEXT,
                quality REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL,
                FOREIGN KEY(cluster_id) REFERENCES unknown_clusters(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS body_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL UNIQUE,
                camera_id INTEGER NOT NULL,
                person_id INTEGER,
                embedding BLOB NOT NULL,
                quality REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'unlabeled',
                verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS body_negative_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL UNIQUE,
                camera_id INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                quality REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
            );

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

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                expiration_time REAL,
                user_agent TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                camera_id INTEGER,
                person_id INTEGER,
                unknown_only INTEGER NOT NULL DEFAULT 0,
                start_time TEXT,
                end_time TEXT,
                weekdays_json TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
                timezone TEXT NOT NULL DEFAULT 'UTC',
                cooldown_seconds INTEGER NOT NULL DEFAULT 300,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS alert_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL,
                event_id INTEGER NOT NULL,
                subscription_id INTEGER,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE,
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                FOREIGN KEY(subscription_id) REFERENCES push_subscriptions(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS alert_event_state (
                event_id INTEGER PRIMARY KEY,
                evaluated_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # Safe upgrades for installations created by earlier versions.
        _ensure_column(conn, "events", "person_id", "person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL")
        _ensure_column(conn, "events", "probable_person_id", "probable_person_id INTEGER")
        _ensure_column(conn, "events", "body_confidence", "body_confidence REAL")
        _ensure_column(conn, "events", "body_identity_source", "body_identity_source TEXT")
        _ensure_column(conn, "events", "unknown_cluster_id", "unknown_cluster_id INTEGER")
        _ensure_column(conn, "events", "identity_state", "identity_state TEXT NOT NULL DEFAULT 'pending'")
        _ensure_column(conn, "events", "identity_confidence", "identity_confidence REAL")
        _ensure_column(conn, "camera_runtime_settings", "home_preset_set", "home_preset_set INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "camera_runtime_settings", "autofollow_max_speed", "autofollow_max_speed REAL NOT NULL DEFAULT 0.65")

        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_cameras_enabled ON cameras(enabled);
            CREATE INDEX IF NOT EXISTS idx_persons_name ON persons(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_events_camera_created ON events(camera_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_person_created ON events(person_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_probable_person_created ON events(probable_person_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_cluster_created ON events(unknown_cluster_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_identity_state ON events(identity_state, created_at);
            CREATE INDEX IF NOT EXISTS idx_face_samples_person ON face_samples(person_id);
            CREATE INDEX IF NOT EXISTS idx_face_samples_cluster ON face_samples(cluster_id);
            CREATE INDEX IF NOT EXISTS idx_body_samples_person ON body_samples(person_id, verified);
            CREATE INDEX IF NOT EXISTS idx_body_samples_camera ON body_samples(camera_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_body_negative_camera ON body_negative_samples(camera_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_unknown_clusters_status ON unknown_clusters(status, last_seen DESC);
            CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON alert_rules(enabled);
            CREATE INDEX IF NOT EXISTS idx_alert_deliveries_rule_created ON alert_deliveries(rule_id, created_at DESC);
            """
        )

        # Events from V2 are intentionally queued for background identity indexing.
        conn.execute(
            "UPDATE events SET identity_state = 'pending' WHERE identity_state IS NULL OR identity_state = ''"
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
