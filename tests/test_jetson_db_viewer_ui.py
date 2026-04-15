import unittest
import contextlib
from pathlib import Path
from unittest import mock
from urllib.parse import unquote
import tempfile
import uuid
import sqlite3

from host_pc.jetson_db_snapshot import SnapshotHandle, TablePage
import host_pc.jetson_db_snapshot as snapshot_mod

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - environment-dependent test guard
    QApplication = None
    spark_app_v2 = None
else:
    import spark_app_v2


def _run_worker_thread_immediately(*args, **kwargs):
    if args:
        target = args[0]
        thread_args = args[1] if len(args) > 1 else tuple()
    else:
        target = kwargs["target"]
        thread_args = kwargs.get("args", tuple())

    worker = mock.Mock()
    worker.start.side_effect = lambda: target(*thread_args)
    return worker


@unittest.skipUnless(QApplication is not None, "PyQt6 is not installed")
class JetsonDbViewerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_viewer_dialog_has_expected_defaults(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()

        self.assertEqual(dialog.windowTitle(), "Jetson DB Viewer")
        self.assertTrue(dialog.refresh_btn.isEnabled())
        self.assertEqual(dialog.status_label.text(), "Ready")
        self.assertEqual(dialog.status_label.property("read_only"), True)
        self.assertEqual(dialog.table_selector.count(), 0)
        self.assertEqual(dialog.rows_table.rowCount(), 0)
        self.assertEqual(dialog.rows_table.columnCount(), 0)

        self.assertIsNone(dialog.current_snapshot)
        self.assertEqual(dialog.current_table, "")
        self.assertEqual(dialog.row_offset, 0)
        self.assertFalse(dialog.refresh_in_flight)
        self.assertEqual(dialog._refresh_request_token, 0)

    def test_refresh_click_disables_button_until_load_starts(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()

        with mock.patch.object(spark_app_v2, "threading") as threading_mock:
            thread_mock = mock.Mock()
            thread_instance = mock.Mock()
            thread_instance.start = mock.Mock()
            thread_mock.Thread.return_value = thread_instance
            threading_mock.Thread = thread_mock.Thread

            dialog._on_refresh_clicked()

        self.assertFalse(dialog.refresh_btn.isEnabled())
        self.assertTrue(dialog.refresh_in_flight)
        self.assertEqual(dialog.status_label.text(), "Refreshing Jetson DB snapshot…")
        self.assertEqual(dialog._refresh_request_token, 1)
        threading_mock.Thread.assert_called_once()
        thread_instance.start.assert_called_once()

    def test_second_refresh_click_is_ignored_while_in_flight(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()

        with mock.patch.object(spark_app_v2, "threading") as threading_mock:
            thread_mock = mock.Mock()
            thread_instance = mock.Mock()
            thread_instance.start = mock.Mock()
            thread_mock.Thread.return_value = thread_instance
            threading_mock.Thread = thread_mock.Thread

            dialog._on_refresh_clicked()
            dialog._on_refresh_clicked()

        self.assertTrue(dialog.refresh_in_flight)
        self.assertEqual(dialog._refresh_request_token, 1)
        self.assertEqual(dialog.refresh_btn.isEnabled(), False)
        self.assertEqual(threading_mock.Thread.call_count, 1)
        thread_instance.start.assert_called_once()

    def test_successful_refresh_populates_discovered_tables_and_rows(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        snapshot = SnapshotHandle(path=Path("/tmp/snapshot.db"))

        with (
            mock.patch.object(spark_app_v2, "create_snapshot_with_retry", return_value=snapshot),
            mock.patch.object(spark_app_v2, "list_user_tables", return_value=["sessions", "button_events"]),
            mock.patch.object(
                spark_app_v2,
                "load_table_rows",
                return_value=TablePage(
                    table_name="sessions",
                    rows=[
                        {"id": 1, "text": "session one"},
                        {"id": 2, "text": "session two"},
                    ],
                    has_more=False,
                ),
            ),
            mock.patch("spark_app_v2.threading.Thread", side_effect=_run_worker_thread_immediately),
        ):
            dialog._on_refresh()

        self.assertFalse(dialog.refresh_in_flight)
        self.assertTrue(dialog.refresh_btn.isEnabled())
        self.assertEqual(dialog.table_selector.count(), 2)
        self.assertEqual(dialog.table_selector.currentText(), "sessions")
        self.assertEqual(dialog.current_table, "sessions")
        self.assertIsNotNone(dialog.current_snapshot)
        self.assertEqual(dialog.rows_table.rowCount(), 2)
        self.assertEqual(dialog.rows_table.columnCount(), 2)
        self.assertEqual(dialog.rows_table.horizontalHeaderItem(0).text(), "id")
        self.assertEqual(dialog.rows_table.item(0, 1).text(), "session one")
        self.assertEqual(dialog.rows_table.item(1, 0).text(), "2")
        self.assertEqual(dialog.status_label.text(), "Loaded 2 rows from sessions")

    def test_failed_refresh_keeps_last_good_snapshot_visible(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        old_snapshot = SnapshotHandle(path=Path("/tmp/old.db"))
        dialog.current_snapshot = old_snapshot
        dialog.current_table = "sessions"
        dialog._populate_table_selector(["sessions"])
        dialog._render_table_page(
            TablePage(
                table_name="sessions",
                rows=[{"id": 1, "text": "previous"}],
                has_more=False,
            )
        )
        old_rows = dialog.rows_table.rowCount()
        old_cols = dialog.rows_table.columnCount()

        with (
            mock.patch.object(
                spark_app_v2,
                "create_snapshot_with_retry",
                side_effect=RuntimeError("temporary DB read failure"),
            ),
            mock.patch("spark_app_v2.threading.Thread", side_effect=_run_worker_thread_immediately),
        ):
            dialog._on_refresh_clicked()

        self.assertFalse(dialog.refresh_in_flight)
        self.assertTrue(dialog.refresh_btn.isEnabled())
        self.assertIs(dialog.current_snapshot, old_snapshot)
        self.assertEqual(dialog.current_table, "sessions")
        self.assertEqual(dialog.rows_table.rowCount(), old_rows)
        self.assertEqual(dialog.rows_table.columnCount(), old_cols)
        self.assertEqual(dialog.status_label.text(), "Refresh failed: temporary DB read failure")

    def test_selected_table_load_failure_preserves_current_snapshot_and_rows(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        current_snapshot = SnapshotHandle(path=Path("/tmp/snapshot.db"))
        dialog.current_snapshot = current_snapshot
        dialog.current_table = "sessions"
        dialog._populate_table_selector(["sessions", "missing_table"])
        dialog._render_table_page(
            TablePage(
                table_name="sessions",
                rows=[{"id": 1, "text": "session one"}],
                has_more=False,
            )
        )

        previous_table = dialog.current_table
        previous_rows = dialog.rows_table.rowCount()
        previous_cols = dialog.rows_table.columnCount()
        previous_status = dialog.status_label.text()

        with mock.patch.object(spark_app_v2, "load_table_rows", side_effect=RuntimeError("table read failed")):
            dialog._on_table_selected("missing_table")

        self.assertIs(dialog.current_snapshot, current_snapshot)
        self.assertEqual(dialog.current_table, previous_table)
        self.assertEqual(dialog.rows_table.rowCount(), previous_rows)
        self.assertEqual(dialog.rows_table.columnCount(), previous_cols)
        self.assertEqual(dialog.status_label.text(), "Failed to load table 'missing_table': table read failed")
        self.assertNotEqual(dialog.status_label.text(), previous_status)

    def test_refresh_path_never_opens_live_db_with_sqlite(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()

        token = uuid.uuid4().hex
        temp_dir = Path(tempfile.gettempdir())
        live_source = temp_dir / f"jetson_db_live_source_{token}_source.db"
        snapshot_path = temp_dir / f"jetson_db_snapshot_copy_{token}_snapshot.db"

        with sqlite3.connect(live_source) as connection:
            connection.executescript(
                "CREATE TABLE sessions(id INTEGER PRIMARY KEY, value TEXT);"
                "INSERT INTO sessions(value) VALUES ('live-source');"
            )
        with sqlite3.connect(snapshot_path) as connection:
            connection.executescript(
                "CREATE TABLE sessions(id INTEGER PRIMARY KEY, value TEXT);"
                "INSERT INTO sessions(value) VALUES ('snapshot-row');"
            )

        connect_calls = []
        original_connect = snapshot_mod.sqlite3.connect
        open_connections = []

        def recorded_connect(*args, **kwargs):
            connect_calls.append(args)
            connection = original_connect(*args, **kwargs)
            open_connections.append(connection)
            return connection

        try:
            with (
                mock.patch.object(spark_app_v2, "create_snapshot_with_retry", return_value=SnapshotHandle(path=snapshot_path)),
                mock.patch("spark_app_v2.threading.Thread", side_effect=_run_worker_thread_immediately),
                mock.patch("host_pc.jetson_db_snapshot.sqlite3.connect", side_effect=recorded_connect),
            ):
                dialog._on_refresh()

            self.assertTrue(connect_calls)
            decoded_calls = [unquote(item[0]).lower() for item in connect_calls if item]
            self.assertTrue(any(str(snapshot_path.as_posix()).lower() in item for item in decoded_calls))
            self.assertFalse(any(str(live_source.as_posix()).lower() in item for item in decoded_calls))
            self.assertFalse(any("z:/demo/pico_bridge/jetson_spark.db" in item for item in decoded_calls))
        finally:
            for connection in open_connections:
                with contextlib.suppress(Exception):
                    connection.close()

            for path in (snapshot_path, live_source):
                with contextlib.suppress(Exception):
                    path.unlink()

    def test_refresh_failure_leaves_button_enabled_and_shows_error(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        old_snapshot = SnapshotHandle(path=Path("/tmp/old_snapshot.db"))
        dialog.current_snapshot = old_snapshot
        dialog.current_table = "sessions"
        dialog.current_table_has_more = True
        dialog.row_offset = 50
        dialog.load_more_btn.setEnabled(True)
        dialog._populate_table_selector(["sessions"])
        dialog._render_table_page(
            TablePage(
                table_name="sessions",
                rows=[{"id": 1, "text": "existing"}],
                has_more=True,
            )
        )

        with (
            mock.patch.object(
                spark_app_v2,
                "create_snapshot_with_retry",
                side_effect=RuntimeError("retry exhausted"),
            ),
            mock.patch("spark_app_v2.threading.Thread", side_effect=_run_worker_thread_immediately),
        ):
            dialog._on_refresh_clicked()

        self.assertTrue(dialog.refresh_btn.isEnabled())
        self.assertEqual(dialog.status_label.text(), "Refresh failed: retry exhausted")
        self.assertTrue(dialog.load_more_btn.isEnabled())
        self.assertIs(dialog.current_snapshot, old_snapshot)
        self.assertEqual(dialog.current_table, "sessions")
        self.assertEqual(dialog.current_table_has_more, True)
        self.assertEqual(dialog.row_offset, 50)
        self.assertEqual(dialog.rows_table.item(0, 0).text(), "1")

    def test_load_more_appends_next_page_for_selected_table(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        snapshot = SnapshotHandle(path=Path("/tmp/snapshot.db"))
        first_page = TablePage(
            table_name="sessions",
            rows=[
                {"id": 1, "text": "session one"},
                {"id": 2, "text": "session two"},
            ],
            has_more=True,
        )
        second_page = TablePage(
            table_name="sessions",
            rows=[
                {"id": 3, "text": "session three"},
            ],
            has_more=False,
        )

        with (
            mock.patch.object(spark_app_v2, "create_snapshot_with_retry", return_value=snapshot),
            mock.patch.object(spark_app_v2, "list_user_tables", return_value=["sessions", "button_events"]),
            mock.patch.object(spark_app_v2, "load_table_rows", side_effect=[first_page]),
            mock.patch("spark_app_v2.threading.Thread", side_effect=_run_worker_thread_immediately),
        ):
            dialog._on_refresh()

        self.assertTrue(dialog.load_more_btn.isEnabled())
        self.assertEqual(dialog.rows_table.rowCount(), 2)
        self.assertEqual(dialog.rows_table.item(1, 0).text(), "2")

        with mock.patch.object(spark_app_v2, "load_table_rows", side_effect=[second_page]) as load_rows_mock:
            dialog._on_load_more()

        self.assertEqual(dialog.rows_table.rowCount(), 3)
        self.assertEqual(dialog.rows_table.item(2, 0).text(), "3")
        self.assertEqual(dialog.rows_table.item(2, 1).text(), "session three")
        self.assertFalse(dialog.load_more_btn.isEnabled())
        self.assertEqual(dialog.status_label.text(), "Loaded 1 more rows from sessions")
        load_rows_mock.assert_called_once_with(snapshot.path, "sessions", limit=100, offset=2)

    def test_selected_table_load_uses_dialog_page_size(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        dialog.current_snapshot = SnapshotHandle(path=Path("/tmp/snapshot.db"))
        dialog.current_table = "sessions"
        dialog._populate_table_selector(["sessions"])

        page = TablePage(
            table_name="sessions",
            rows=[{"id": 1, "text": "session one"}],
            has_more=False,
        )

        with mock.patch.object(spark_app_v2, "load_table_rows", return_value=page) as load_rows:
            dialog._on_table_selected("sessions")

        load_rows.assert_called_once_with(
            Path("/tmp/snapshot.db"),
            "sessions",
            limit=dialog._page_size,
            offset=0,
        )

    def test_close_event_deletes_active_snapshot_and_ignores_late_worker_result(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        active_snapshot = SnapshotHandle(path=Path("/tmp/active_snapshot.db"))
        stale_snapshot = SnapshotHandle(path=Path("/tmp/stale_snapshot.db"))
        dialog.current_snapshot = active_snapshot
        dialog.current_table = "sessions"
        dialog._render_table_page(
            TablePage(
                table_name="sessions",
                rows=[{"id": 1, "text": "active row"}],
                has_more=False,
            )
        )

        with mock.patch("spark_app_v2.delete_snapshot") as delete_snapshot:
            dialog.closeEvent(mock.Mock())
            stale_token = 0
            stale_page = TablePage(table_name="sessions", rows=[{"id": 10, "text": "stale"}], has_more=False)
            dialog._on_refresh_succeeded(stale_token, stale_snapshot, ["sessions"], stale_page)

            self.assertEqual(delete_snapshot.call_count, 2)
            delete_snapshot.assert_has_calls([mock.call(active_snapshot), mock.call(stale_snapshot)])
            self.assertIsNone(dialog.current_snapshot)
            self.assertEqual(dialog.current_table, "sessions")
            self.assertEqual(dialog.rows_table.rowCount(), 1)
            self.assertEqual(dialog.rows_table.item(0, 1).text(), "active row")
            self.assertFalse(dialog.refresh_in_flight)

    def test_stale_refresh_failure_after_close_is_inert(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        prior_snapshot = SnapshotHandle(path=Path("/tmp/close_refresh_fail_snapshot.db"))
        dialog.current_snapshot = prior_snapshot
        dialog.current_table = "sessions"
        dialog.current_table_has_more = True
        dialog.refresh_in_flight = True
        dialog.row_offset = 5
        dialog._render_table_page(
            TablePage(
                table_name="sessions",
                rows=[{"id": 1, "text": "live row"}],
                has_more=True,
            )
        )
        dialog.status_label.setText("Refreshing Jetson DB snapshot…")

        stale_token = dialog._refresh_request_token
        with mock.patch("spark_app_v2.delete_snapshot") as delete_snapshot:
            dialog.closeEvent(mock.Mock())
            dialog._on_refresh_failed(stale_token, "late failure")

            self.assertEqual(dialog.current_snapshot, None)
            self.assertFalse(dialog.refresh_in_flight)
            self.assertEqual(dialog.rows_table.rowCount(), 1)
            self.assertEqual(dialog.rows_table.item(0, 0).text(), "1")
            self.assertEqual(dialog.status_label.text(), "Refreshing Jetson DB snapshot…")
            self.assertFalse(dialog.load_more_btn.isEnabled())
            delete_snapshot.assert_called_once_with(prior_snapshot)
            self.assertEqual(dialog._refresh_request_token, stale_token + 1)

    def test_successful_refresh_deletes_previous_snapshot_after_swap(self):
        dialog = spark_app_v2.JetsonDbViewerDialog()
        prior_snapshot = SnapshotHandle(path=Path("/tmp/old_snapshot.db"))
        dialog.current_snapshot = prior_snapshot

        with (
            mock.patch.object(spark_app_v2, "create_snapshot_with_retry", return_value=SnapshotHandle(path=Path("/tmp/new_snapshot.db"))),
            mock.patch.object(spark_app_v2, "list_user_tables", return_value=["sessions", "button_events"]),
            mock.patch.object(
                spark_app_v2,
                "load_table_rows",
                return_value=TablePage(
                    table_name="sessions",
                    rows=[{"id": 1, "text": "new row"}],
                    has_more=False,
                ),
            ),
            mock.patch("spark_app_v2.threading.Thread", side_effect=_run_worker_thread_immediately),
            mock.patch("spark_app_v2.delete_snapshot") as delete_snapshot,
        ):
            dialog._on_refresh()

        delete_snapshot.assert_called_once_with(prior_snapshot)
        self.assertIsNotNone(dialog.current_snapshot)
        self.assertEqual(dialog.current_snapshot.path, Path("/tmp/new_snapshot.db"))
        self.assertEqual(dialog.rows_table.item(0, 1).text(), "new row")


if __name__ == "__main__":
    unittest.main()
