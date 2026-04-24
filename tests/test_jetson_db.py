import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        if self.db is not None:
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

    def test_context_new_reuses_latest_same_context_and_pid_instead_of_inserting_duplicate(self):
        payload = make_payload(
            app_name="Chrome",
            process_name="chrome.exe",
            pid=28536,
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="initial article text",
        )
        self.db.on_context_new(payload)

        refreshed = make_payload(
            app_name="Chrome",
            process_name="chrome.exe",
            pid=28536,
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="refreshed article text",
            timestamp=456.78,
        )
        row_id = self.db.on_context_new(refreshed)
        rows = self.db.get_recent_sessions(limit=10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(row_id, rows[0]["id"])
        self.assertEqual(rows[0]["text"], "refreshed article text")
        self.assertEqual(rows[0]["host_observed_at"], 456.78)

    def test_context_update_without_active_session_reattaches_to_latest_same_context_and_pid(self):
        payload = make_payload(
            app_name="Chrome",
            process_name="chrome.exe",
            pid=26572,
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="initial article text",
        )
        row_id = self.db.on_context_new(payload)
        self.db._active_session_id = None
        self.db._active_context_key = None

        updated = make_payload(
            app_name="Chrome",
            process_name="chrome.exe",
            pid=26572,
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="updated article text",
            source="web_content",
            timestamp=789.01,
        )
        self.db.on_context_update(updated)
        rows = self.db.get_recent_sessions(limit=10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], row_id)
        self.assertEqual(rows[0]["text"], "updated article text")
        self.assertEqual(rows[0]["host_observed_at"], 789.01)

    def test_context_update_collapses_existing_duplicate_rows_for_same_live_session(self):
        payload = make_payload(
            app_name="Chrome",
            process_name="chrome.exe",
            pid=26572,
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="initial article text",
        )
        keep_id = self.db.on_context_new(payload)
        duplicate_payload = make_payload(
            app_name="Chrome",
            process_name="chrome.exe",
            pid=26572,
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="stale duplicate text",
            timestamp=100.0,
        )
        duplicate_id = self.db._conn.execute(
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
                build_context_key(duplicate_payload),
                build_content_fingerprint(duplicate_payload),
                duplicate_payload["app_name"],
                duplicate_payload["window_title"],
                duplicate_payload["process_name"],
                duplicate_payload["pid"],
                duplicate_payload["source"],
                duplicate_payload["tab_title"],
                duplicate_payload["url"],
                duplicate_payload["text"],
                duplicate_payload["timestamp"],
                50.0,
                50.0,
            ),
        ).lastrowid
        self.db._conn.execute(
            "INSERT INTO button_events (button_id, session_id, timestamp) VALUES (?, ?, ?)",
            (3, duplicate_id, 75.0),
        )
        self.db._conn.commit()

        updated = make_payload(
            app_name="Chrome",
            process_name="chrome.exe",
            pid=26572,
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="updated article text",
            timestamp=200.0,
        )
        self.db.on_context_update(updated)

        rows = self.db.get_recent_sessions(limit=10)
        button_row = self.db._conn.execute(
            "SELECT session_id FROM button_events WHERE button_id = 3"
        ).fetchone()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], keep_id)
        self.assertEqual(button_row["session_id"], keep_id)

    def test_button_press_links_to_active_session(self):
        self.db.on_context_new(make_payload())
        self.db.on_button_press(2)

        row = self.db._conn.execute("SELECT button_id, session_id FROM button_events").fetchone()

        self.assertEqual(row["button_id"], 2)
        self.assertIsNotNone(row["session_id"])

    def test_reopen_restores_most_recent_session_as_active(self):
        payload = make_payload(app_name="Code", window_title="Current Window")
        self.db.on_context_new(payload)
        self.db.close()
        self.db = None

        reopened = JetsonDB(str(self.db_path))
        try:
            row = reopened.get_active_session()
            self.assertIsNotNone(row)
            self.assertEqual(row["app_name"], "Code")
            self.assertEqual(row["window_title"], "Current Window")
        finally:
            reopened.close()

    def test_reopen_prefers_latest_host_observed_at_when_updated_at_is_skewed(self):
        older_host_payload = make_payload(
            app_name="OldClock",
            window_title="Older host context",
            timestamp=1000.0,
        )
        newer_host_payload = make_payload(
            app_name="NewHost",
            window_title="Latest host context",
            timestamp=2000.0,
        )

        with mock.patch("jetson.db_manager.time.time", side_effect=[5000.0, 4000.0]):
            self.db.on_context_new(older_host_payload)
            self.db.on_context_new(newer_host_payload)

        self.db.close()
        self.db = None

        reopened = JetsonDB(str(self.db_path))
        try:
            row = reopened.get_active_session()
            self.assertIsNotNone(row)
            self.assertEqual(row["app_name"], "NewHost")
            self.assertEqual(row["host_observed_at"], 2000.0)
        finally:
            reopened.close()

    def test_recent_sessions_since_uses_host_observed_cutoff(self):
        self.db.on_context_new(make_payload(window_title="old", timestamp=100.0, text="old"))
        self.db.on_context_new(make_payload(window_title="new", pid=43, timestamp=500.0, text="new"))

        rows = self.db.get_recent_sessions_since(200.0)

        self.assertEqual([row["window_title"] for row in rows], ["new"])

    def test_recent_sessions_since_orders_by_host_observed_at(self):
        with mock.patch("jetson.db_manager.time.time", side_effect=[900.0, 800.0]):
            self.db.on_context_new(make_payload(window_title="older host", timestamp=100.0))
            self.db.on_context_new(make_payload(window_title="newer host", pid=43, timestamp=500.0))

        rows = self.db.get_recent_sessions_since(0.0, dedupe=False)

        self.assertEqual([row["window_title"] for row in rows], ["newer host", "older host"])

    def test_recent_sessions_since_dedupes_context_key_to_newest(self):
        def insert_session(payload):
            self.db._conn.execute(
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
                    build_context_key(payload),
                    build_content_fingerprint(payload),
                    payload["app_name"],
                    payload["window_title"],
                    payload["process_name"],
                    payload["pid"],
                    payload["source"],
                    payload["tab_title"],
                    payload["url"],
                    payload["text"],
                    payload["timestamp"],
                    payload["timestamp"],
                    payload["timestamp"],
                ),
            )

        for index, timestamp in enumerate((700.0, 600.0, 500.0, 400.0, 300.0, 200.0, 100.0)):
            insert_session(make_payload(
                app_name="Chrome",
                process_name="chrome.exe",
                pid=100 + index,
                window_title="Boston Tea Party",
                url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
                text="newest duplicate text" if index == 0 else f"older duplicate text {index}",
                timestamp=timestamp,
            ))
        insert_session(make_payload(
            app_name="Notes",
            process_name="notes.exe",
            pid=2,
            window_title="Essay",
            text="Tea Act notes",
            timestamp=50.0,
        ))
        self.db._conn.commit()

        rows = self.db.get_recent_sessions_since(0.0, limit=2, dedupe=True)

        self.assertEqual([row["text"] for row in rows], ["newest duplicate text", "Tea Act notes"])

    def test_keyword_search_matches_multiword_query_across_newlines(self):
        self.db.on_context_new(
            make_payload(
                app_name="Chrome",
                process_name="chrome.exe",
                pid=3001,
                window_title="Boston Tea Party - Wikipedia",
                url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
                text="Parliament passed the Tea\nAct after pressure from merchants.",
            )
        )

        matches = self.db.get_recent_sessions_matching_text("Tea Act", limit=3)

        self.assertEqual(len(matches), 1)
        self.assertIn("Tea\nAct", matches[0]["text"])

    def test_keyword_search_matches_multiword_query_across_repeated_spaces(self):
        self.db.on_context_new(
            make_payload(
                app_name="Chrome",
                process_name="chrome.exe",
                pid=3002,
                window_title="Boston Tea Party - Wikipedia",
                url="https://en.wikipedia.org/wiki/Boston_Tea_Party#2",
                text="The East India Company lobbied Parliament  for  relief.",
            )
        )

        matches = self.db.get_recent_sessions_matching_text("Parliament for relief", limit=3)

        self.assertEqual(len(matches), 1)
        self.assertIn("Parliament  for  relief", matches[0]["text"])


if __name__ == "__main__":
    unittest.main()
