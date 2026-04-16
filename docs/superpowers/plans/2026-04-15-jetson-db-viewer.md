# Jetson DB Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, manual-refresh Jetson DB viewer to the SPARK host app that inspects a local snapshot of the Jetson SQLite database instead of opening the live `Z:\` file directly.

**Architecture:** Add one small host-side snapshot/query helper in `host_pc/jetson_db_snapshot.py`, then wire a read-only Qt dialog into `spark_app_v2.py` behind a new `View Jetson DB` action. Keep all live-file handling out of the dialog itself: the UI asks the helper for a validated local snapshot, discovers available tables, and renders paged rows from the snapshot only.

**Tech Stack:** Python 3, standard library (`sqlite3`, `tempfile`, `shutil`, `pathlib`, `threading`, `time`), PyQt6, existing unittest/pytest patterns.

---

## File Map

- Create: `host_pc/jetson_db_snapshot.py`
  Centralize the default Jetson DB path, snapshot copy/validation, explicit read-only snapshot opens, schema discovery, paged row loading, and temp-file cleanup.
- Modify: `spark_app_v2.py`
  Add the new `View Jetson DB` action, read-only viewer dialog, refresh-state handling, background refresh worker integration, and user-facing status/error text.
- Create: `tests/test_jetson_db_snapshot.py`
  Unit tests for snapshot creation, validation, read-only access, table discovery, paged loading, and cleanup behavior.
- Modify: `tests/test_spark_panel_ui.py`
  Keep the main panel action-grid assertions current and verify the new Jetson DB action is visible and wired.
- Create: `tests/test_jetson_db_viewer_ui.py`
  Focused `unittest`-style Qt tests for dialog refresh behavior, disabled refresh during single-flight load, table selector population, paging controls, retry exhaustion, and failure-state messaging.
- Reference: `docs/superpowers/specs/2026-04-15-jetson-db-viewer-design.md`

## Task 1: Build Snapshot Creation And Validation Helper

**Files:**
- Create: `host_pc/jetson_db_snapshot.py`
- Test: `tests/test_jetson_db_snapshot.py`

- [ ] **Step 1: Write the failing tests for snapshot creation and validation**

```python
import sqlite3


def test_create_validated_snapshot_copies_source_db_to_unique_temp_path(tmp_path):
    from host_pc.jetson_db_snapshot import create_validated_snapshot

    source = tmp_path / "jetson_spark.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, app_name TEXT)")
    conn.execute("INSERT INTO sessions (app_name) VALUES ('Firefox')")
    conn.commit()
    conn.close()

    snapshot = create_validated_snapshot(source)

    assert snapshot.source_path == source
    assert snapshot.snapshot_path != source
    assert snapshot.snapshot_path.exists()


def test_create_validated_snapshot_rejects_missing_source(tmp_path):
    from host_pc.jetson_db_snapshot import SnapshotError, create_validated_snapshot

    missing = tmp_path / "missing.db"

    with pytest.raises(SnapshotError):
        create_validated_snapshot(missing)


def test_open_snapshot_connection_uses_read_only_mode(tmp_path, monkeypatch):
    import sqlite3
    from host_pc.jetson_db_snapshot import create_validated_snapshot, open_snapshot_connection

    source = tmp_path / "jetson_spark.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, app_name TEXT)")
    conn.commit()
    conn.close()

    snapshot = create_validated_snapshot(source)

    captured = {}
    real_connect = sqlite3.connect

    def recording_connect(path, *args, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)

    conn = open_snapshot_connection(snapshot.snapshot_path)
    conn.close()

    assert "mode=ro" in captured["path"]
    assert captured["kwargs"].get("uri") is True


def test_create_validated_snapshot_cleans_up_temp_artifacts_after_validation_failure(tmp_path, monkeypatch):
    import tempfile
    from host_pc.jetson_db_snapshot import SnapshotError, create_validated_snapshot

    source = tmp_path / "jetson_spark.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    failed_temp_dir = tmp_path / "spark_jetson_db_failed"
    def fake_mkdtemp(prefix):
        failed_temp_dir.mkdir()
        return str(failed_temp_dir)

    monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp)

    def broken_open_snapshot_connection(_snapshot_path):
        assert _snapshot_path.exists()
        raise SnapshotError("Snapshot integrity check failed")

    monkeypatch.setattr(
        "host_pc.jetson_db_snapshot.open_snapshot_connection",
        broken_open_snapshot_connection,
    )

    with pytest.raises(SnapshotError):
        create_validated_snapshot(source)

    assert not failed_temp_dir.exists()
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_jetson_db_snapshot.py::test_create_validated_snapshot_copies_source_db_to_unique_temp_path tests/test_jetson_db_snapshot.py::test_open_snapshot_connection_uses_read_only_mode tests/test_jetson_db_snapshot.py::test_create_validated_snapshot_cleans_up_temp_artifacts_after_validation_failure -v`
Expected: FAIL because `host_pc.jetson_db_snapshot` does not exist yet.

