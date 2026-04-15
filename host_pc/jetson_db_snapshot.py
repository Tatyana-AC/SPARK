"""Helpers for creating validated, read-only Jetson DB snapshots."""

from __future__ import annotations

import sqlite3
import logging
import shutil
import tempfile
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
import re
import time


DEFAULT_JETSON_DB_PATH = Path(r"Z:\demo\pico_bridge\jetson_spark.db")
_logger = logging.getLogger(__name__)


class SnapshotError(Exception):
    """Raised when a snapshot cannot be created or validated."""


@dataclass
class SnapshotHandle:
    """Metadata-only handle for a validated snapshot database."""

    path: Path


@dataclass
class TablePage:
    """A single bounded page of rows returned from a snapshot table."""

    table_name: str
    rows: list[dict[str, object]]
    has_more: bool


def delete_snapshot(handle_or_path: SnapshotHandle | Path | str) -> None:
    """Delete a snapshot file and its temporary directory if present."""
    snapshot_path = handle_or_path.path if isinstance(handle_or_path, SnapshotHandle) else _as_path(handle_or_path)
    if not snapshot_path.exists():
        return

    if isinstance(handle_or_path, SnapshotHandle) or _looks_like_snapshot_artifact(snapshot_path):
        _cleanup_snapshot(snapshot_path.parent, snapshot_path)
        return

    _logger.warning("delete_snapshot received non-snapshot path, skipping parent cleanup: %s", snapshot_path)


def _looks_like_snapshot_artifact(snapshot_path: Path) -> bool:
    return snapshot_path.name == "jetson_spark.db" and snapshot_path.parent.name.startswith("spark_snapshot_")


def _as_path(path: Path | str) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _open_sqlite_read_only(snapshot_path: Path) -> sqlite3.Connection:
    path_for_uri = quote(snapshot_path.resolve().as_posix(), safe=":/")
    uri = f"file:{path_for_uri}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def open_snapshot_connection(snapshot_path: Path | str) -> sqlite3.Connection:
    """Open a read-only connection to a snapshot path using URI mode."""
    snapshot_path = _as_path(snapshot_path)
    if not snapshot_path.exists():
        raise SnapshotError(f"Snapshot DB missing: {snapshot_path}")
    return _open_sqlite_read_only(snapshot_path)


