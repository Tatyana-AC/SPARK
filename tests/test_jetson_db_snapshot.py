import sqlite3
import logging

import host_pc.jetson_db_snapshot as snapshot_mod

import pytest

from host_pc.jetson_db_snapshot import (
    SnapshotError,
    create_validated_snapshot,
    delete_snapshot,
    open_snapshot_connection,
    list_user_tables,
    load_table_rows,
    create_snapshot_with_retry,
)


def _make_source_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE windows(id INTEGER PRIMARY KEY, name TEXT);
            INSERT INTO windows(name) VALUES ('main');
            """,
        )
        conn.commit()
    finally:
        conn.close()


def _make_snapshot_source_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context_key TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                app_name TEXT NOT NULL,
                window_title TEXT NOT NULL,
                process_name TEXT NOT NULL,
                pid INTEGER NOT NULL,
                source TEXT NOT NULL,
                tab_title TEXT,
                url TEXT,
                text TEXT NOT NULL DEFAULT '',
                host_observed_at REAL,
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE button_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                button_id INTEGER NOT NULL,
                session_id INTEGER,
                timestamp REAL NOT NULL
            );
            CREATE TABLE other_table(id INTEGER PRIMARY KEY);
            INSERT INTO sessions (context_key, content_fingerprint, app_name, window_title, process_name, pid, source, text, started_at, updated_at)
            VALUES
              ('a', 'a', 'a', 'a', 'a', 1, 'a', 'row1', 1, 1),
              ('b', 'b', 'b', 'b', 'b', 2, 'b', 'row2', 2, 2),
              ('c', 'c', 'c', 'c', 'c', 3, 'c', 'row3', 3, 3);
            INSERT INTO button_events (button_id, session_id, timestamp) VALUES (11, 1, 10);
            INSERT INTO button_events (button_id, session_id, timestamp) VALUES (12, 2, 20);
            INSERT INTO button_events (button_id, session_id, timestamp) VALUES (13, 3, 30);
            INSERT INTO other_table (id) VALUES (1);
            """,
        )
        conn.commit()
    finally:
        conn.close()


def test_create_validated_snapshot_copies_source_db_to_unique_temp_path(tmp_path):
    source_path = tmp_path / "source.db"
    _make_source_db(source_path)

    handle = create_validated_snapshot(source_path)
    assert handle.path.exists()
    assert handle.path != source_path
    assert handle.path.suffix == ".db"
    assert handle.path.parent != tmp_path

    with open_snapshot_connection(handle.path) as connection:
        check = connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        assert check is not None


def test_create_validated_snapshot_rejects_missing_source(tmp_path):
    source_path = tmp_path / "missing.db"

    with pytest.raises(SnapshotError):
        create_validated_snapshot(source_path)


def test_open_snapshot_connection_uses_read_only_mode(tmp_path, monkeypatch):
    db_path = tmp_path / "source.db"
    _make_source_db(db_path)

    calls = []
    original_connect = sqlite3.connect

    def fake_connect(database, *args, **kwargs):
        calls.append((database, args, kwargs))
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr("host_pc.jetson_db_snapshot.sqlite3.connect", fake_connect)

    with open_snapshot_connection(db_path) as connection:
        connection.execute("SELECT 1")

    assert len(calls) == 1
    database, _, kwargs = calls[0]
    assert isinstance(database, str)
    assert database.startswith("file:")
    assert "?mode=ro" in database
    assert kwargs.get("uri") is True


def test_open_snapshot_connection_is_read_only(tmp_path):
    db_path = tmp_path / "source.db"
    _make_source_db(db_path)

    with open_snapshot_connection(db_path) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO windows(name) VALUES ('blocked')")


def test_open_snapshot_connection_escapes_uri_path(tmp_path, monkeypatch):
    db_path = tmp_path / "db with space.db"
    _make_source_db(db_path)

    calls = []
    original_connect = sqlite3.connect

    def fake_connect(database, *args, **kwargs):
        calls.append((database, args, kwargs))
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr("host_pc.jetson_db_snapshot.sqlite3.connect", fake_connect)

    with open_snapshot_connection(db_path) as connection:
        connection.execute("SELECT 1")

    assert len(calls) == 1
    _, _, kwargs = calls[0]
    assert kwargs.get("uri") is True
    assert "%20" in calls[0][0]


def test_create_validated_snapshot_uses_default_source_path_if_none(tmp_path, monkeypatch):
    default_source = tmp_path / "default_source.db"
    _make_source_db(default_source)

    monkeypatch.setattr(snapshot_mod, "DEFAULT_JETSON_DB_PATH", default_source)

    handle = create_validated_snapshot()
    assert handle.path.exists()
    assert handle.path != default_source


