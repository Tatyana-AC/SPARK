"""
SPARK Jetson Brain - authoritative rich context store.

The Jetson owns durable persistence for captured context sessions plus button
events linked to the active session.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_SESSION_RECENCY_ORDER = "COALESCE(host_observed_at, updated_at) DESC, id DESC"


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip().lower()


def build_context_key(payload: dict) -> str:
    app_name = payload.get("app_name", "")
    url = payload.get("url")
    window_title = payload.get("window_title", "")
    if url:
        return f"{app_name}|{url}"
    return f"{app_name}|{window_title}"


def build_content_fingerprint(payload: dict) -> str:
    body = "|".join(
        (
            _normalize(payload.get("app_name")),
            _normalize(payload.get("url")) or _normalize(payload.get("window_title")),
            _normalize(payload.get("text")),
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class JetsonDB:
    """Session-oriented SQLite store for the Jetson Brain node."""

    def __init__(self, db_path: str = "jetson_spark.db"):
        self._path = Path(db_path)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._active_session_id: Optional[int] = None
        self._active_context_key: Optional[str] = None
        self._create_tables()
        self._restore_active_session()
        logger.info("JetsonDB opened at %s", self._path.resolve())

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                context_key         TEXT    NOT NULL,
                content_fingerprint TEXT    NOT NULL,
                app_name            TEXT    NOT NULL,
                window_title        TEXT    NOT NULL,
                process_name        TEXT    NOT NULL,
                pid                 INTEGER NOT NULL,
                source              TEXT    NOT NULL,
                tab_title           TEXT,
                url                 TEXT,
                text                TEXT    NOT NULL DEFAULT '',
                host_observed_at    REAL,
                started_at          REAL    NOT NULL,
                updated_at          REAL    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_context_key
            ON sessions (context_key);

            CREATE INDEX IF NOT EXISTS idx_sessions_fingerprint
            ON sessions (content_fingerprint);

            CREATE TABLE IF NOT EXISTS button_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                button_id   INTEGER NOT NULL,
                session_id  INTEGER,
                timestamp   REAL    NOT NULL
            );
        """
        )
        self._conn.commit()

    def _restore_active_session(self) -> None:
        row = self._conn.execute(
            f"SELECT id, context_key FROM sessions ORDER BY {_SESSION_RECENCY_ORDER} LIMIT 1"
        ).fetchone()
        if row is None:
            return
        self._active_session_id = int(row["id"])
        self._active_context_key = row["context_key"]

    @staticmethod
    def _payload_pid(payload: dict) -> int:
        return int(payload.get("pid", 0))

    def _get_latest_session(self) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            f"SELECT * FROM sessions ORDER BY {_SESSION_RECENCY_ORDER} LIMIT 1"
        ).fetchone()

    def _find_reusable_session(self, payload: dict, context_key: str) -> Optional[sqlite3.Row]:
        row = self._get_latest_session()
        if row is None:
            return None
        if row["context_key"] != context_key:
            return None
        if row["process_name"] != payload.get("process_name", ""):
            return None
        if int(row["pid"]) != self._payload_pid(payload):
            return None
        return row

    def _set_active_session(self, row_id: int, context_key: str) -> None:
        self._active_session_id = int(row_id)
        self._active_context_key = context_key

    def _update_session_row(self, row_id: int, payload: dict, *, now: float) -> None:
        fingerprint = build_content_fingerprint(payload)
        self._conn.execute(
            """
            UPDATE sessions
            SET content_fingerprint = ?,
                app_name = ?,
                window_title = ?,
                process_name = ?,
                pid = ?,
                source = ?,
                tab_title = ?,
                url = ?,
                text = ?,
                host_observed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                fingerprint,
                payload.get("app_name", ""),
                payload.get("window_title", ""),
                payload.get("process_name", ""),
                self._payload_pid(payload),
                payload.get("source", ""),
                payload.get("tab_title"),
                payload.get("url"),
                payload.get("text", ""),
                payload.get("timestamp"),
                now,
                row_id,
            ),
        )

    def _collapse_live_session_duplicates(self, keep_session_id: int, payload: dict, context_key: str) -> None:
        duplicate_ids = [
            int(row["id"])
            for row in self._conn.execute(
                f"""
                SELECT id
                FROM sessions
                WHERE context_key = ?
                  AND process_name = ?
                  AND pid = ?
                  AND id != ?
                ORDER BY {_SESSION_RECENCY_ORDER}
                """,
                (
                    context_key,
                    payload.get("process_name", ""),
                    self._payload_pid(payload),
                    keep_session_id,
                ),
            ).fetchall()
        ]
        if not duplicate_ids:
            return

        placeholders = ",".join("?" for _ in duplicate_ids)
        self._conn.execute(
            f"UPDATE button_events SET session_id = ? WHERE session_id IN ({placeholders})",
            (keep_session_id, *duplicate_ids),
        )
        self._conn.execute(
            f"DELETE FROM sessions WHERE id IN ({placeholders})",
            duplicate_ids,
        )

    def on_context_new(self, payload: dict) -> int:
        now = time.time()
        context_key = build_context_key(payload)
        reusable = self._find_reusable_session(payload, context_key)
        if reusable is not None:
            self._update_session_row(int(reusable["id"]), payload, now=now)
            self._collapse_live_session_duplicates(int(reusable["id"]), payload, context_key)
            self._conn.commit()
            self._set_active_session(int(reusable["id"]), context_key)
            return int(reusable["id"])

        fingerprint = build_content_fingerprint(payload)
        cur = self._conn.execute(
            """
            INSERT INTO sessions (
                context_key,
                content_fingerprint,
                app_name,
                window_title,
                process_name,
                pid,
                source,
                tab_title,
                url,
                text,
                host_observed_at,
                started_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context_key,
                fingerprint,
                payload.get("app_name", ""),
                payload.get("window_title", ""),
                payload.get("process_name", ""),
                int(payload.get("pid", 0)),
                payload.get("source", ""),
                payload.get("tab_title"),
                payload.get("url"),
                payload.get("text", ""),
                payload.get("timestamp"),
                now,
                now,
            ),
        )
        self._collapse_live_session_duplicates(int(cur.lastrowid), payload, context_key)
        self._conn.commit()
        self._set_active_session(int(cur.lastrowid), context_key)
        return self._active_session_id

    def on_context_update(self, payload: dict) -> None:
        context_key = build_context_key(payload)
        if self._active_session_id is None or self._active_context_key != context_key:
            reusable = self._find_reusable_session(payload, context_key)
            if reusable is None:
                logger.warning("CONTEXT_UPDATE with no matching active session - promoting to CONTEXT_NEW")
                self.on_context_new(payload)
                return
            logger.warning(
                "CONTEXT_UPDATE with no matching active session - reattaching to latest session id=%s",
                reusable["id"],
            )
            self._set_active_session(int(reusable["id"]), context_key)

        now = time.time()
        self._update_session_row(self._active_session_id, payload, now=now)
        self._collapse_live_session_duplicates(self._active_session_id, payload, context_key)
        self._conn.commit()

    def on_button_press(self, button_id: int) -> None:
        self._conn.execute(
            """
            INSERT INTO button_events (button_id, session_id, timestamp)
            VALUES (?, ?, ?)
            """,
            (button_id, self._active_session_id, time.time()),
        )
        self._conn.commit()

    def get_active_session(self) -> Optional[sqlite3.Row]:
        """Return the most recently updated session, or None."""
        if self._active_session_id is None:
            return None
        return self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (self._active_session_id,),
        ).fetchone()

    def get_recent_sessions(self, limit: int = 20):
        return self._conn.execute(
            f"SELECT * FROM sessions ORDER BY {_SESSION_RECENCY_ORDER} LIMIT ?",
            (limit,),
        ).fetchall()

    def get_recent_sessions_matching_text(self, query_text: str, limit: int = 3):
        normalized_query = _normalize(query_text)
        if not normalized_query:
            return []
        matches = []
        rows = self._conn.execute(
            f"""
            SELECT *
            FROM sessions
            WHERE text != ''
            ORDER BY {_SESSION_RECENCY_ORDER}
            """,
        ).fetchall()
        for row in rows:
            if normalized_query in _normalize(row["text"]):
                matches.append(row)
                if len(matches) >= limit:
                    break
        return matches

    def close(self) -> None:
        self._conn.close()
        logger.info("JetsonDB closed")
