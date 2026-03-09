"""
SQLite database layer for persisting window context snapshots.

Stores the full text content of each window visit so context
is available across sessions and can be queried later.
"""

import sqlite3
import logging
from pathlib import Path
from typing import List, Optional

from .accessibility.base import WindowInfo, WindowContextSnapshot, TextSource

logger = logging.getLogger(__name__)


class SparkDB:
    """SQLite-backed storage for window context snapshots."""

    def __init__(self, db_path: str = "spark.db"):
        self._path = Path(db_path)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate()
        logger.info(f"SparkDB opened at {self._path.resolve()}")

    def _create_tables(self) -> None:
        self._conn.execute("""
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
                timestamp     REAL    NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns that may be missing from older databases."""
        columns = {
            row[1]
            for row in self._conn.execute(
                "PRAGMA table_info(window_snapshots)"
            ).fetchall()
        }
        for col in ("tab_title", "url"):
            if col not in columns:
                self._conn.execute(
                    f"ALTER TABLE window_snapshots ADD COLUMN {col} TEXT"
                )
                logger.info(f"Migrated: added '{col}' column to window_snapshots")
        self._conn.commit()

    def save_snapshot(self, snapshot: WindowContextSnapshot) -> None:
        """Insert a window context snapshot into the database."""
        self._conn.execute(
            """
            INSERT INTO window_snapshots
                (app_name, window_title, process_name, pid, text, source,
                 tab_title, url, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                snapshot.timestamp,
            ),
        )
        self._conn.commit()
        logger.debug(
            f"Saved snapshot: {snapshot.window_info.app_name} — "
            f"{len(snapshot.text)} chars"
        )

    def get_recent(self, limit: int = 20) -> List[WindowContextSnapshot]:
        """Return the most recent snapshots, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM window_snapshots ORDER BY timestamp DESC LIMIT ?",
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
            ORDER BY timestamp DESC
            """,
            (pattern, pattern, pattern),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

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
            timestamp=row["timestamp"],
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
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
        logger.info("SparkDB closed")

    def delete_n_oldest_snapshots(self, count: int = 100) -> None:
        """Delete the 'n' oldest snapshots from the database."""
        self._conn.execute("""
            DELETE FROM window_snapshots 
            WHERE id IN (
                SELECT id FROM window_snapshots 
                ORDER BY timestamp ASC 
                LIMIT ?
            )
        """, (count,))
        self._conn.commit()
        logger.info(f"Deleted the {count} oldest snapshots.")