- [ ] **Step 3: Write the minimal snapshot helper implementation**

```python
from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time


DEFAULT_JETSON_DB_PATH = Path(r"Z:\demo\pico_bridge\jetson_spark.db")


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotHandle:
    source_path: Path
    snapshot_path: Path
    created_at: float


def open_snapshot_connection(snapshot_path: Path) -> sqlite3.Connection:
    uri = f"file:{snapshot_path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def create_validated_snapshot(source_path: Path | str | None = None) -> SnapshotHandle:
    source = Path(source_path or DEFAULT_JETSON_DB_PATH)
    if not source.exists():
        raise SnapshotError(f"Jetson DB not found: {source}")

    temp_dir = Path(tempfile.mkdtemp(prefix="spark_jetson_db_"))
    snapshot_path = temp_dir / f"snapshot_{int(time.time() * 1000)}.db"
    shutil.copy2(source, snapshot_path)
    if snapshot_path.stat().st_size <= 0:
        raise SnapshotError("Copied snapshot is empty")

    conn = open_snapshot_connection(snapshot_path)
    try:
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise SnapshotError("Snapshot integrity check failed")
    finally:
        conn.close()

    return SnapshotHandle(source_path=source, snapshot_path=snapshot_path, created_at=time.time())
```

- [ ] **Step 4: Add cleanup for failed snapshot attempts**

Wrap temp-directory creation and validation in `try`/`except`/`finally` so a failed copy or failed validation deletes the abandoned snapshot file and temp directory before re-raising `SnapshotError`.

- [ ] **Step 5: Run the focused tests to verify they pass**

Run: `pytest tests/test_jetson_db_snapshot.py::test_create_validated_snapshot_copies_source_db_to_unique_temp_path tests/test_jetson_db_snapshot.py::test_open_snapshot_connection_uses_read_only_mode tests/test_jetson_db_snapshot.py::test_create_validated_snapshot_cleans_up_temp_artifacts_after_validation_failure -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add host_pc/jetson_db_snapshot.py tests/test_jetson_db_snapshot.py
git commit -m "feat: add Jetson DB snapshot helper"
```

## Task 2: Add Schema Discovery, Paging, And Snapshot Cleanup

**Files:**
- Modify: `host_pc/jetson_db_snapshot.py`
- Test: `tests/test_jetson_db_snapshot.py`

- [ ] **Step 1: Write the failing tests for table discovery and paged row loading**

