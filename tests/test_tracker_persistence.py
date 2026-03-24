import tempfile
import unittest
from pathlib import Path

from host_pc.accessibility.base import TextSource, WindowInfo
from host_pc.accessibility.tracker import WindowContextTracker
from host_pc.db import SparkDB


def make_window_info(
    title: str = "Inbox",
    app_name: str = "slack",
    process_name: str = "slack.exe",
    pid: int = 101,
) -> WindowInfo:
    return WindowInfo(
        title=title,
        app_name=app_name,
        process_name=process_name,
        pid=pid,
    )


class WindowContextTrackerPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "spark.db"
        self.db = SparkDB(str(self.db_path))
        self.tracker = WindowContextTracker(db=self.db)

    def tearDown(self) -> None:
        self.db.close()
        self._tmpdir.cleanup()

    def test_first_update_persists_current_window_immediately(self):
        self.tracker.update(
            make_window_info(),
            "hello from slack",
            TextSource.FULL_WINDOW,
        )

        row = self.db._conn.execute(
            "SELECT app_name, window_title, text, source FROM window_snapshots"
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["app_name"], "slack")
        self.assertEqual(row["window_title"], "Inbox")
        self.assertEqual(row["text"], "hello from slack")
        self.assertEqual(row["source"], TextSource.FULL_WINDOW.value)

    def test_same_context_updates_existing_row_in_place(self):
        self.tracker.update(
            make_window_info(),
            "first text",
            TextSource.FULL_WINDOW,
        )
        first_id = self.db._conn.execute(
            "SELECT id FROM window_snapshots"
        ).fetchone()["id"]

        self.tracker.update(
            make_window_info(),
            "updated text",
            TextSource.FOCUSED_ELEMENT,
        )

        rows = self.db._conn.execute(
            "SELECT id, text, source FROM window_snapshots"
        ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], first_id)
        self.assertEqual(rows[0]["text"], "updated text")
        self.assertEqual(rows[0]["source"], TextSource.FOCUSED_ELEMENT.value)

    def test_context_switch_inserts_new_current_row_without_waiting_for_next_switch(self):
        self.tracker.update(
            make_window_info(title="Inbox", app_name="slack"),
            "slack message body",
            TextSource.FULL_WINDOW,
        )

        self.tracker.update(
            make_window_info(
                title="Project Plan",
                app_name="Codex",
                process_name="codex.exe",
                pid=202,
            ),
            "implementation checklist and notes",
            TextSource.FULL_WINDOW,
        )

        rows = self.db._conn.execute(
            "SELECT app_name, window_title, text FROM window_snapshots ORDER BY id"
        ).fetchall()

        self.assertEqual(
            [(row["app_name"], row["window_title"], row["text"]) for row in rows],
            [
                ("slack", "Inbox", "slack message body"),
                ("Codex", "Project Plan", "implementation checklist and notes"),
            ],
        )

    def test_revisiting_unchanged_context_reuses_existing_row(self):
        self.tracker.update(
            make_window_info(title="Inbox", app_name="slack"),
            "slack message body",
            TextSource.FULL_WINDOW,
        )
        original = self.db._conn.execute(
            "SELECT id, first_seen, last_seen FROM window_snapshots WHERE app_name = 'slack'"
        ).fetchone()

        self.tracker.update(
            make_window_info(
                title="Project Plan",
                app_name="Codex",
                process_name="codex.exe",
                pid=202,
            ),
            "implementation checklist and notes",
            TextSource.FULL_WINDOW,
        )
        self.tracker.update(
            make_window_info(title="Inbox", app_name="slack"),
            "slack message body",
            TextSource.FULL_WINDOW,
        )

        rows = self.db._conn.execute(
            "SELECT id, first_seen, last_seen FROM window_snapshots WHERE app_name = 'slack'"
        ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], original["id"])
        self.assertEqual(rows[0]["first_seen"], original["first_seen"])
        self.assertGreaterEqual(rows[0]["last_seen"], original["last_seen"])

    def test_irrelevant_window_is_not_persisted(self):
        self.tracker.update(
            make_window_info(
                title="Search",
                app_name="SearchHost",
                process_name="SearchHost.exe",
                pid=303,
            ),
            "Search",
            TextSource.FULL_WINDOW,
        )

        count = self.db._conn.execute(
            "SELECT COUNT(*) FROM window_snapshots"
        ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_codex_style_window_is_persisted_for_debug_visibility(self):
        self.tracker.update(
            make_window_info(
                title="Codex",
                app_name="Codex",
                process_name="Codex.exe",
                pid=404,
            ),
            "Codex Codex Minimize Maximize Close Codex",
            TextSource.FULL_WINDOW,
        )

        row = self.db._conn.execute(
            "SELECT id, app_name, window_title FROM window_snapshots"
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["app_name"], "Codex")
        self.assertEqual(row["window_title"], "Codex")


if __name__ == "__main__":
    unittest.main()
