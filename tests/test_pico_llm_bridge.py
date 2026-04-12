"""Tests for Jetson bridge LLM request building, including DB-backed summarize."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jetson.db_manager import JetsonDB
from jetson.pico_llm_bridge import (
    build_llm_request,
    _build_summarize_prompt,
    _log_inbound_packet,
    _write_bridge_packet,
)


SYSTEM_PROMPT = "You are a helpful assistant."


def _make_context_payload(**overrides):
    defaults = {
        "app_name": "Firefox",
        "window_title": "GitHub - SPARK",
        "process_name": "firefox.exe",
        "pid": 1234,
        "source": "web_content",
        "tab_title": "SPARK repo",
        "url": "https://github.com/spark",
        "text": "README content here",
        "timestamp": 100.0,
    }
    defaults.update(overrides)
    return defaults


class BuildLlmRequestTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = JetsonDB(str(Path(self._tmpdir.name) / "test.db"))

    def tearDown(self):
        self.db.close()
        self._tmpdir.cleanup()

    def test_summarize_command_pulls_from_db(self):
        self.db.on_context_new(_make_context_payload())

        raw = json.dumps({"command": "summarize"})
        system, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertEqual(system, SYSTEM_PROMPT)
        self.assertIn("Firefox", prompt)
        self.assertIn("GitHub - SPARK", prompt)
        self.assertIn("README content here", prompt)

    def test_summarize_command_uses_updated_session(self):
        self.db.on_context_new(_make_context_payload())
        self.db.on_context_update(_make_context_payload(text="Updated content"))

        raw = json.dumps({"command": "summarize"})
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("Updated content", prompt)

    def test_summarize_command_no_active_session(self):
        raw = json.dumps({"command": "summarize"})
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("no active session", prompt)

    def test_summarize_command_no_db(self):
        raw = json.dumps({"command": "summarize"})
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=None)

        self.assertIn("no database available", prompt)

    def test_legacy_summarize_window_still_works(self):
        raw = json.dumps({
            "command": "summarize_window",
            "app_name": "Chrome",
            "window_title": "Test Page",
            "window_text": "Page content",
        })
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("Chrome", prompt)
        self.assertIn("Test Page", prompt)
        self.assertIn("Page content", prompt)

    def test_plain_text_passthrough(self):
        _, prompt = build_llm_request("just a raw prompt", SYSTEM_PROMPT)

        self.assertEqual(prompt, "just a raw prompt")


class BridgeLoggingTests(unittest.TestCase):
    def test_log_inbound_packet_logs_button_press(self):
        with mock.patch("jetson.pico_llm_bridge.logger.info") as info_log:
            _log_inbound_packet({"type": 0x05, "button_id": 0})

        info_log.assert_called_once_with("[UART IN] button_press button_id=%s", 0)

    def test_write_bridge_packet_logs_and_flushes(self):
        serial = mock.Mock()

        with mock.patch("jetson.pico_llm_bridge.logger.info") as info_log:
            _write_bridge_packet(serial, b"abc", label="summarize_done")

        serial.write.assert_called_once_with(b"abc")
        serial.flush.assert_called_once_with()
        info_log.assert_called_once_with("[UART OUT] %s bytes=%d", "summarize_done", 3)


if __name__ == "__main__":
    unittest.main()
