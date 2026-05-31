from __future__ import annotations

import sqlite3
from pathlib import Path


class ReportState:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS report_runs (
                    slot_key TEXT PRIMARY KEY,
                    slot_label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def already_sent(self, slot_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM report_runs WHERE slot_key = ? AND status = 'sent'",
                (slot_key,),
            ).fetchone()
        return row is not None

    def record(self, slot_key: str, slot_label: str, status: str, message_count: int = 0, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO report_runs (slot_key, slot_label, status, message_count, error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slot_key) DO UPDATE SET
                    status = excluded.status,
                    message_count = excluded.message_count,
                    error = excluded.error,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (slot_key, slot_label, status, message_count, error),
            )