```python
def test_list_user_tables_returns_sessions_button_events_and_unknown_tables(tmp_path):
    from host_pc.jetson_db_snapshot import create_validated_snapshot, list_user_tables

    source = tmp_path / "jetson_spark.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, updated_at REAL)")
    conn.execute("CREATE TABLE button_events (id INTEGER PRIMARY KEY, timestamp REAL)")
    conn.execute("CREATE TABLE debug_notes (id INTEGER PRIMARY KEY, note TEXT)")
    conn.commit()
    conn.close()

    snapshot = create_validated_snapshot(source)

    assert list_user_tables(snapshot.snapshot_path) == ["sessions", "button_events", "debug_notes"]


def test_load_table_rows_pages_sessions_newest_first(tmp_path):
    from host_pc.jetson_db_snapshot import create_validated_snapshot, load_table_rows

    source = tmp_path / "jetson_spark.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, app_name TEXT, updated_at REAL)")
    conn.executemany(
        "INSERT INTO sessions (app_name, updated_at) VALUES (?, ?)",
        [("old", 1.0), ("new", 2.0), ("newest", 3.0)],
    )
    conn.commit()
    conn.close()

    snapshot = create_validated_snapshot(source)
    page = load_table_rows(snapshot.snapshot_path, "sessions", limit=2, offset=0)

    assert [row["app_name"] for row in page.rows] == ["newest", "new"]
    assert page.has_more is True


def test_delete_snapshot_removes_snapshot_file_and_parent_dir(tmp_path):
    from host_pc.jetson_db_snapshot import create_validated_snapshot, delete_snapshot

    source = tmp_path / "jetson_spark.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    snapshot = create_validated_snapshot(source)
    delete_snapshot(snapshot)

    assert not snapshot.snapshot_path.exists()
    assert not snapshot.snapshot_path.parent.exists()


def test_default_jetson_db_path_is_used_when_no_source_path_is_provided(tmp_path, monkeypatch):
    from host_pc import jetson_db_snapshot

    source = tmp_path / "jetson_spark.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(jetson_db_snapshot, "DEFAULT_JETSON_DB_PATH", source)

    snapshot = jetson_db_snapshot.create_validated_snapshot()

    assert snapshot.source_path == source
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_jetson_db_snapshot.py::test_list_user_tables_returns_sessions_button_events_and_unknown_tables tests/test_jetson_db_snapshot.py::test_load_table_rows_pages_sessions_newest_first tests/test_jetson_db_snapshot.py::test_default_jetson_db_path_is_used_when_no_source_path_is_provided -v`
Expected: FAIL because discovery/paging helpers do not exist yet.

- [ ] **Step 3: Extend the helper with schema discovery and a page model**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TablePage:
    columns: list[str]
    rows: list[dict]
    offset: int
    limit: int
    has_more: bool


