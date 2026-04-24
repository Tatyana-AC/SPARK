"""Tests for Jetson bridge LLM request building, including DB-backed summarize."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jetson.db_manager import JetsonDB
from jetson.pico_llm_bridge import (
    _append_llm_audit_record,
    _button_press_request_text,
    build_llm_request,
    _build_respond_prompt,
    _build_summarize_prompt,
    _log_inbound_packet,
    handle_summarize_request,
    run_bridge,
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

    def test_synthesize_session_prompt_includes_active_anchor_and_related_notes(self):
        self.db.on_context_new(_make_context_payload(
            app_name="Notes",
            window_title="History notes",
            pid=2001,
            url=None,
            text="Notes mention the Tea Act and East India Company.",
            timestamp=1000.0,
        ))
        self.db.on_context_new(_make_context_payload(
            app_name="System Settings",
            window_title="Displays",
            pid=2002,
            url=None,
            text="Brightness and display arrangement.",
            timestamp=1100.0,
        ))
        self.db.on_context_new(_make_context_payload(
            app_name="Chrome",
            window_title="Boston Tea Party - Wikipedia",
            pid=2003,
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="The Boston Tea Party was a protest involving the Tea Act and East India Company.",
            timestamp=1200.0,
        ))

        raw = json.dumps({"command": "synthesize_session", "window_minutes": 30})
        with mock.patch("jetson.pico_llm_bridge.time.time", return_value=1200.0):
            system, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

        self.assertIn("session synthesis", system.lower())
        self.assertIn("ANCHOR SOURCE", prompt)
        self.assertIn("Boston Tea Party - Wikipedia", prompt)
        self.assertIn("RELATED RECENT SOURCES", prompt)
        self.assertIn("History notes", prompt)
        self.assertIn("Related context", prompt)
        self.assertNotIn("Brightness and display arrangement", prompt)

    def test_synthesize_session_does_not_match_unrelated_recent_apps_on_generic_terms(self):
        self.db.on_context_new(_make_context_payload(
            app_name="Chrome",
            window_title="Project docs",
            pid=2001,
            url="https://github.com/example/project",
            tab_title="Project docs",
            text="Company access support and productivity setup notes.",
            timestamp=1000.0,
        ))
        self.db.on_context_new(_make_context_payload(
            app_name="Notes",
            window_title="History notes",
            pid=2002,
            url=None,
            text="The Tea Act and East India Company are relevant to the Boston Tea Party.",
            timestamp=1100.0,
        ))
        self.db.on_context_new(_make_context_payload(
            app_name="Chrome",
            window_title="Boston Tea Party - Wikipedia",
            pid=2003,
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
            text="The Boston Tea Party was a protest involving the Tea Act and East India Company.",
            timestamp=1200.0,
        ))

        with mock.patch("jetson.pico_llm_bridge.time.time", return_value=1200.0):
            _, prompt = build_llm_request(
                json.dumps({"command": "synthesize_session", "window_minutes": 30}),
                SYSTEM_PROMPT,
                db=self.db,
            )

        self.assertIn("History notes", prompt)
        self.assertNotIn("Project docs", prompt)

    def test_synthesize_session_without_related_context_is_anchor_only(self):
        self.db.on_context_new(_make_context_payload(
            app_name="Chrome",
            window_title="Boston Tea Party - Wikipedia",
            text="Boston Tea Party article text",
            timestamp=1200.0,
        ))

        with mock.patch("jetson.pico_llm_bridge.time.time", return_value=1200.0):
            _, prompt = build_llm_request(
                json.dumps({"command": "synthesize_session", "window_minutes": 30}),
                SYSTEM_PROMPT,
                db=self.db,
            )

        self.assertIn("No related recent context cleared the relevance threshold", prompt)

    def test_button_press_request_text_uses_session_synthesis(self):
        payload = json.loads(_button_press_request_text(0))

        self.assertEqual(payload, {"command": "synthesize_session", "window_minutes": 30})

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

    def test_log_inbound_packet_logs_request_command(self):
        with mock.patch("jetson.pico_llm_bridge.logger.info") as info_log:
            _log_inbound_packet(
                {
                    "type": 0x03,
                    "request": json.dumps(
                        {"command": "synthesize_session", "window_minutes": 30}
                    ),
                }
            )

        info_log.assert_called_once_with(
            "[UART IN] summarize_request chars=%d command=%s",
            55,
            "synthesize_session",
        )

    def test_write_bridge_packet_logs_and_flushes(self):
        serial = mock.Mock()

        with mock.patch("jetson.pico_llm_bridge.logger.info") as info_log:
            _write_bridge_packet(serial, b"abc", label="summarize_done")

        serial.write.assert_called_once_with(b"abc")
        serial.flush.assert_called_once_with()
        info_log.assert_called_once_with("[UART OUT] %s bytes=%d", "summarize_done", 3)


class _ScriptedSerial:
    def __init__(self, script):
        self._script = list(script)
        self.close = mock.Mock()

    def read(self, _size):
        if not self._script:
            raise KeyboardInterrupt()
        value = self._script.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class RunBridgeReconnectWatchdogTests(unittest.TestCase):
    def _make_args(self):
        return mock.Mock(
            port="/dev/ttyTHS0",
            baud=115200,
            reconnect_delay=0.0,
            reconnect_watchdog_grace=1.0,
            db=":memory:",
            llm_url="http://127.0.0.1:8080",
            system_prompt=SYSTEM_PROMPT,
            structured=False,
            stream=True,
            timeout=120,
            audit_log=None,
        )

    def test_reconnect_watchdog_forces_second_reopen_when_no_packets_arrive(self):
        args = self._make_args()
        serial1 = _ScriptedSerial([b"x", RuntimeError("device reports readiness to read but returned no data")])
        serial2 = _ScriptedSerial([b"", b"", KeyboardInterrupt()])
        serial3 = _ScriptedSerial([KeyboardInterrupt()])
        parser = mock.Mock()
        db = mock.Mock()

        with mock.patch("jetson.pico_llm_bridge.JetsonDB", return_value=db):
            with mock.patch(
                "jetson.pico_llm_bridge.open_serial_with_retry",
                side_effect=[serial1, serial2, serial3],
            ) as open_serial:
                with mock.patch("jetson.pico_llm_bridge.PacketParser", return_value=parser):
                    with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                        with mock.patch(
                            "jetson.pico_llm_bridge.time.monotonic",
                            side_effect=[10.0, 10.4, 11.2, 20.0],
                        ):
                            with self.assertRaises(KeyboardInterrupt):
                                run_bridge(args)

        self.assertEqual(open_serial.call_count, 3)
        parser.feed.assert_called_once_with(b"x")
        serial2.close.assert_called_once()
        db.close.assert_called_once()

    def test_reconnect_watchdog_stays_disabled_until_bridge_has_seen_real_traffic(self):
        args = self._make_args()
        serial1 = _ScriptedSerial([b"", b"", KeyboardInterrupt()])
        parser = mock.Mock()
        db = mock.Mock()

        with mock.patch("jetson.pico_llm_bridge.JetsonDB", return_value=db):
            with mock.patch(
                "jetson.pico_llm_bridge.open_serial_with_retry",
                return_value=serial1,
            ) as open_serial:
                with mock.patch("jetson.pico_llm_bridge.PacketParser", return_value=parser):
                    with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                        with mock.patch("jetson.pico_llm_bridge.time.monotonic", side_effect=[10.0, 11.5]):
                            with self.assertRaises(KeyboardInterrupt):
                                run_bridge(args)

        self.assertEqual(open_serial.call_count, 1)
        parser.feed.assert_not_called()
        serial1.close.assert_called_once()
        db.close.assert_called_once()


class AuditLoggingTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.audit_log = Path(self._tmpdir.name) / "llm_audit.log"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_append_llm_audit_record_writes_divided_request_response_block(self):
        payload = {
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
            "stream": False,
        }

        _append_llm_audit_record(
            self.audit_log,
            command="summarize_window",
            endpoint="http://127.0.0.1:8080/v1/chat/completions",
            request_payload=payload,
            response_text="final outbound text",
        )

        text = self.audit_log.read_text(encoding="utf-8")
        self.assertIn("SPARK LLM AUDIT", text)
        self.assertIn("Command: summarize_window", text)
        self.assertIn("Endpoint: http://127.0.0.1:8080/v1/chat/completions", text)
        self.assertIn("===== REQUEST JSON BEGIN =====", text)
        self.assertIn(json.dumps(payload, indent=2), text)
        self.assertIn("===== RESPONSE TEXT BEGIN =====", text)
        self.assertIn("final outbound text", text)
        self.assertIn("=" * 80, text)

    def test_handle_summarize_request_logs_exact_payload_and_streamed_final_output(self):
        ser = mock.Mock()
        request = json.dumps(
            {
                "command": "summarize_window",
                "app_name": "Chrome",
                "window_title": "Draft",
                "window_text": "Visible context",
            }
        )
        args = mock.Mock(
            stream=True,
            structured=False,
            timeout=120,
            llm_url="http://127.0.0.1:8080",
            system_prompt=SYSTEM_PROMPT,
            audit_log=str(self.audit_log),
        )

        fake_stream_response = mock.Mock()
        fake_stream_response.__enter__ = mock.Mock(return_value=fake_stream_response)
        fake_stream_response.__exit__ = mock.Mock(return_value=False)
        fake_stream_response.raise_for_status = mock.Mock()
        fake_stream_response.iter_lines = mock.Mock(
            return_value=[
                'data: {"choices":[{"delta":{"content":"hello "}}]}',
                'data: {"choices":[{"delta":{"content":"world"}}]}',
                "data: [DONE]",
            ]
        )

        with mock.patch("jetson.pico_llm_bridge.requests.post", return_value=fake_stream_response) as post:
            with mock.patch("jetson.pico_llm_bridge._write_bridge_packet"):
                with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                    handle_summarize_request(ser, request, args, db=None)

        post.assert_called_once()
        text = self.audit_log.read_text(encoding="utf-8")
        self.assertIn('"stream": true', text)
        self.assertIn('"role": "system"', text)
        self.assertIn('"role": "user"', text)
        self.assertIn("hello world", text)


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
            audit_log=None,
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
        query_payload = query.call_args.args[1]
        self.assertFalse(query_payload["stream"])
        self.assertNotIn("response_format", query_payload)
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
        query_payload = query.call_args.args[1]
        self.assertFalse(query_payload["stream"])
        self.assertNotIn("response_format", query_payload)
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
        query_payload = query.call_args.args[1]
        self.assertFalse(query_payload["stream"])
        self.assertNotIn("response_format", query_payload)
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