def list_user_tables(snapshot_path: Path | str) -> list[str]:
    """List user tables in deterministic display order."""
    with open_snapshot_connection(snapshot_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name ASC
            """
        ).fetchall()

    tables = [row[0] for row in rows]
    preferred = [name for name in ("sessions", "button_events") if name in tables]
    remainder = sorted(name for name in tables if name not in preferred)
    return preferred + remainder


def _infer_fallback_table_order(connection: sqlite3.Connection, table_name: str) -> str | None:
    try:
        connection.execute(f"SELECT rowid FROM {table_name} LIMIT 1").fetchone()
        return "rowid DESC"
    except sqlite3.OperationalError:
        table_info = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        pk_columns = [str(row[1]) for row in table_info if row[5] > 0]
        if not pk_columns:
            return None
        return ", ".join(f'"{name}"' for name in pk_columns) + " DESC"


def _table_order_clause(connection: sqlite3.Connection, table_name: str) -> str | None:
    if table_name == "sessions":
        return "updated_at DESC, id DESC"
    if table_name == "button_events":
        return "timestamp DESC, id DESC"
    return _infer_fallback_table_order(connection, table_name)


def load_table_rows(
    snapshot_path: Path | str,
    table_name: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> TablePage:
    """Load a bounded page of rows for a snapshot table."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise SnapshotError("limit must be a positive integer")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise SnapshotError("offset must be a non-negative integer")

    _validate_table_name(snapshot_path, table_name)
    page_size = limit + 1

    with open_snapshot_connection(snapshot_path) as connection:
        connection.row_factory = sqlite3.Row
        order_clause = _table_order_clause(connection, table_name)
        query = (
            f"SELECT * FROM {table_name} "
            f"{('ORDER BY ' + order_clause + ' ') if order_clause else ''}"
            "LIMIT ? OFFSET ?"
        )
        rows = connection.execute(query, (page_size, offset)).fetchall()

    has_more = len(rows) > limit
    row_dicts = [dict(row) for row in rows[:limit]]
    return TablePage(table_name=table_name, rows=row_dicts, has_more=has_more)


_PERMANENT_RETRY_BLOCKING_PREFIXES = (
    "Source DB missing",
    "Source DB is not a file",
    "Failed to validate snapshot DB:",
)


_TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_table_name(snapshot_path: Path | str, table_name: str) -> None:
    if not isinstance(table_name, str) or not _TABLE_NAME_PATTERN.fullmatch(table_name):
        raise SnapshotError(f"Unknown or invalid table: {table_name}")

    if table_name not in list_user_tables(snapshot_path):
        raise SnapshotError(f"Unknown or invalid table: {table_name}")


def _is_retryable_snapshot_error(error: SnapshotError) -> bool:
    message = str(error)
    return not any(message.startswith(prefix) for prefix in _PERMANENT_RETRY_BLOCKING_PREFIXES)


def create_snapshot_with_retry(
    source_path: Path | str | None = None,
    *,
    attempts: int = 3,
    delay_s: float = 0.05,
) -> SnapshotHandle:
    """Create snapshots with bounded retries for transient setup failures."""
    source = _as_path(source_path) if source_path is not None else DEFAULT_JETSON_DB_PATH
    if not source.exists():
        raise SnapshotError(f"Source DB missing: {source}")
    if not source.is_file():
        raise SnapshotError(f"Source DB is not a file: {source}")

    if attempts <= 0:
        raise SnapshotError("attempts must be positive")

    for attempt in range(attempts):
        try:
            return create_validated_snapshot(source)
        except SnapshotError as error:
            if not _is_retryable_snapshot_error(error):
                raise
            if attempt >= attempts - 1:
                raise SnapshotError(f"Failed to create snapshot after {attempts} attempts") from error
            time.sleep(delay_s)
        except Exception:
            raise


def _validate_snapshot_db(connection: sqlite3.Connection) -> None:
    master_row = connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    if master_row is None:
        raise SnapshotError("Snapshot DB is empty")

    integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
    if not integrity_row:
        raise SnapshotError("Snapshot DB missing integrity result")
    if str(integrity_row[0]).lower() != "ok":
        raise SnapshotError("Snapshot DB failed integrity check")


def _make_snapshot_path() -> tuple[Path, Path]:
    snapshot_dir = Path(tempfile.mkdtemp(prefix="spark_snapshot_"))
    snapshot_path = snapshot_dir / "jetson_spark.db"
    return snapshot_dir, snapshot_path


def _cleanup_snapshot(snapshot_dir: Path, snapshot_path: Path) -> None:
    try:
        if snapshot_path.exists():
            snapshot_path.unlink()
    except OSError as error:
        _logger.warning("Failed to remove snapshot file %s: %s", snapshot_path, error)
    try:
        if snapshot_path.parent.exists() and snapshot_path.parent.is_dir():
            shutil.rmtree(snapshot_dir)
    except OSError as error:
        _logger.warning("Failed to remove snapshot directory %s: %s", snapshot_dir, error)


def create_validated_snapshot(source_path: Path | str | None = None) -> SnapshotHandle:
    """Create a validated snapshot copy and return its metadata handle."""
    source = _as_path(source_path) if source_path is not None else DEFAULT_JETSON_DB_PATH

    if not source.exists():
        raise SnapshotError(f"Source DB missing: {source}")

    snapshot_dir, snapshot_path = _make_snapshot_path()

    try:
        try:
            shutil.copyfile(source, snapshot_path)
        except Exception as error:
            _cleanup_snapshot(snapshot_dir, snapshot_path)
            raise SnapshotError(f"Failed to copy source database to snapshot: {error}") from error

        try:
            connection = open_snapshot_connection(snapshot_path)
            try:
                _validate_snapshot_db(connection)
            finally:
                connection.close()
        except Exception as error:
            _cleanup_snapshot(snapshot_dir, snapshot_path)
            if isinstance(error, SnapshotError):
                raise SnapshotError(f"Failed to validate snapshot DB: {error}") from error
            raise SnapshotError(f"Failed to open snapshot DB: {error}") from error

        return SnapshotHandle(path=snapshot_path)
    except Exception as error:
        if isinstance(error, SnapshotError):
            raise
        raise SnapshotError("Failed to create validated snapshot") from error