def list_user_tables(snapshot_path: Path) -> list[str]:
    conn = open_snapshot_connection(snapshot_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    names = [row[0] for row in rows]
    preferred = [name for name in ("sessions", "button_events") if name in names]
    remaining = sorted(name for name in names if name not in preferred)
    return preferred + remaining
```

- [ ] **Step 4: Implement a single bounded row loader with deterministic ordering**

Use one helper like `load_table_rows(snapshot_path, table_name, *, limit=100, offset=0)` that:

- orders `sessions` by `updated_at DESC, id DESC`
- orders `button_events` by `timestamp DESC, id DESC`
- falls back to `rowid DESC` for unknown tables
- fetches `limit + 1` rows to compute `has_more`
- returns dictionaries keyed by column name so the Qt table layer stays generic

- [ ] **Step 5: Add one bounded retry helper for refresh-time snapshot loading**

Add a small helper like `create_snapshot_with_retry(source_path=None, *, attempts=3, delay_s=0.05)` that retries only transient snapshot creation failures, then re-raises the last `SnapshotError` after the final attempt. Keep retry policy centralized here so the dialog worker does not duplicate it.

Treat copy failures, snapshot open failures, and integrity-validation failures as transient retry candidates. Treat missing source path and other configuration failures as permanent failures that raise immediately without retry.

Write failing tests first for both cases:

- transient failure path: `create_validated_snapshot()` fails twice and succeeds on the third call
- retry exhaustion path: transient failure repeats three times and raises the final `SnapshotError`
- permanent failure path: missing source path raises once with no retry

- [ ] **Step 6: Add snapshot cleanup and failure-safe delete helpers**

Implement `delete_snapshot(snapshot)` so it removes the snapshot file and its temp directory if they still exist, swallowing only expected cleanup errors after logging them.

- [ ] **Step 7: Run the helper test file to verify it passes**

Run: `pytest tests/test_jetson_db_snapshot.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add host_pc/jetson_db_snapshot.py tests/test_jetson_db_snapshot.py
git commit -m "feat: add Jetson DB schema browsing helpers"
```

## Task 3: Add The Main-Panel Entry Point And Viewer Dialog Skeleton

**Files:**
- Modify: `spark_app_v2.py`
- Modify: `tests/test_spark_panel_ui.py`
- Create: `tests/test_jetson_db_viewer_ui.py`

- [ ] **Step 1: Write the failing UI tests for the new action and default dialog state**

```python
def test_action_grid_shows_view_jetson_db_button(self):
    panel = self._make_panel()

    visible_titles = sorted(
        btn._title_lbl.text()
        for btn in panel.findChildren(spark_app_v2.ActionButton)
        if not btn.isHidden()
    )

    assert "View Jetson DB" in visible_titles


def test_jetson_db_viewer_defaults_to_manual_refresh_state(self):
    from spark_app_v2 import JetsonDbViewerDialog

    dialog = JetsonDbViewerDialog()

    self.assertEqual(dialog.windowTitle(), "Jetson DB Viewer")
    self.assertTrue(dialog.refresh_btn.isEnabled())
    self.assertEqual(dialog.table_selector.count(), 0)
```

Implement `tests/test_jetson_db_viewer_ui.py` in the same `unittest` style as `tests/test_spark_panel_ui.py`: import-guard PyQt, create one shared `QApplication` in `setUpClass`, and avoid adding a new `pytest-qt` dependency.

- [ ] **Step 2: Run the focused UI tests to verify they fail**

Run: `pytest tests/test_spark_panel_ui.py::SparkPanelUiTests::test_action_grid_shows_view_jetson_db_button tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_jetson_db_viewer_defaults_to_manual_refresh_state -v`
Expected: FAIL because the button and dialog do not exist yet.

- [ ] **Step 3: Add the new action button in `spark_app_v2.py`**

Update the action grid near `self.btn_test_context`, `self.btn_custom_context`, and `self.btn_history` so the new button is visible by default and connected to a new `_on_view_jetson_db()` handler. Keep `Show History` hidden and unchanged.

```python
self.btn_view_jetson_db = ActionButton("View Jetson DB", "Inspect Jetson snapshot for debugging", self)
self.btn_view_jetson_db.clicked.connect(self._on_view_jetson_db)
grid.addWidget(self.btn_view_jetson_db, 1, 1)
```

- [ ] **Step 4: Add a minimal viewer dialog class**

Create `JetsonDbViewerDialog(QDialog)` near `CustomContextDialog` so it can reuse the file's existing Qt styling pattern. The first green version only needs:

- title `Jetson DB Viewer`
- a table selector
- a refresh button
- a read-only status label
- a `QTableWidget` or `QTableView` placeholder for row rendering
- internal state for `current_snapshot`, `current_table`, `current_offset`, and `refresh_in_flight`

- [ ] **Step 5: Run the focused UI tests to verify they pass**

Run: `pytest tests/test_spark_panel_ui.py::SparkPanelUiTests::test_action_grid_shows_view_jetson_db_button tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_jetson_db_viewer_defaults_to_manual_refresh_state -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add spark_app_v2.py tests/test_spark_panel_ui.py tests/test_jetson_db_viewer_ui.py
git commit -m "feat: add Jetson DB viewer entry point"
```

## Task 4: Implement Manual Refresh, Single-Flight Loading, And Table Rendering

**Files:**
- Modify: `spark_app_v2.py`
- Modify: `tests/test_jetson_db_viewer_ui.py`
- Reuse: `host_pc/jetson_db_snapshot.py`

- [ ] **Step 1: Write the failing UI/controller tests for refresh behavior**

```python
def test_refresh_disables_button_until_snapshot_load_completes(self):
    from spark_app_v2 import JetsonDbViewerDialog
    from unittest import mock

    dialog = JetsonDbViewerDialog()

    def fake_start_refresh():
        dialog._refresh_in_flight = True
        dialog._apply_refresh_started()

    with mock.patch.object(dialog, "_start_refresh", side_effect=fake_start_refresh):
        dialog._on_refresh_clicked()

    self.assertFalse(dialog.refresh_btn.isEnabled())


def test_second_refresh_click_is_ignored_while_request_is_in_flight(self):
    from spark_app_v2 import JetsonDbViewerDialog
    from unittest import mock

    dialog = JetsonDbViewerDialog()
    launches = []

    def fake_start_refresh():
        launches.append("start")
        dialog._refresh_in_flight = True
        dialog._apply_refresh_started()

    with mock.patch.object(dialog, "_start_refresh", side_effect=fake_start_refresh):
        dialog._on_refresh_clicked()
        dialog._on_refresh_clicked()

    self.assertEqual(launches, ["start"])


def test_successful_refresh_populates_discovered_tables_and_rows(self):
    from spark_app_v2 import JetsonDbViewerDialog
    from host_pc.jetson_db_snapshot import SnapshotHandle, TablePage
    from pathlib import Path

    dialog = JetsonDbViewerDialog()

    snapshot = SnapshotHandle(
        source_path=Path("Z:/demo/pico_bridge/jetson_spark.db"),
        snapshot_path=Path("C:/Temp/snapshot.db"),
        created_at=1.0,
    )
    page = TablePage(columns=["id", "app_name"], rows=[{"id": 1, "app_name": "Firefox"}], offset=0, limit=100, has_more=False)

    dialog._handle_refresh_result(snapshot=snapshot, tables=["sessions", "button_events"], selected_table="sessions", page=page)

    self.assertEqual(dialog.table_selector.count(), 2)
    self.assertEqual(dialog.table_selector.currentText(), "sessions")
    self.assertEqual(dialog.rows_table.rowCount(), 1)


def test_failed_refresh_keeps_last_good_snapshot_visible(self):
    from spark_app_v2 import JetsonDbViewerDialog
    from host_pc.jetson_db_snapshot import SnapshotHandle, TablePage
    from pathlib import Path

    dialog = JetsonDbViewerDialog()
    snapshot = SnapshotHandle(source_path=Path("Z:/demo/pico_bridge/jetson_spark.db"), snapshot_path=Path("C:/Temp/snapshot.db"), created_at=1.0)
    page = TablePage(columns=["id"], rows=[{"id": 1}], offset=0, limit=100, has_more=False)
    dialog._handle_refresh_result(snapshot=snapshot, tables=["sessions"], selected_table="sessions", page=page)

    dialog._handle_refresh_error("Snapshot validation failed")

    self.assertEqual(dialog.rows_table.rowCount(), 1)
    self.assertIn("Snapshot validation failed", dialog.status_lbl.text())


def test_refresh_path_never_opens_live_db_with_sqlite(self):
    import sqlite3
    import tempfile
    from pathlib import Path
    from unittest import mock
    from spark_app_v2 import JetsonDbViewerDialog
    from host_pc import jetson_db_snapshot

    dialog = JetsonDbViewerDialog()
    live_dir = Path(tempfile.mkdtemp())
    live_path = live_dir / "jetson_spark.db"
    source_conn = sqlite3.connect(live_path)
    source_conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, updated_at REAL)")
    source_conn.execute("INSERT INTO sessions (updated_at) VALUES (1.0)")
    source_conn.commit()
    source_conn.close()

    connect_calls = []
    real_connect = sqlite3.connect

    def recording_connect(path, *args, **kwargs):
        connect_calls.append((path, kwargs))
        return real_connect(path, *args, **kwargs)

    with (
        mock.patch.object(sqlite3, "connect", side_effect=recording_connect),
        mock.patch.object(jetson_db_snapshot, "DEFAULT_JETSON_DB_PATH", live_path),
        mock.patch("spark_app_v2.threading.Thread", lambda target, args=(), daemon=True: type("T", (), {"start": lambda self: target(*args)})()),
    ):
        dialog._on_refresh_clicked()

    self.assertGreater(len(connect_calls), 0)
    self.assertTrue(all("mode=ro" in str(path) for path, _ in connect_calls))
    self.assertTrue(all(str(live_path) not in str(path) for path, _ in connect_calls))


