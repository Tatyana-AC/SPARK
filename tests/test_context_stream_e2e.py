"""End-to-end test: host context stream -> wire packets -> Jetson DB -> summarize from DB.

Exercises the full composed chain that the unit tests cover in isolation:
  host SerialSender serializes snapshot
  -> framed bytes on wire
  -> PacketParser feeds bytes
  -> handle_packet dispatches to JetsonDB
  -> button press fires lightweight session synthesis command
  -> build_llm_request pulls active and recent related context from DB
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.protocol import (
    PacketParser,
    PKT_BUTTON_PRESS,
    PKT_CONTEXT_NEW,
    PKT_CONTEXT_UPDATE,
    build_button_press,
    build_context_new,
    build_context_update,
)
from host_pc.accessibility.base import TextSource, WindowContextSnapshot, WindowInfo
from host_pc.serial_sender import SerialSender
from jetson.db_manager import JetsonDB, build_content_fingerprint, build_context_key
from jetson.pico_llm_bridge import _button_press_request_text, build_llm_request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    app_name="Firefox",
    title="GitHub - SPARK",
    text="README.md\n## SPARK\nThree-node distributed system",
    url="https://github.com/user/SPARK",
    tab_title="SPARK repo",
    pid=1234,
    timestamp=1000.0,
):
    return WindowContextSnapshot(
        window_info=WindowInfo(
            title=title,
            app_name=app_name,
            process_name=f"{app_name.lower()}.exe",
            pid=pid,
        ),
        text=text,
        source=TextSource.FULL_WINDOW,
        url=url,
        tab_title=tab_title,
        timestamp=timestamp,
    )


class FakeSerial:
    """Captures bytes written by SerialSender."""

    def __init__(self):
        self.is_open = True
        self.writes = []
        self.in_waiting = 0

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, size):
        return b""


class ContextStreamEndToEnd(unittest.TestCase):
    """Full chain: host snapshot -> wire bytes -> parser -> JetsonDB.

    Uses a single persistent parser and DB across all relay calls within
    each test, mirroring what the real Jetson bridge does.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = JetsonDB(str(Path(self._tmpdir.name) / "test.db"))
        self.parsed_packets = []

        def handle_packet(pkt):
            self.parsed_packets.append(pkt)
            pkt_type = pkt["type"]
            if pkt_type == PKT_CONTEXT_NEW:
                self.db.on_context_new(pkt)
            elif pkt_type == PKT_CONTEXT_UPDATE:
                self.db.on_context_update(pkt)
            elif pkt_type == PKT_BUTTON_PRESS:
                self.db.on_button_press(pkt["button_id"])

        self.parser = PacketParser(on_packet=handle_packet)
        self.sender = SerialSender(port="FAKE")
        self.sender._serial = FakeSerial()

    def tearDown(self):
        self.db.close()
        self._tmpdir.cleanup()

    def _relay(self):
        """Feed all bytes written by the sender into the parser."""
        for chunk in self.sender._serial.writes:
            self.parser.feed(chunk)
        self.sender._serial.writes.clear()

    # -- context new ---

    def test_context_new_lands_in_db(self):
        snap = _make_snapshot()
        self.sender.send_context_new(snap)
        self._relay()

        self.assertEqual(len(self.parsed_packets), 1)
        self.assertEqual(self.parsed_packets[0]["type"], PKT_CONTEXT_NEW)

        row = self.db.get_active_session()
        self.assertIsNotNone(row)
        self.assertEqual(row["app_name"], "Firefox")
        self.assertEqual(row["url"], "https://github.com/user/SPARK")
        self.assertIn("SPARK", row["text"])
        self.assertEqual(row["tab_title"], "SPARK repo")
        self.assertEqual(row["pid"], 1234)

    def test_context_new_fingerprint_matches(self):
        snap = _make_snapshot()
        self.sender.send_context_new(snap)
        self._relay()

        payload = self.parsed_packets[0]
        row = self.db.get_active_session()
        self.assertEqual(row["content_fingerprint"], build_content_fingerprint(payload))
        self.assertEqual(row["context_key"], build_context_key(payload))

    # -- context update ---

    def test_context_update_modifies_active_session(self):
        self.sender.send_context_new(_make_snapshot(text="original"))
        self._relay()
        self.sender.send_context_update(_make_snapshot(text="updated"))
        self._relay()

        sessions = self.db.get_recent_sessions(limit=10)
        self.assertEqual(len(sessions), 1, "update should not create a second row")
        self.assertEqual(sessions[0]["text"], "updated")

    def test_update_before_new_promotes(self):
        self.sender.send_context_update(_make_snapshot(text="orphan"))
        self._relay()

        row = self.db.get_active_session()
        self.assertIsNotNone(row, "orphan update should promote to new session")
        self.assertEqual(row["text"], "orphan")

    # -- window switch ---

    def test_window_switch_creates_second_session(self):
        self.sender.send_context_new(
            _make_snapshot(app_name="Firefox", title="GitHub")
        )
        self._relay()
        self.sender.send_context_new(
            _make_snapshot(app_name="VSCode", title="code.py", url=None)
        )
        self._relay()

        sessions = self.db.get_recent_sessions(limit=10)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(self.db.get_active_session()["app_name"], "VSCode")

    # -- button press ---

    def test_button_press_links_to_active_session(self):
        self.sender.send_context_new(_make_snapshot())
        self._relay()

        self.parser.feed(build_button_press(1))

        row = self.db._conn.execute(
            "SELECT button_id, session_id FROM button_events"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["button_id"], 1)
        self.assertEqual(row["session_id"], self.db.get_active_session()["id"])

    # -- chunked relay ---

    def test_chunked_relay_reassembles(self):
        """Packets arriving in small chunks still parse correctly."""
        self.sender.send_context_new(_make_snapshot(text="a" * 500))
        wire = b"".join(self.sender._serial.writes)
        self.sender._serial.writes.clear()

        for i in range(0, len(wire), 13):
            self.parser.feed(wire[i : i + 13])

        row = self.db.get_active_session()
        self.assertIsNotNone(row)
        self.assertEqual(row["text"], "a" * 500)

    def test_back_to_back_packets_in_single_feed(self):
        self.sender.send_context_new(
            _make_snapshot(app_name="App1", title="W1", url=None)
        )
        self.sender.send_context_new(
            _make_snapshot(app_name="App2", title="W2", url=None)
        )
        blob = b"".join(self.sender._serial.writes)
        self.sender._serial.writes.clear()

        self.parser.feed(blob)

        self.assertEqual(len(self.parsed_packets), 2)
        self.assertEqual(len(self.db.get_recent_sessions(limit=10)), 2)

    # -- interleaved context + button ---

    def test_interleaved_context_and_button_packets(self):
        self.sender.send_context_new(_make_snapshot())
        ctx_wire = b"".join(self.sender._serial.writes)
        self.sender._serial.writes.clear()

        self.sender.send_context_update(_make_snapshot(text="newer"))
        upd_wire = b"".join(self.sender._serial.writes)
        self.sender._serial.writes.clear()

        combined = ctx_wire + build_button_press(0) + upd_wire + build_button_press(1)
        self.parser.feed(combined)

        types = [p["type"] for p in self.parsed_packets]
        self.assertEqual(types, [
            PKT_CONTEXT_NEW, PKT_BUTTON_PRESS, PKT_CONTEXT_UPDATE, PKT_BUTTON_PRESS,
        ])
        buttons = self.db._conn.execute(
            "SELECT button_id FROM button_events ORDER BY id"
        ).fetchall()
        self.assertEqual([b["button_id"] for b in buttons], [0, 1])
        self.assertEqual(self.db.get_active_session()["text"], "newer")

    # -- DB-backed summarize (the key simplification) ---

    def test_summarize_from_db_matches_payload_path(self):
        """The lightweight 'summarize' command (reads DB) produces the same
        LLM prompt as the payload-bearing 'summarize_window' command."""
        snap = _make_snapshot(
            app_name="Firefox",
            title="GitHub - SPARK",
            text="README.md\n## SPARK\nDistributed system overview",
            url="https://github.com/user/SPARK",
        )
        self.sender.send_context_new(snap)
        self._relay()

        sys_prompt = "You are a helpful assistant."

        # New path: lightweight command, context pulled from DB.
        _, prompt_from_db = build_llm_request(
            '{"command": "summarize"}', sys_prompt, db=self.db
        )

        # Old path: full payload sent from host.
        _, prompt_from_payload = build_llm_request(
            json.dumps({
                "command": "summarize_window",
                "app_name": "Firefox",
                "window_title": "GitHub - SPARK",
                "window_text": "README.md\n## SPARK\nDistributed system overview",
            }),
            sys_prompt,
        )

        self.assertEqual(prompt_from_db, prompt_from_payload)

    def test_summarize_after_update_uses_latest_text(self):
        self.sender.send_context_new(_make_snapshot(text="original"))
        self._relay()
        self.sender.send_context_update(_make_snapshot(text="refactored code"))
        self._relay()

        _, prompt = build_llm_request(
            '{"command": "summarize"}', "sys", db=self.db
        )
        self.assertIn("refactored code", prompt)
        self.assertNotIn("original", prompt)

    def test_summarize_with_no_session_returns_fallback(self):
        """Summarize before any context has arrived returns a safe fallback."""
        _, prompt = build_llm_request(
            '{"command": "summarize"}', "sys", db=self.db
        )
        self.assertEqual(prompt, "(no active session)")

    def test_summarize_after_window_switch_uses_latest_window(self):
        """After switching windows, summarize uses the new active session."""
        self.sender.send_context_new(
            _make_snapshot(app_name="Firefox", text="browsing")
        )
        self._relay()
        self.sender.send_context_new(
            _make_snapshot(app_name="VSCode", title="main.py", text="def main(): pass", url=None)
        )
        self._relay()

        _, prompt = build_llm_request(
            '{"command": "summarize"}', "sys", db=self.db
        )
        self.assertIn("VSCode", prompt)
        self.assertIn("def main(): pass", prompt)
        self.assertNotIn("browsing", prompt)

    def test_button_request_synthesizes_active_anchor_with_related_recent_context(self):
        self.sender.send_context_new(
            _make_snapshot(
                app_name="Notes",
                title="History notes",
                text="Class notes about the Tea Act and East India Company.",
                url=None,
                tab_title=None,
                pid=2001,
                timestamp=1_950.0,
            )
        )
        self._relay()
        self.sender.send_context_new(
            _make_snapshot(
                app_name="Chrome",
                title="Boston Tea Party - Wikipedia",
                text="Boston Tea Party protest involving the Tea Act.",
                url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
                tab_title="Boston Tea Party",
                pid=2002,
                timestamp=2_000.0,
            )
        )
        self._relay()

        with mock.patch("jetson.pico_llm_bridge.time.time", return_value=2_000.0):
            _, prompt = build_llm_request(_button_press_request_text(1), "sys", db=self.db)

        self.assertIn("ANCHOR SOURCE", prompt)
        self.assertIn("Boston Tea Party - Wikipedia", prompt)
        self.assertIn("RELATED RECENT SOURCES", prompt)
        self.assertIn("History notes", prompt)
        self.assertIn("last 30 minutes", prompt)

    # -- reformat selection path ---

    def test_reformat_from_db_includes_selected_text_and_context(self):
        self.sender.send_context_new(
            _make_snapshot(
                app_name="VSCode",
                title="main.py",
                text="def foo():    pass",
                url=None,
            )
        )
        self._relay()

        _, prompt = build_llm_request(
            json.dumps({
                "command": "reformat_selection",
                "selected_text": "def foo():    pass",
            }),
            "You are a helpful assistant.",
            db=self.db,
        )

        self.assertIn("VSCode", prompt)
        self.assertIn("main.py", prompt)
        self.assertIn("def foo():    pass", prompt)

    def test_reformat_with_no_session_returns_no_context_prompt(self):
        _, prompt = build_llm_request(
            json.dumps({
                "command": "reformat_selection",
                "selected_text": "try this",
            }),
            "You are a helpful assistant.",
            db=self.db,
        )

        self.assertEqual(prompt, "(no active session)")


if __name__ == "__main__":
    unittest.main()
