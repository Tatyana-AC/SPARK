import importlib.util
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path


class _FakeRuntimeRunnerModule:
    @staticmethod
    def run_with_diagnostics(callback, *, error_log_path, trace_log_path):
        return None


class _FakeEvent:
    def __init__(self, key_number, pressed=True):
        self.key_number = key_number
        self.pressed = pressed


class _FakeEvents:
    def __init__(self, events):
        self._events = list(events)

    def get(self):
        if self._events:
            return self._events.pop(0)
        return None


class _FakeButtons:
    def __init__(self, events):
        self.events = _FakeEvents(events)


class _FakeLcdUi:
    def __init__(self, call_log=None):
        self.presses = []
        self.call_log = call_log

    def handle_press(self, index, *, now):
        if self.call_log is not None:
            self.call_log.append(("lcd", index, now))
        self.presses.append((index, now))

    def tick(self, *, now):
        if self.call_log is not None:
            self.call_log.append(("tick", now))


class _FakeSerialBridge:
    def __init__(self, call_log):
        self.call_log = call_log

    def relay_once(self, *, max_chunk_size):
        self.call_log.append(("serial", max_chunk_size))


class _FakeJetsonTransport:
    def __init__(self, call_log):
        self.call_log = call_log

    def poll(self, *, max_chunk_size):
        self.call_log.append(("transport", max_chunk_size))


class PicoCodeTests(unittest.TestCase):
    def _load_code_module(self):
        module_name = f"_test_pico_code_{uuid.uuid4().hex}"
        module_path = Path(__file__).resolve().parents[1] / "pico" / "code.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)

        prior_runtime_runner = sys.modules.get("runtime_runner")
        sys.modules["runtime_runner"] = _FakeRuntimeRunnerModule()
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        finally:
            if prior_runtime_runner is None:
                sys.modules.pop("runtime_runner", None)
            else:
                sys.modules["runtime_runner"] = prior_runtime_runner
        return module

    def test_drain_button_events_updates_lcd_for_press_only_and_emits_debug_first(self):
        module = self._load_code_module()
        call_log = []
        lcd_ui = _FakeLcdUi(call_log=call_log)
        buttons = _FakeButtons([_FakeEvent(2), _FakeEvent(1, pressed=False)])
        module.BUTTON_EVENT_DEBUG_ENABLED = True
        module._send_button_debug = lambda message: call_log.append(("debug", message))

        module._drain_button_events(
            buttons,
            lcd_ui,
            now=123.0,
        )

        self.assertEqual(lcd_ui.presses, [(2, 123.0)])
        self.assertEqual(
            call_log,
            [
                ("debug", "PB3 pressed"),
                ("lcd", 2, 123.0),
                ("debug", "PB3 done"),
            ],
        )
        self.assertIsNone(buttons.events.get())

    def test_drain_button_events_skips_debug_when_button_debug_disabled(self):
        module = self._load_code_module()
        call_log = []
        lcd_ui = _FakeLcdUi(call_log=call_log)
        buttons = _FakeButtons([_FakeEvent(0)])
        module.BUTTON_EVENT_DEBUG_ENABLED = False
        module._send_button_debug = lambda message: call_log.append(("debug", message))

        module._drain_button_events(
            buttons,
            lcd_ui,
            now=456.0,
        )

        self.assertEqual(lcd_ui.presses, [(0, 456.0)])
        self.assertEqual(call_log, [("lcd", 0, 456.0)])

    def test_record_uart_diag_appends_line_to_log_file(self):
        module = self._load_code_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "uart_diag.txt"
            module.UART_DIAG_LOG_PATH = str(log_path)

            module._record_uart_diag("event-1")
            module._record_uart_diag("event-2")

            self.assertEqual(log_path.read_text(encoding="utf-8"), "event-1\nevent-2\n")

    def test_configure_runtime_disables_autoreload(self):
        module = self._load_code_module()
        steps = []
        supervisor = types.SimpleNamespace(runtime=types.SimpleNamespace(autoreload=True))

        module._configure_runtime(supervisor, steps.append)

        self.assertFalse(supervisor.runtime.autoreload)
        self.assertEqual(steps, ["autoreload disabled"])

    def test_lcd_debug_checkpoint_targets_after_press_time(self):
        module = self._load_code_module()

        self.assertEqual(module.LCD_DEBUG_CHECKPOINT, "after_press_time")

    def test_runtime_defaults_keep_palette_updates_but_disable_highlight_group_mutation(self):
        module = self._load_code_module()

        self.assertTrue(module.LCD_SKIP_PALETTE_WRITE)
        self.assertFalse(module.LCD_SKIP_HIGHLIGHT_UPDATE)
        self.assertTrue(module.LCD_SKIP_HIGHLIGHT_CLEAR)

    def test_run_main_loop_iteration_records_post_step_checkpoints(self):
        module = self._load_code_module()
        call_log = []
        serial_bridge = _FakeSerialBridge(call_log)
        lcd_ui = _FakeLcdUi(call_log=call_log)
        jetson_transport = _FakeJetsonTransport(call_log)
        protocol_handler = object()
        custom_hid = object()
        buttons = object()
        sleeps = []

        module._send_button_debug = lambda message: call_log.append(("debug", message))
        module._drain_button_events = lambda buttons_arg, lcd_ui_arg, now: call_log.append(("buttons", now))
        module._sync_response_state = lambda protocol_handler_arg, transport_arg: call_log.append(("sync", None))
        module._drain_hid_reports = (
            lambda custom_hid_arg, protocol_handler_arg, raw_report_id: call_log.append(("hid", raw_report_id))
        )

        last_debug_heartbeat = module._run_main_loop_iteration(
            now=5.0,
            last_debug_heartbeat=0.0,
            serial_bridge=serial_bridge,
            buttons=buttons,
            lcd_ui=lcd_ui,
            jetson_transport=jetson_transport,
            protocol_handler=protocol_handler,
            custom_hid=custom_hid,
            raw_report_id=9,
            time_sleep=sleeps.append,
        )

        self.assertEqual(last_debug_heartbeat, 5.0)
        self.assertEqual(module._last_loop_checkpoint, "after_sleep")
        self.assertEqual(
            call_log,
            [
                ("debug", "heartbeat"),
                ("serial", module.CDC_RELAY_SLICE_BYTES),
                ("buttons", 5.0),
                ("transport", module.CDC_RELAY_SLICE_BYTES),
                ("sync", None),
                ("hid", 9),
                ("tick", 5.0),
            ],
        )
        self.assertEqual(sleeps, [module.BUTTON_POLL_SLEEP_S])

    def test_prepare_upload_result_includes_last_loop_checkpoint(self):
        module = self._load_code_module()
        module._last_cdc_debug_status = "heartbeat|sent:27"
        module._last_loop_checkpoint = "after_button_events"

        result = module._prepare_upload_result(
            1,
            "probe",
            AppCommand=types.SimpleNamespace(FEATURE_1=99),
            StatusCode=types.SimpleNamespace(INTERNAL_ERROR=9, BUSY=1),
        )

        self.assertEqual(
            result["response_text"],
            "PICO ECHO: probe\nCDC DEBUG: heartbeat|sent:27\nLOOP CHECKPOINT: after_button_events",
        )


if __name__ == "__main__":
    unittest.main()
