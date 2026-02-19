from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from .config import STATE_DB_PATH

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    branch TEXT NOT NULL,
    pr_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    summary TEXT NOT NULL,
    sample_messages TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    clusters_found INTEGER NOT NULL DEFAULT 0,
    prs_created INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS log_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    cluster_slug TEXT NOT NULL,
    sample_messages TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL,
    module TEXT NOT NULL,
    severity TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class StateManager:
    def __init__(self, db_path: Path = STATE_DB_PATH) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def get_open_patterns(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT slug, summary, sample_messages FROM processed_patterns "
            "WHERE status != 'closed'"
        ).fetchall()
        return [
            {
                "slug": row["slug"],
                "summary": row["summary"],
                "sample_messages": json.loads(row["sample_messages"]),
            }
            for row in rows
        ]

    def record_pattern(
        self,
        slug: str,
        branch: str,
        pr_url: str,
        summary: str,
        sample_messages: list[str],
    ) -> None:
        now = time.time()
        self._conn.execute(
            "INSERT INTO processed_patterns "
            "(slug, branch, pr_url, status, summary, sample_messages, created_at, updated_at) "
            "VALUES (?, ?, ?, 'open', ?, ?, ?, ?)",
            (slug, branch, pr_url, summary, json.dumps(sample_messages), now, now),
        )
        self._conn.commit()

    def record_run(
        self,
        started_at: float,
        clusters_found: int,
        prs_created: int,
        errors: int,
    ) -> int:
        duration = time.time() - started_at
        cursor = self._conn.execute(
            "INSERT INTO runs (started_at, clusters_found, prs_created, errors, duration_seconds) "
            "VALUES (?, ?, ?, ?, ?)",
            (started_at, clusters_found, prs_created, errors, duration),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def record_snapshot(
        self,
        run_id: int,
        cluster_slug: str,
        sample_messages: list[str],
        occurrence_count: int,
        module: str,
        severity: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO log_snapshots "
            "(run_id, cluster_slug, sample_messages, occurrence_count, module, severity, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                cluster_slug,
                json.dumps(sample_messages),
                occurrence_count,
                module,
                severity,
                time.time(),
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
