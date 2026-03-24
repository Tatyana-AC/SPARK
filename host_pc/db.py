"""
SQLite database layer for persisting window context snapshots.

Stores the full text content of each window visit so context
is available across sessions and can be queried later.
"""

import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from .accessibility.base import TextSource, WindowContextSnapshot, WindowInfo
from .snapshot_policy import snapshot_fingerprint

logger = logging.getLogger(__name__)


class SparkDB:
    """SQLite-backed storage for window context snapshots."""

    def __init__(self, db_path: str = "spark.db"):
        self._path = Path(db_path)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate()
        logger.info("SparkDB opened at %s", self._path.resolve())

    def _create_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS window_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name      TEXT    NOT NULL,
                window_title  TEXT    NOT NULL,
                process_name  TEXT    NOT NULL,
                pid           INTEGER NOT NULL,
                text          TEXT    NOT NULL,
                source        TEXT    NOT NULL,
                tab_title     TEXT,
                url           TEXT,
                content_fingerprint TEXT,
                first_seen    REAL,
                last_seen     REAL,
                timestamp     REAL    NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns that may be missing from older databases."""
        columns = {
            row[1]
            for row in self._conn.execute(
                "PRAGMA table_info(window_snapshots)"
            ).fetchall()
        }
        for col, ddl in (
            ("tab_title", "TEXT"),
            ("url", "TEXT"),
            ("content_fingerprint", "TEXT"),
            ("first_seen", "REAL"),
            ("last_seen", "REAL"),
        ):
            if col not in columns:
                self._conn.execute(
                    f"ALTER TABLE window_snapshots ADD COLUMN {col} {ddl}"
                )
                logger.info("Migrated: added '%s' column to window_snapshots", col)
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_window_snapshots_fingerprint
            ON window_snapshots (content_fingerprint)
            """
        )
        self._backfill_snapshot_metadata()
        self._conn.commit()

    def _backfill_snapshot_metadata(self) -> None:
        rows = self._conn.execute(
            """
            SELECT id, app_name, window_title, process_name, pid, text, source,
                   tab_title, url, timestamp, first_seen, last_seen, content_fingerprint
            FROM window_snapshots
            WHERE first_seen IS NULL OR last_seen IS NULL OR content_fingerprint IS NULL
            """
        ).fetchall()
        for row in rows:
            snapshot = self._row_to_snapshot(row)
            fingerprint = snapshot_fingerprint(snapshot)
            first_seen = row["first_seen"] if row["first_seen"] is not None else row["timestamp"]
            last_seen = row["last_seen"] if row["last_seen"] is not None else row["timestamp"]
            self._conn.execute(
                """
                UPDATE window_snapshots
                SET content_fingerprint = ?,
                    first_seen = ?,
                    last_seen = ?
                WHERE id = ?
                """,
                (fingerprint, first_seen, last_seen, row["id"]),
            )

    def save_snapshot(self, snapshot: WindowContextSnapshot) -> int:
        """Insert a window context snapshot into the database and return its row id."""
        fingerprint = snapshot_fingerprint(snapshot)
        cursor = self._conn.execute(
            """
            INSERT INTO window_snapshots
                (app_name, window_title, process_name, pid, text, source,
                 tab_title, url, content_fingerprint, first_seen, last_seen, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.window_info.app_name,
                snapshot.window_info.title,
                snapshot.window_info.process_name,
                snapshot.window_info.pid,
                snapshot.text,
                snapshot.source.value,
                snapshot.tab_title,
                snapshot.url,
                fingerprint,
                snapshot.timestamp,
                snapshot.timestamp,
                snapshot.timestamp,
            ),
        )
        self._conn.commit()
        logger.debug(
            "Saved snapshot: %s (%s chars)",
            snapshot.window_info.app_name,
            len(snapshot.text),
        )
        return int(cursor.lastrowid)

    def update_snapshot(self, snapshot_id: int, snapshot: WindowContextSnapshot) -> None:
        """Update an existing persisted snapshot row in place."""
        fingerprint = snapshot_fingerprint(snapshot)
        self._conn.execute(
            """
            UPDATE window_snapshots
            SET app_name = ?,
                window_title = ?,
                process_name = ?,
                pid = ?,
                text = ?,
                source = ?,
                tab_title = ?,
                url = ?,
                content_fingerprint = ?,
                last_seen = ?,
                timestamp = ?
            WHERE id = ?
            """,
            (
                snapshot.window_info.app_name,
                snapshot.window_info.title,
                snapshot.window_info.process_name,
                snapshot.window_info.pid,
                snapshot.text,
                snapshot.source.value,
                snapshot.tab_title,
                snapshot.url,
                fingerprint,
                snapshot.timestamp,
                snapshot.timestamp,
                snapshot_id,
            ),
        )
        self._conn.commit()
        logger.debug(
            "Updated snapshot %s: %s (%s chars)",
            snapshot_id,
            snapshot.window_info.app_name,
            len(snapshot.text),
        )

    def find_snapshot_id_by_fingerprint(
        self,
        snapshot: WindowContextSnapshot,
        exclude_id: Optional[int] = None,
    ) -> Optional[int]:
        """Return an existing row id for the snapshot fingerprint, if present."""
        fingerprint = snapshot_fingerprint(snapshot)
        if exclude_id is None:
            row = self._conn.execute(
                """
                SELECT id
                FROM window_snapshots
                WHERE content_fingerprint = ?
                ORDER BY last_seen DESC, id DESC
                LIMIT 1
                """,
                (fingerprint,),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT id
                FROM window_snapshots
                WHERE content_fingerprint = ? AND id != ?
                ORDER BY last_seen DESC, id DESC
                LIMIT 1
                """,
                (fingerprint, exclude_id),
            ).fetchone()
        return int(row["id"]) if row else None

    def get_recent(self, limit: int = 20) -> List[WindowContextSnapshot]:
        """Return the most recent snapshots, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM window_snapshots ORDER BY COALESCE(last_seen, timestamp) DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def search(self, query: str) -> List[WindowContextSnapshot]:
        """Search snapshots by text content, window title, or URL."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT * FROM window_snapshots
            WHERE text LIKE ? OR window_title LIKE ? OR url LIKE ?
            ORDER BY COALESCE(last_seen, timestamp) DESC
            """,
            (pattern, pattern, pattern),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def get_debug_rows(self, limit: int = 50) -> list[sqlite3.Row]:
        """Return viewer-friendly snapshot rows for the live database window."""
        return self._conn.execute(
            """
            SELECT id,
                   app_name,
                   window_title,
                   first_seen,
                   last_seen,
                   content_fingerprint,
                   replace(replace(text, char(10), ' '), char(13), ' ') AS text_preview
            FROM window_snapshots
            ORDER BY COALESCE(last_seen, timestamp) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> WindowContextSnapshot:
        """Convert a database row back into a WindowContextSnapshot."""
        return WindowContextSnapshot(
            window_info=WindowInfo(
                title=row["window_title"],
                app_name=row["app_name"],
                process_name=row["process_name"],
                pid=row["pid"],
            ),
            text=row["text"],
            source=TextSource(row["source"]),
            tab_title=row["tab_title"],
            url=row["url"],
            timestamp=row["last_seen"] if "last_seen" in row.keys() and row["last_seen"] is not None else row["timestamp"],
        )

    def set_pref(self, key: str, value: str) -> None:
        """Store a preference (upsert)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_pref(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a preference, or return *default* if not set."""
        row = self._conn.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (key,),
        ).fetchone()
        return row["value"] if row else default

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
        logger.info("SparkDB closed")

    def delete_n_oldest_snapshots(self, count: int = 100) -> None:
        """Delete the 'n' oldest snapshots from the database."""
        self._conn.execute(
            """
            DELETE FROM window_snapshots
            WHERE id IN (
                SELECT id FROM window_snapshots
                ORDER BY COALESCE(last_seen, timestamp) ASC
                LIMIT ?
            )
            """,
            (count,),
        )
        self._conn.commit()
        logger.info("Deleted the %s oldest snapshots.", count)
