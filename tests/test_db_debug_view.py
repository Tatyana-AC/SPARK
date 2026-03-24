import tempfile
import time
import unittest
from pathlib import Path

from host_pc.accessibility.base import TextSource, WindowContextSnapshot, WindowInfo
from host_pc.db import SparkDB


def make_snapshot(
    *,
    app_name: str,
    title: str,
    text: str,
    process_name: str | None = None,
    pid: int = 100,
    timestamp: float | None = None,
) -> WindowContextSnapshot:
    return WindowContextSnapshot(
        window_info=WindowInfo(
            title=title,
            app_name=app_name,
            process_name=process_name or f"{app_name}.exe",
            pid=pid,
        ),
        text=text,
        source=TextSource.FULL_WINDOW,
        timestamp=timestamp if timestamp is not None else time.time(),
    )


class SparkDBDebugRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "spark.db"
        self.db = SparkDB(str(self.db_path))

    def tearDown(self) -> None:
        self.db.close()
        self._tmpdir.cleanup()

    def test_get_debug_rows_returns_latest_rows_with_preview_fields(self):
        older = make_snapshot(
            app_name="slack",
            title="Inbox",
            text="older body text",
            timestamp=1000.0,
        )
        newer = make_snapshot(
            app_name="Codex",
            title="Plan",
            text=(
                "newer body text that should show in preview without being truncated "
                "even when the debug viewer needs more than one line to display it"
            ),
            timestamp=2000.0,
        )

        older_id = self.db.save_snapshot(older)
        newer_id = self.db.save_snapshot(newer)

        rows = self.db.get_debug_rows(limit=2)

        self.assertEqual([row["id"] for row in rows], [newer_id, older_id])
        self.assertEqual(rows[0]["app_name"], "Codex")
        self.assertEqual(rows[0]["window_title"], "Plan")
        self.assertEqual(rows[0]["first_seen"], 2000.0)
        self.assertEqual(rows[0]["last_seen"], 2000.0)
        self.assertEqual(
            rows[0]["text_preview"],
            (
                "newer body text that should show in preview without being truncated "
                "even when the debug viewer needs more than one line to display it"
            ),
        )
        self.assertTrue(rows[0]["content_fingerprint"])


if __name__ == "__main__":
    unittest.main()