def test_create_validated_snapshot_copy_stage_error_is_reported(tmp_path, monkeypatch):
    source_path = tmp_path / "source.db"
    _make_source_db(source_path)

    def fail_copy(*args, **kwargs):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(snapshot_mod.shutil, "copyfile", fail_copy)
    with pytest.raises(SnapshotError, match="Failed to copy"):
        create_validated_snapshot(source_path)


def test_create_validated_snapshot_cleanup_failure_is_logged(tmp_path, caplog, monkeypatch):
    source_path = tmp_path / "empty.db"
    conn = sqlite3.connect(source_path)
    conn.close()

    def fail_rmtree(*args, **kwargs):
        raise OSError("delete failed")

    with caplog.at_level(logging.WARNING):
        monkeypatch.setattr(snapshot_mod.shutil, "rmtree", fail_rmtree)
        with pytest.raises(SnapshotError):
            create_validated_snapshot(source_path)

    assert any("Failed to remove snapshot directory" in rec.message for rec in caplog.records)


def test_create_validated_snapshot_cleans_up_temp_artifacts_after_validation_failure(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "empty.db"
    conn = sqlite3.connect(source_path)
    conn.close()

    snapshot_dir = tmp_path / "snapshot_artifacts"

    def fake_mkdtemp(*args, **kwargs):
        snapshot_dir.mkdir()
        return str(snapshot_dir)

    monkeypatch.setattr("host_pc.jetson_db_snapshot.tempfile.mkdtemp", fake_mkdtemp)

    with pytest.raises(SnapshotError):
        create_validated_snapshot(source_path)

    assert not snapshot_dir.exists()


def test_create_validated_snapshot_cleanup_removes_artifacts(tmp_path):
    source_path = tmp_path / "source.db"
    _make_source_db(source_path)

    handle = create_validated_snapshot(source_path)
    snapshot_path = handle.path
    snapshot_dir = snapshot_path.parent

    delete_snapshot(handle)

    assert not snapshot_path.exists()
    assert not snapshot_dir.exists()


def test_delete_snapshot_removes_snapshot_file_and_parent_dir(tmp_path):
    source_path = tmp_path / "source.db"
    _make_source_db(source_path)

    handle = create_validated_snapshot(source_path)
    snapshot_path = handle.path
    snapshot_dir = snapshot_path.parent

    delete_snapshot(handle)

    assert not snapshot_path.exists()
    assert not snapshot_dir.exists()


def test_delete_snapshot_missing_path_is_tolerated(tmp_path):
    missing_path = tmp_path / "does_not_exist.db"

    delete_snapshot(missing_path)

    assert not missing_path.exists()


def test_delete_snapshot_non_snapshot_path_does_not_remove_parent(tmp_path, caplog):
    work_dir = tmp_path / "not_a_snapshot"
    work_dir.mkdir()
    file_path = work_dir / "notes.txt"
    file_path.write_text("keep this")

    with caplog.at_level(logging.WARNING):
        delete_snapshot(file_path)

    assert work_dir.exists()
    assert file_path.exists()
    assert any("non-snapshot path" in rec.message for rec in caplog.records)


def test_list_user_tables_returns_sessions_button_events_and_unknown_tables(tmp_path):
    source_path = tmp_path / "source.db"
    _make_snapshot_source_db(source_path)

    handle = create_validated_snapshot(source_path)

    assert list_user_tables(handle.path) == [
        "sessions",
        "button_events",
        "other_table",
    ]


def test_load_table_rows_pages_sessions_newest_first(tmp_path):
    source_path = tmp_path / "source.db"
    _make_snapshot_source_db(source_path)

    handle = create_validated_snapshot(source_path)
    first_page = load_table_rows(handle.path, "sessions", limit=2, offset=0)

    assert [row["id"] for row in first_page.rows] == [3, 2]
    assert first_page.has_more

    second_page = load_table_rows(handle.path, "sessions", limit=2, offset=2)
    assert [row["id"] for row in second_page.rows] == [1]
    assert not second_page.has_more


def test_load_table_rows_orders_sessions_by_host_observed_at_before_updated_at(tmp_path):
    source_path = tmp_path / "source.db"
    conn = sqlite3.connect(source_path)
    try:
        conn.executescript(
            """
            CREATE TABLE sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context_key TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                app_name TEXT NOT NULL,
                window_title TEXT NOT NULL,
                process_name TEXT NOT NULL,
                pid INTEGER NOT NULL,
                source TEXT NOT NULL,
                tab_title TEXT,
                url TEXT,
                text TEXT NOT NULL DEFAULT '',
                host_observed_at REAL,
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            INSERT INTO sessions (context_key, content_fingerprint, app_name, window_title, process_name, pid, source, text, host_observed_at, started_at, updated_at)
            VALUES
              ('a', 'a', 'older-host', 'older-host', 'a', 1, 'a', 'row1', 100.0, 10.0, 500.0),
              ('b', 'b', 'newer-host', 'newer-host', 'b', 2, 'b', 'row2', 300.0, 20.0, 100.0),
              ('c', 'c', 'middle-host', 'middle-host', 'c', 3, 'c', 'row3', 200.0, 30.0, 400.0);
            """
        )
        conn.commit()
    finally:
        conn.close()

    handle = create_validated_snapshot(source_path)
    first_page = load_table_rows(handle.path, "sessions", limit=3, offset=0)

    assert [row["app_name"] for row in first_page.rows] == ["newer-host", "middle-host", "older-host"]


def test_load_table_rows_uses_primary_key_order_for_without_rowid_table(tmp_path):
    source_path = tmp_path / "without_rowid.db"
    conn = sqlite3.connect(source_path)
    try:
        conn.executescript(
            """
            CREATE TABLE log_entries(
                event_id INTEGER NOT NULL,
                event_time INTEGER NOT NULL,
                message TEXT NOT NULL,
                PRIMARY KEY(event_id)
            ) WITHOUT ROWID;
            INSERT INTO log_entries(event_id, event_time, message)
            VALUES (5, 30, 'three'), (1, 10, 'one'), (3, 20, 'two');
            """
        )
        conn.commit()
    finally:
        conn.close()

    handle = create_validated_snapshot(source_path)
    rows = load_table_rows(handle.path, "log_entries", limit=10, offset=0)

    assert [row["event_id"] for row in rows.rows] == [5, 3, 1]


def test_load_table_rows_rejects_invalid_table_name(tmp_path):
    source_path = tmp_path / "source.db"
    _make_snapshot_source_db(source_path)

    handle = create_validated_snapshot(source_path)

    with pytest.raises(SnapshotError, match="Unknown or invalid table"):
        load_table_rows(handle.path, "sessions; DROP TABLE sessions; --")


def test_load_table_rows_rejects_invalid_paging_args(tmp_path):
    source_path = tmp_path / "source.db"
    _make_snapshot_source_db(source_path)

    handle = create_validated_snapshot(source_path)

    with pytest.raises(SnapshotError, match="limit must be a positive integer"):
        load_table_rows(handle.path, "sessions", limit=0)

    with pytest.raises(SnapshotError, match="offset must be a non-negative integer"):
        load_table_rows(handle.path, "sessions", offset=-1)

    with pytest.raises(SnapshotError, match="limit must be a positive integer"):
        load_table_rows(handle.path, "sessions", limit=-10)

    with pytest.raises(SnapshotError, match="offset must be a non-negative integer"):
        load_table_rows(handle.path, "sessions", offset="bad")


def test_list_user_tables_prefers_known_tables_and_sorts_deterministically_when_absent(tmp_path):
    source_path = tmp_path / "source.db"
    conn = sqlite3.connect(source_path)
    try:
        conn.executescript(
            """
            CREATE TABLE zed_table(id INTEGER PRIMARY KEY);
            CREATE TABLE alpha_table(id INTEGER PRIMARY KEY);
            CREATE TABLE another_table(id INTEGER PRIMARY KEY);
            """
        )
        conn.commit()
    finally:
        conn.close()

    handle = create_validated_snapshot(source_path)

    assert list_user_tables(handle.path) == [
        "alpha_table",
        "another_table",
        "zed_table",
    ]


def test_list_user_tables_closes_snapshot_connection_even_with_context_manager(tmp_path, monkeypatch):
    class _FakeConnection:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            class _Rows:
                def fetchall(self_inner):
                    return [("sessions",)]

            return _Rows()

        def close(self):
            self.closed = True

    fake_connection = _FakeConnection()
    monkeypatch.setattr(snapshot_mod, "open_snapshot_connection", lambda _path: fake_connection)

    tables = list_user_tables(tmp_path / "snapshot.db")

    assert tables == ["sessions"]
    assert fake_connection.closed is True


def test_load_table_rows_closes_snapshot_connection_even_with_context_manager(tmp_path, monkeypatch):
    class _FakeConnection:
        def __init__(self):
            self.closed = False
            self.row_factory = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, *_args, **_kwargs):
            if "sqlite_master" in sql:
                class _Rows:
                    def fetchall(self_inner):
                        return [("sessions",)]

                return _Rows()
            if "PRAGMA table_info" in sql:
                class _Rows:
                    def fetchall(self_inner):
                        return []

                return _Rows()
            class _Rows:
                def fetchall(self_inner):
                    return [sqlite3.Row]

            return _Rows()

        def close(self):
            self.closed = True

    fake_connection = _FakeConnection()
    monkeypatch.setattr(snapshot_mod, "open_snapshot_connection", lambda _path: fake_connection)
    monkeypatch.setattr(snapshot_mod, "list_user_tables", lambda _path: ["sessions"])
    monkeypatch.setattr(snapshot_mod, "_table_order_clause", lambda *_args, **_kwargs: None)

    class _Row(dict):
        pass

    fake_connection.execute = lambda sql, *_args, **_kwargs: type(
        "_Rows",
        (),
        {"fetchall": lambda self: [_Row(id=1, text="row1")]},
    )()

    page = load_table_rows(tmp_path / "snapshot.db", "sessions", limit=1, offset=0)

    assert page.rows == [{"id": 1, "text": "row1"}]
    assert fake_connection.closed is True