def test_retry_exhaustion_surfaces_distinct_error_and_leaves_refresh_enabled(self):
    from spark_app_v2 import JetsonDbViewerDialog

    dialog = JetsonDbViewerDialog()
    dialog._handle_refresh_error("Jetson DB not found: Z:/demo/pico_bridge/jetson_spark.db")

    self.assertTrue(dialog.refresh_btn.isEnabled())
    self.assertIn("Jetson DB not found", dialog.status_lbl.text())
```

- [ ] **Step 2: Run the focused viewer tests to verify they fail**

Run: `pytest tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_refresh_disables_button_until_snapshot_load_completes tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_second_refresh_click_is_ignored_while_request_is_in_flight tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_successful_refresh_populates_discovered_tables_and_rows -v`
Expected: FAIL because refresh-state handling and rendering do not exist yet.

- [ ] **Step 3: Implement one refresh controller with request tokens**

Use a single helper path in the dialog:

- `_on_refresh_clicked()` guards against re-entry
- `_start_refresh()` increments a request token and launches one background worker
- worker calls `create_snapshot_with_retry()`, `list_user_tables()`, and `load_table_rows()`
- UI-thread callback ignores results whose request token is not current

The first implementation can use `threading.Thread` plus a main-thread handoff through an existing Qt signal bridge rather than introducing a larger threading framework.

- [ ] **Step 4: Render rows generically from `TablePage`**

Populate the table widget from `page.columns` and `page.rows`, update the status label with source path, snapshot path, row count, and refreshed time, and re-enable the refresh button on both success and failure.

- [ ] **Step 5: Preserve the last good snapshot on refresh failure**

Only swap `self._active_snapshot` after a refresh succeeds. On failure, show the error text and keep the already-rendered rows and table list unchanged.

- [ ] **Step 6: Run the viewer UI test file to verify it passes**

Run: `pytest tests/test_jetson_db_viewer_ui.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add spark_app_v2.py tests/test_jetson_db_viewer_ui.py
git commit -m "feat: add manual Jetson DB viewer refresh flow"
```

## Task 5: Add Paging, Cleanup-On-Close, And Final Verification

**Files:**
- Modify: `spark_app_v2.py`
- Modify: `tests/test_jetson_db_viewer_ui.py`
- Possibly modify: `host_pc/jetson_db_snapshot.py`

- [ ] **Step 1: Write the failing tests for paging and snapshot cleanup**

```python
def test_load_more_appends_next_page_for_selected_table(self):
    from spark_app_v2 import JetsonDbViewerDialog
    from host_pc.jetson_db_snapshot import TablePage

    dialog = JetsonDbViewerDialog()
    first = TablePage(columns=["id"], rows=[{"id": 3}, {"id": 2}], offset=0, limit=2, has_more=True)
    second = TablePage(columns=["id"], rows=[{"id": 1}], offset=2, limit=2, has_more=False)

    dialog._apply_table_page("sessions", first, replace=True)
    dialog._apply_table_page("sessions", second, replace=False)

    self.assertEqual(dialog.rows_table.rowCount(), 3)


