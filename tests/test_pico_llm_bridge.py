"""Tests for Jetson bridge LLM request building, including DB-backed summarize."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jetson.db_manager import JetsonDB
from jetson.pico_llm_bridge import (
    build_llm_request,
    _build_respond_prompt,
    _build_summarize_prompt,
    _log_inbound_packet,
    handle_summarize_request,
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

    def test_reformat_selection_command_pulls_from_db(self):
        self.db.on_context_new(_make_context_payload())

        raw = json.dumps({
            "command": "reformat_selection",
            "selected_text": "  adjust spacing  ",
        })
        system, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("code rewriter", system)
        self.assertIn("rewritten selected text", system)
        self.assertIn("Active application: Firefox", prompt)
        self.assertIn("Window title: GitHub - SPARK", prompt)
        self.assertIn("README content here", prompt)
        self.assertIn("adjust spacing", prompt)

    def test_reformat_selection_preserves_formatting_sensitive_selected_text(self):
        self.db.on_context_new(_make_context_payload())

        raw = json.dumps({
            "command": "reformat_selection",
            "selected_text": "  line1\n\tline2\n    line3  \n",
        })
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("  line1\n\tline2\n    line3  \n", prompt)

    def test_reformat_prompt_demands_grammar_and_spelling_corrections(self):
        self.db.on_context_new(_make_context_payload())

        raw = json.dumps({
            "command": "reformat_selection",
            "selected_text": "thsi is not corrrect",
        })
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("Correct spelling, grammar", prompt)
        self.assertIn("punctuation", prompt)
        self.assertIn("Preserve the meaning", prompt)
        self.assertIn("relevant", prompt)

    def test_reformat_selection_command_without_active_session(self):
        raw = json.dumps({
            "command": "reformat_selection",
            "selected_text": "fix this",
        })
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("no active session", prompt)

    def test_reformat_selection_uses_reformat_system_prompt(self):
        self.db.on_context_new(_make_context_payload())

        raw = json.dumps({
            "command": "reformat_selection",
            "selected_text": "fix this",
        })
        system, _ = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("rewritten", system)
        self.assertIn("selected text", system)
        self.assertNotEqual(system, SYSTEM_PROMPT)

    def test_respond_selection_command_pulls_from_db(self):
        self.db.on_context_new(_make_context_payload(text="Visible draft context"))

        raw = json.dumps({
            "command": "respond_selection",
            "previous_user_input": "Thanks for the update. I wanted to follow up on",
        })
        system, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("continue and complete the user's in-progress text", system.lower())
        self.assertIn("Active application: Firefox", prompt)
        self.assertIn("Window title: GitHub - SPARK", prompt)
        self.assertIn("Visible draft context", prompt)
        self.assertIn("Thanks for the update. I wanted to follow up on", prompt)

    def test_respond_selection_without_active_session(self):
        raw = json.dumps({
            "command": "respond_selection",
            "previous_user_input": "draft text",
        })
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("no active session", prompt)

    def test_keyword_search_command_uses_three_most_recent_matching_entries(self):
        self.db.on_context_new(
            _make_context_payload(
                text="old irrational proof",
                pid=1001,
                url="https://example.com/old",
                window_title="old",
            )
        )
        self.db.on_context_new(
            _make_context_payload(
                text="newer irrational contradiction",
                pid=1002,
                url="https://example.com/newer",
                window_title="newer",
            )
        )
        self.db.on_context_new(
            _make_context_payload(
                text="freshest irrational lemma",
                pid=1003,
                url="https://example.com/freshest",
                window_title="freshest",
            )
        )
        self.db.on_context_new(
            _make_context_payload(
                text="freshest unrelated note",
                pid=1004,
                url="https://example.com/unrelated",
                window_title="unrelated",
            )
        )

        raw = json.dumps({
            "command": "keyword_search",
            "selected_text": "irrational",
        })
        system, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("summarize the three most recent matching entries", system.lower())
        self.assertIn("freshest irrational lemma", prompt)
        self.assertIn("newer irrational contradiction", prompt)
        self.assertIn("old irrational proof", prompt)
        self.assertNotIn("freshest unrelated note", prompt)

    def test_keyword_search_prompt_uses_keyword_centered_snippets_instead_of_full_entry_text(self):
        long_text = ("prefix " * 200) + "Parliament passed the Tea Act" + (" suffix" * 200)
        self.db.on_context_new(_make_context_payload(text=long_text))

        raw = json.dumps({
            "command": "keyword_search",
            "selected_text": "Parliament",
        })
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("Parliament passed the Tea Act", prompt)
        self.assertNotIn("prefix prefix prefix prefix prefix prefix prefix prefix prefix prefix prefix prefix", prompt)
        self.assertLess(len(prompt), 3000)

    def test_keyword_search_without_matches_returns_no_match_marker(self):
        self.db.on_context_new(_make_context_payload(text="freshest unrelated note"))

        raw = json.dumps({
            "command": "keyword_search",
            "selected_text": "irrational",
        })
        _, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("no keyword matches", prompt)


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


class ReformatHandlingTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = JetsonDB(str(Path(self._tmpdir.name) / "test.db"))

    def tearDown(self):
        self.db.close()
        self._tmpdir.cleanup()

    def _make_args(self):
        return mock.Mock(
            stream=False,
            structured=True,
            timeout=120,
            llm_url="http://127.0.0.1:8080",
            system_prompt=SYSTEM_PROMPT,
        )

    def test_reformat_selection_ignores_structured_response_mode(self):
        self.db.on_context_new(_make_context_payload())
        ser = mock.Mock()
        request = json.dumps({
            "command": "reformat_selection",
            "selected_text": "inline code",
        })

        with mock.patch("jetson.pico_llm_bridge._emit_summary_response") as emit_chunks:
            with mock.patch("jetson.pico_llm_bridge.query_llm_blocking", return_value="{\"app\": \"x\"}") as query:
                with mock.patch("jetson.pico_llm_bridge._write_bridge_packet"):
                    with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                        handle_summarize_request(ser, request, self._make_args(), db=self.db)

        query.assert_called_once()
        query_kwargs = query.call_args.kwargs
        self.assertFalse(query_kwargs["structured"])
        emit_chunks.assert_any_call(ser, '{"app": "x"}')

    def test_reformat_selection_without_session_sends_error(self):
        ser = mock.Mock()
        request = json.dumps({
            "command": "reformat_selection",
            "selected_text": "inline code",
        })

        with mock.patch("jetson.pico_llm_bridge.build_error", return_value=b"ERROR") as mk_error:
            with mock.patch("jetson.pico_llm_bridge.query_llm_blocking") as query:
                with mock.patch("jetson.pico_llm_bridge._write_bridge_packet") as writer:
                    handle_summarize_request(ser, request, self._make_args(), db=self.db)

        mk_error.assert_called_once()
        query.assert_not_called()
        writer.assert_called_once_with(ser, b"ERROR", label="error")

    def test_respond_selection_ignores_structured_response_mode(self):
        self.db.on_context_new(_make_context_payload())
        ser = mock.Mock()
        request = json.dumps({
            "command": "respond_selection",
            "previous_user_input": "half-written reply",
        })

        with mock.patch("jetson.pico_llm_bridge._emit_summary_response") as emit_chunks:
            with mock.patch("jetson.pico_llm_bridge.query_llm_blocking", return_value="completed reply") as query:
                with mock.patch("jetson.pico_llm_bridge._write_bridge_packet"):
                    with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                        handle_summarize_request(ser, request, self._make_args(), db=self.db)

        query.assert_called_once()
        query_kwargs = query.call_args.kwargs
        self.assertFalse(query_kwargs["structured"])
        emit_chunks.assert_any_call(ser, "completed reply")

    def test_respond_selection_without_session_sends_error(self):
        ser = mock.Mock()
        request = json.dumps({
            "command": "respond_selection",
            "previous_user_input": "half-written reply",
        })

        with mock.patch("jetson.pico_llm_bridge.build_error", return_value=b"ERROR") as mk_error:
            with mock.patch("jetson.pico_llm_bridge.query_llm_blocking") as query:
                with mock.patch("jetson.pico_llm_bridge._write_bridge_packet") as writer:
                    handle_summarize_request(ser, request, self._make_args(), db=self.db)

        mk_error.assert_called_once()
        query.assert_not_called()
        writer.assert_called_once_with(ser, b"ERROR", label="error")

    def test_keyword_search_ignores_structured_response_mode(self):
        self.db.on_context_new(_make_context_payload(text="irrational proof example"))
        ser = mock.Mock()
        request = json.dumps({
            "command": "keyword_search",
            "selected_text": "irrational",
        })

        with mock.patch("jetson.pico_llm_bridge._emit_summary_response") as emit_chunks:
            with mock.patch("jetson.pico_llm_bridge.query_llm_blocking", return_value="matching summary") as query:
                with mock.patch("jetson.pico_llm_bridge._write_bridge_packet"):
                    with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                        handle_summarize_request(ser, request, self._make_args(), db=self.db)

        query.assert_called_once()
        self.assertFalse(query.call_args.kwargs["structured"])
        emit_chunks.assert_any_call(ser, "matching summary")

    def test_keyword_search_without_matches_sends_normal_response(self):
        self.db.on_context_new(_make_context_payload(text="freshest unrelated note"))
        ser = mock.Mock()
        request = json.dumps({
            "command": "keyword_search",
            "selected_text": "irrational",
        })

        with mock.patch("jetson.pico_llm_bridge._emit_summary_response") as emit_chunks:
            with mock.patch("jetson.pico_llm_bridge.query_llm_blocking") as query:
                with mock.patch("jetson.pico_llm_bridge._write_bridge_packet"):
                    with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                        handle_summarize_request(ser, request, self._make_args(), db=self.db)

        query.assert_not_called()
        emit_chunks.assert_any_call(ser, 'No recent entries matched "irrational".')


if __name__ == "__main__":
    unittest.main()