def test_default_jetson_db_path_is_used_when_no_source_path_is_provided(tmp_path, monkeypatch):
    default_source = tmp_path / "default_source.db"
    _make_snapshot_source_db(default_source)

    monkeypatch.setattr(snapshot_mod, "DEFAULT_JETSON_DB_PATH", default_source)

    handle = create_snapshot_with_retry()
    assert handle.path.exists()
    assert handle.path != default_source


def test_create_snapshot_with_retry_retries_transient_failures_then_succeeds(tmp_path, monkeypatch):
    source_path = tmp_path / "source.db"
    _make_snapshot_source_db(source_path)

    original_copyfile = snapshot_mod.shutil.copyfile
    calls = {"count": 0}

    def flaky_copyfile(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("temporary copy failure")
        return original_copyfile(*args, **kwargs)

    monkeypatch.setattr(snapshot_mod.shutil, "copyfile", flaky_copyfile)

    handle = create_snapshot_with_retry(source_path, attempts=3, delay_s=0)
    assert handle.path.exists()
    assert calls["count"] == 3


def test_create_snapshot_with_retry_exhausts_attempts_for_transient_failures(tmp_path, monkeypatch):
    source_path = tmp_path / "source.db"
    _make_snapshot_source_db(source_path)

    def always_fail_copyfile(*args, **kwargs):
        raise RuntimeError("temporary copy failure")

    monkeypatch.setattr(snapshot_mod.shutil, "copyfile", always_fail_copyfile)

    with pytest.raises(SnapshotError, match="Failed to create snapshot after 3 attempts"):
        create_snapshot_with_retry(source_path, attempts=3, delay_s=0)


def test_create_snapshot_with_retry_does_not_retry_missing_source(tmp_path):
    missing_source = tmp_path / "missing.db"

    with pytest.raises(SnapshotError, match="Source DB missing"):
        create_snapshot_with_retry(missing_source, attempts=3, delay_s=0)


def test_create_snapshot_with_retry_does_not_retry_directory_source(tmp_path, monkeypatch):
    source_dir = tmp_path / "source_dir"
    source_dir.mkdir()

    copy_calls = {"count": 0}
    original_copyfile = snapshot_mod.shutil.copyfile

    def counting_copyfile(*args, **kwargs):
        copy_calls["count"] += 1
        return original_copyfile(*args, **kwargs)

    monkeypatch.setattr(snapshot_mod.shutil, "copyfile", counting_copyfile)

    with pytest.raises(SnapshotError, match="Source DB is not a file"):
        create_snapshot_with_retry(source_dir, attempts=3, delay_s=0)

    assert copy_calls["count"] == 0


def test_create_snapshot_with_retry_does_not_retry_validation_errors(tmp_path, monkeypatch):
    source_path = tmp_path / "invalid.db"
    source_path.write_bytes(b"")

    copy_calls = {"count": 0}
    original_copyfile = snapshot_mod.shutil.copyfile

    def counting_copyfile(*args, **kwargs):
        copy_calls["count"] += 1
        return original_copyfile(*args, **kwargs)

    monkeypatch.setattr(snapshot_mod.shutil, "copyfile", counting_copyfile)

    with pytest.raises(SnapshotError, match="Failed to validate snapshot DB"):
        create_snapshot_with_retry(source_path, attempts=3, delay_s=0)

    assert copy_calls["count"] == 1