def test_close_event_deletes_active_snapshot_and_ignores_late_worker_result(self):
    from spark_app_v2 import JetsonDbViewerDialog
    from host_pc.jetson_db_snapshot import SnapshotHandle
    from pathlib import Path
    from unittest import mock

    dialog = JetsonDbViewerDialog()
    snapshot = SnapshotHandle(source_path=Path("Z:/demo/pico_bridge/jetson_spark.db"), snapshot_path=Path("C:/Temp/snapshot.db"), created_at=1.0)
    snapshot.snapshot_path.write_text("placeholder", encoding="utf-8")
    dialog._active_snapshot = snapshot
    dialog._refresh_request_id = 5

    deleted = []
    with mock.patch("spark_app_v2.delete_snapshot", lambda handle: deleted.append(handle.snapshot_path)):
        dialog.close()
        dialog._handle_refresh_result(request_id=4, snapshot=snapshot, tables=[], selected_table="", page=None)

    self.assertEqual(deleted, [snapshot.snapshot_path])


def test_successful_refresh_deletes_previous_snapshot_after_swap(self):
    from spark_app_v2 import JetsonDbViewerDialog
    from host_pc.jetson_db_snapshot import SnapshotHandle, TablePage
    from pathlib import Path
    from unittest import mock

    dialog = JetsonDbViewerDialog()
    old_snapshot = SnapshotHandle(source_path=Path("Z:/demo/pico_bridge/jetson_spark.db"), snapshot_path=Path("C:/Temp/old.db"), created_at=1.0)
    new_snapshot = SnapshotHandle(source_path=Path("Z:/demo/pico_bridge/jetson_spark.db"), snapshot_path=Path("C:/Temp/new.db"), created_at=2.0)
    dialog._active_snapshot = old_snapshot

    deleted = []
    with mock.patch("spark_app_v2.delete_snapshot", lambda handle: deleted.append(handle.snapshot_path)):
        page = TablePage(columns=["id"], rows=[{"id": 1}], offset=0, limit=100, has_more=False)
        dialog._handle_refresh_result(snapshot=new_snapshot, tables=["sessions"], selected_table="sessions", page=page)

    self.assertEqual(dialog._active_snapshot, new_snapshot)
    self.assertEqual(deleted, [old_snapshot.snapshot_path])
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_load_more_appends_next_page_for_selected_table tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_close_event_deletes_active_snapshot_and_ignores_late_worker_result tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_successful_refresh_deletes_previous_snapshot_after_swap -v`
Expected: FAIL because paging and cleanup-on-close are incomplete.

- [ ] **Step 3: Implement paging controls and close cleanup**

Add `Load More` to request the next page for the selected table without replacing the already rendered rows. In `closeEvent()`, mark the dialog closed, invalidate outstanding request IDs, and call `delete_snapshot()` on the active snapshot.

- [ ] **Step 4: Run the Jetson viewer test suite and the existing panel UI tests**

Run: `pytest tests/test_jetson_db_snapshot.py tests/test_jetson_db_viewer_ui.py tests/test_spark_panel_ui.py -v`
Expected: PASS

- [ ] **Step 5: Run a manual smoke check against the mounted Jetson path**

Run:

```powershell
.\.venv\Scripts\python.exe .\spark_app_v2.py
```

Manual checks:

- `View Jetson DB` button is visible in the action grid
- opening the viewer does not block polling or other controls
- `Refresh` loads `sessions` from a local snapshot and shows the snapshot path
- unplugging or hiding `Z:\demo\pico_bridge\jetson_spark.db` produces a contained error in the viewer only
- repeated refreshes do not leave old snapshot files behind in the temp directory

- [ ] **Step 6: Commit**

```bash
git add spark_app_v2.py host_pc/jetson_db_snapshot.py tests/test_jetson_db_snapshot.py tests/test_jetson_db_viewer_ui.py tests/test_spark_panel_ui.py
git commit -m "feat: add snapshot-based Jetson DB viewer"
```
