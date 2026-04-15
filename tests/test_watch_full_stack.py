import io
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class ConfigureAppLoggingTests(unittest.TestCase):
    def _clear_root_handlers(self):
        root = logging.getLogger()
        handlers = list(root.handlers)
        for handler in handlers:
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    def test_configure_app_logging_adds_rotating_handler(self):
        import spark_app_v2

        with TemporaryDirectory() as tmpdir:
            self._clear_root_handlers()
            log_path = Path(tmpdir) / "spark_app_v2.log"

            spark_app_v2.configure_app_logging(log_path=log_path)

            file_handlers = [
                handler
                for handler in logging.getLogger().handlers
                if getattr(handler, "baseFilename", None)
            ]
            self.assertTrue(any(Path(handler.baseFilename) == log_path for handler in file_handlers))

    def test_configure_app_logging_keeps_existing_stream_handler(self):
        import spark_app_v2

        with TemporaryDirectory() as tmpdir:
            self._clear_root_handlers()
            root = logging.getLogger()
            stream = logging.StreamHandler()
            root.addHandler(stream)

            spark_app_v2.configure_app_logging(log_path=Path(tmpdir) / "spark_app_v2.log")

            self.assertIn(stream, logging.getLogger().handlers)


class WatchFullStackTests(unittest.TestCase):
    def test_check_local_spark_app_process_ignores_shell_wrappers(self):
        from watch_full_stack import check_local_spark_app_process

        result = check_local_spark_app_process(
            '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoExit -Command '
            "Set-Location 'C:\\SPARK'; & 'C:\\SPARK\\.venv\\Scripts\\python.exe' 'C:\\SPARK\\spark_app_v2.py'"
        )

        self.assertEqual(result.availability, "missing")
        self.assertEqual(result.status, "App process missing")

    def test_map_app_log_line_routes_pico_debug_to_pico(self):
        from watch_full_stack import map_app_log_line

        source, message = map_app_log_line(
            "2026-04-10 12:44:40,604 pico.debug INFO [PICO] heartbeat"
        )

        self.assertEqual(source, "PICO")
        self.assertEqual(message, "heartbeat")

    def test_map_app_log_line_defaults_to_app(self):
        from watch_full_stack import map_app_log_line

        source, message = map_app_log_line(
            "2026-04-10 12:44:40,604 spark_app_v2 INFO app started"
        )

        self.assertEqual(source, "APP")
        self.assertEqual(message, "app started")

    def test_update_app_serial_status_line_from_connect_message(self):
        from watch_full_stack import update_app_serial_status_line

        self.assertEqual(
            update_app_serial_status_line(None, "SerialSender: connected on COM6 @ 115200"),
            "APP CDC: connected | COM6 @ 115200",
        )

    def test_update_app_serial_status_line_from_write_error(self):
        from watch_full_stack import update_app_serial_status_line

        self.assertEqual(
            update_app_serial_status_line("APP CDC: connected | COM6 @ 115200", "SerialSender: write error - Write timeout"),
            "APP CDC: error | write timeout",
        )

    def test_map_bridge_log_line_keeps_request_start(self):
        from watch_full_stack import map_bridge_log_line

        event = map_bridge_log_line(
            "2000-01-15 19:24:18,974 [INFO] Handling summarize request: chars=22 stream=True structured=False llm_url=http://127.0.0.1:8080"
        )

        self.assertEqual(event.source, "JETSON-BRIDGE")
        self.assertEqual(event.message, "summarize request started")

    def test_map_bridge_log_line_keeps_request_end(self):
        from watch_full_stack import map_bridge_log_line

        event = map_bridge_log_line(
            "2000-01-15 19:24:18,974 [INFO] Summarize request completed with 139 streamed chunk(s)"
        )

        self.assertEqual(event.source, "JETSON-BRIDGE")
        self.assertEqual(event.message, "summarize request finished")

    def test_map_bridge_log_line_hides_chunk_spam(self):
        from watch_full_stack import map_bridge_log_line

        self.assertIsNone(
            map_bridge_log_line(
                "2000-01-15 19:24:18,934 [INFO] [UART OUT] summarize_chunk bytes=31"
            )
        )
        self.assertIsNone(
            map_bridge_log_line(
                "2000-01-15 19:24:18,933 [INFO] [UART OUT] summarize_response chars=13 packets=1"
            )
        )

    def test_map_llm_log_line_keeps_request_received_and_finished(self):
        from watch_full_stack import map_llm_log_line

        start = map_llm_log_line(
            "slot launch_slot_: id  3 | task 701 | processing task, is_child = 0"
        )
        end = map_llm_log_line(
            "srv  log_server_r: done request: POST /v1/chat/completions 127.0.0.1 200"
        )

        self.assertEqual(start.source, "JETSON-LLM")
        self.assertEqual(start.message, "request received")
        self.assertEqual(end.source, "JETSON-LLM")
        self.assertEqual(end.message, "output generation finished")

    def test_map_llm_log_line_hides_token_level_noise(self):
        from watch_full_stack import map_llm_log_line

        self.assertIsNone(
            map_llm_log_line(
                "slot update_slots: id  3 | task 701 | prompt processing progress, n_tokens = 231, batch.n_tokens = 231, progress = 1.000000"
            )
        )

    def test_file_tail_source_starts_at_eof(self):
        from watch_full_stack import FileTailSource

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bridge.log"
            path.write_text("old line\n", encoding="utf-8")
            source = FileTailSource(path, source_label="JETSON-BRIDGE")

            self.assertEqual(source.poll(), [])

    def test_file_tail_source_reads_new_lines_after_startup(self):
        from watch_full_stack import FileTailSource

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bridge.log"
            path.write_text("old line\n", encoding="utf-8")
            source = FileTailSource(path, source_label="JETSON-BRIDGE")
            source.poll()

            path.write_text("old line\nnew line\n", encoding="utf-8")
            events = source.poll()

            self.assertEqual([event.message for event in events], ["new line"])

    def test_file_tail_source_skips_filtered_lines(self):
        from watch_full_stack import FileTailSource, LogEvent

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bridge.log"
            path.write_text("old line\n", encoding="utf-8")

            def _mapper(line):
                if line == "skip me":
                    return None
                return LogEvent(source="JETSON-BRIDGE", message=line)

            source = FileTailSource(path, source_label="JETSON-BRIDGE", mapper=_mapper)
            source.poll()

            path.write_text("old line\nskip me\nkeep me\n", encoding="utf-8")
            events = source.poll()

            self.assertEqual([event.message for event in events], ["keep me"])

    def test_render_watch_event_includes_local_timestamp(self):
        from watch_full_stack import RenderEvent, render_watch_event

        out = io.StringIO()
        render_watch_event(
            RenderEvent(kind="log", label="APP", message="app started"),
            out=out,
            now_text="12:44:40",
        )

        self.assertEqual(out.getvalue(), "[12:44:40] [APP] app started\n")

    def test_build_dashboard_frame_includes_component_status_and_recent_logs(self):
        from watch_full_stack import build_dashboard_frame

        frame = build_dashboard_frame(
            component_lines=["APP: missing", "JETSON-BRIDGE: present"],
            log_lines=["[12:44:40] [APP] app started", "[12:44:41] [CHECK] APP missing"],
            now_text="12:44:42",
        )

        self.assertIn("SPARK Full Stack Watcher  12:44:42", frame)
        self.assertIn("APP: missing", frame)
        self.assertIn("JETSON-BRIDGE: present", frame)
        self.assertIn("[12:44:40] [APP] app started", frame)

    def test_build_pico_status_line_reports_disconnect(self):
        from watch_full_stack import build_pico_status_line

        state = type("PicoState", (), {"connected": False, "error": "device not found"})()

        self.assertEqual(
            build_pico_status_line(state),
            "PICO HID: missing | device not found",
        )

    def test_build_pico_status_line_reports_runtime_flags(self):
        from watch_full_stack import build_pico_status_line

        state = type(
            "PicoState",
            (),
            {
                "connected": True,
                "upload_active": True,
                "active_message_id": 7,
                "response_active": False,
                "response_complete": True,
                "response_len": 128,
                "response_chunk_count": 3,
                "runtime_status_text": "button:1|after_button_events",
                "error": "",
            },
        )()

        self.assertEqual(
            build_pico_status_line(state),
            "PICO HID: present | upload=ACTIVE msg_id=7 response=COMPLETE len=128 chunks=3 | debug=button:1|after_button_events",
        )

    def test_build_component_lines_includes_pico_status(self):
        from watch_full_stack import HealthCheckResult, build_component_lines

        pico_state = type(
            "PicoState",
            (),
            {
                "connected": True,
                "upload_active": False,
                "active_message_id": 0,
                "response_active": True,
                "response_complete": False,
                "response_len": 42,
                "response_chunk_count": 2,
                "error": "",
            },
        )()

        lines = build_component_lines(
            [
                HealthCheckResult(
                    component_name="app-process",
                    label="APP",
                    availability="present",
                    status="App process running (1 matches)",
                )
            ],
            pico_state=pico_state,
        )

        self.assertEqual(lines[0], "PICO HID: present | upload=idle msg_id=0 response=STREAMING len=42 chunks=2")
        self.assertIn("APP process: present | App process running (1 matches)", lines)

    def test_build_component_lines_includes_app_serial_status(self):
        from watch_full_stack import build_component_lines

        lines = build_component_lines([], app_serial_status_line="APP CDC: error | write timeout")

        self.assertEqual(lines[0], "APP CDC: error | write timeout")

    def test_build_pico_poller_is_disabled_when_app_process_is_running(self):
        from watch_full_stack import build_pico_poller

        poller = build_pico_poller(app_running=True)

        self.assertIsNone(poller)

    def test_run_watch_loop_uses_app_log_pico_events_without_hid_poller(self):
        from watch_full_stack import AppLogSource, build_parser, run_watch_loop

        class _FakeOut(io.StringIO):
            def isatty(self):
                return False

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "spark_app_v2.log"
            path.write_text("2026-04-10 12:44:40,604 spark_app_v2 INFO app started\n", encoding="utf-8")
            source = AppLogSource(path)

            state = {"calls": 0}

            def _sleep(_seconds):
                state["calls"] += 1
                if state["calls"] == 1:
                    path.write_text(
                        "2026-04-10 12:44:40,604 spark_app_v2 INFO app started\n"
                        "2026-04-10 12:44:45,604 pico.debug INFO [PICO] heartbeat\n",
                        encoding="utf-8",
                    )

            args = build_parser().parse_args(["--check-interval", "100"])
            out = _FakeOut()

            run_watch_loop(
                args,
                out=out,
                sources=[source],
                health_check_runner=lambda _args: [],
                pico_poller=None,
                monotonic=lambda: 0.0,
                sleep_fn=_sleep,
                max_iterations=4,
            )

            self.assertIn("[PICO] heartbeat", out.getvalue())

    def test_dashboard_renderer_uses_ansi_redraw_in_interactive_mode(self):
        from watch_full_stack import DashboardRenderer

        out = io.StringIO()
        renderer = DashboardRenderer(out=out, interactive=True)
        renderer.render("frame body")

        self.assertEqual(out.getvalue(), "\x1b[H\x1b[Jframe body")

    def test_dashboard_renderer_uses_custom_redraw_backend_when_provided(self):
        from watch_full_stack import DashboardRenderer

        calls = []
        renderer = DashboardRenderer(
            out=io.StringIO(),
            interactive=True,
            redraw=lambda frame: calls.append(frame),
        )

        renderer.render("frame body")

        self.assertEqual(calls, ["frame body"])

    def test_watcher_forces_append_mode_even_on_tty(self):
        from watch_full_stack import should_use_interactive_dashboard

        class _FakeOut:
            def isatty(self):
                return True

        out = _FakeOut()

        self.assertFalse(
            should_use_interactive_dashboard(
                out,
                os_name="nt",
            )
        )

    def test_run_watch_loop_renders_source_events_in_noninteractive_mode(self):
        from watch_full_stack import LogEvent, build_parser, run_watch_loop

        class _FakeSource:
            source_label = "JETSON-BRIDGE"

            def __init__(self):
                self.calls = 0

            def poll(self):
                self.calls += 1
                if self.calls == 3:
                    return [LogEvent(source="JETSON-BRIDGE", message="bridge line")]
                return []

        class _FakeOut(io.StringIO):
            def isatty(self):
                return False

        args = build_parser().parse_args(["--check-interval", "100"])
        out = _FakeOut()
        source = _FakeSource()

        run_watch_loop(
            args,
            out=out,
            sources=[source],
            health_check_runner=lambda _args: [],
            monotonic=lambda: 0.0,
            sleep_fn=lambda _s: None,
            max_iterations=4,
        )

        self.assertIn("[JETSON-BRIDGE] bridge line", out.getvalue())

    def test_run_watch_loop_logs_pico_runtime_status_changes(self):
        from watch_full_stack import build_parser, run_watch_loop

        class _FakeOut(io.StringIO):
            def isatty(self):
                return False

        pico_states = iter(
            [
                type("PicoState", (), {
                    "connected": True,
                    "upload_active": False,
                    "active_message_id": 0,
                    "response_active": False,
                    "response_complete": False,
                    "response_len": 0,
                    "response_chunk_count": 0,
                    "runtime_status_text": "heartbeat|after_sleep",
                    "error": "",
                })(),
                type("PicoState", (), {
                    "connected": True,
                    "upload_active": False,
                    "active_message_id": 0,
                    "response_active": True,
                    "response_complete": False,
                    "response_len": 12,
                    "response_chunk_count": 1,
                    "runtime_status_text": "rdone:4|after_sleep",
                    "error": "",
                })(),
            ]
        )

        args = build_parser().parse_args(["--check-interval", "100"])
        out = _FakeOut()

        run_watch_loop(
            args,
            out=out,
            sources=[],
            health_check_runner=lambda _args: [],
            pico_poller=type("Poller", (), {"poll": lambda self: next(pico_states)})(),
            monotonic=lambda: 0.0,
            sleep_fn=lambda _s: None,
            max_iterations=2,
        )

        self.assertIn("[PICO] rdone:4", out.getvalue())

    def test_append_pico_runtime_events_repeats_heartbeat_after_interval(self):
        from watch_full_stack import _append_pico_runtime_events

        rendered_events = []
        pico_state = type("PicoState", (), {"runtime_status_text": "heartbeat|after_sleep"})()

        text, emitted_at = _append_pico_runtime_events(
            rendered_events,
            previous_text="heartbeat|after_sleep",
            previous_emitted_at=0.0,
            pico_state=pico_state,
            now=5.0,
        )

        self.assertEqual(text, "heartbeat|after_sleep")
        self.assertEqual(emitted_at, 5.0)
        self.assertEqual([(event.label, event.message) for event in rendered_events], [("PICO", "heartbeat")])

    def test_run_watch_loop_renders_real_file_tail_events(self):
        from watch_full_stack import FileTailSource, build_parser, run_watch_loop

        class _FakeOut(io.StringIO):
            def isatty(self):
                return False

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bridge.log"
            path.write_text("old\n", encoding="utf-8")
            source = FileTailSource(path, source_label="JETSON-BRIDGE")

            state = {"calls": 0}

            def _sleep(_seconds):
                state["calls"] += 1
                if state["calls"] == 1:
                    path.write_text("old\nnew line\n", encoding="utf-8")

            args = build_parser().parse_args(["--check-interval", "100"])
            out = _FakeOut()

            run_watch_loop(
                args,
                out=out,
                sources=[source],
                health_check_runner=lambda _args: [],
                monotonic=lambda: 0.0,
                sleep_fn=_sleep,
                max_iterations=4,
            )

            self.assertIn("[JETSON-BRIDGE] new line", out.getvalue())


if __name__ == "__main__":
    unittest.main()
