import tempfile
import unittest
from pathlib import Path

from jetson.db_manager import JetsonDB, build_content_fingerprint, build_context_key


def make_payload(
    *,
    app_name="Codex",
    window_title="Plan",
    process_name="Codex.exe",
    pid=42,
    source="full_window",
    tab_title=None,
    url=None,
    text="hello world",
    timestamp=123.45,
):
    return {
        "app_name": app_name,
        "window_title": window_title,
        "process_name": process_name,
        "pid": pid,
        "source": source,
        "tab_title": tab_title,
        "url": url,
        "text": text,
        "timestamp": timestamp,
    }


class JetsonDBTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "jetson_spark.db"
        self.db = JetsonDB(str(self.db_path))

    def tearDown(self):
        self.db.close()
        self._tmpdir.cleanup()

    def test_context_new_creates_rich_session_row(self):
        payload = make_payload(url="https://example.com")

        row_id = self.db.on_context_new(payload)
        row = self.db.get_recent_sessions(limit=1)[0]

        self.assertEqual(row["id"], row_id)
        self.assertEqual(row["context_key"], build_context_key(payload))
        self.assertEqual(row["content_fingerprint"], build_content_fingerprint(payload))
        self.assertEqual(row["app_name"], "Codex")
        self.assertEqual(row["url"], "https://example.com")
        self.assertEqual(row["text"], "hello world")

    def test_context_update_updates_active_row_in_place(self):
        payload = make_payload()
        self.db.on_context_new(payload)

        updated = make_payload(text="updated text", source="focused_element")
        self.db.on_context_update(updated)
        row = self.db.get_recent_sessions(limit=1)[0]

        self.assertEqual(row["text"], "updated text")
        self.assertEqual(row["source"], "focused_element")
        self.assertEqual(row["content_fingerprint"], build_content_fingerprint(updated))

    def test_button_press_links_to_active_session(self):
        self.db.on_context_new(make_payload())
        self.db.on_button_press(2)

        row = self.db._conn.execute("SELECT button_id, session_id FROM button_events").fetchone()

        self.assertEqual(row["button_id"], 2)
        self.assertIsNotNone(row["session_id"])


if __name__ == "__main__":
    unittest.main()
