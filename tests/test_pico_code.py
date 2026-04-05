import builtins
import importlib.util
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock


class _FakeRuntimeRunnerModule:
    @staticmethod
    def run_with_diagnostics(callback, *, error_log_path, trace_log_path):
        return None


class _FakeSerialBridge:
    def __init__(self, call_log):
        self.call_log = call_log

    def relay_once(self, *, max_chunk_size):
        self.call_log.append(("serial", max_chunk_size))


class _FakeJetsonTransport:
    def __init__(self, call_log):
        self.call_log = call_log
        self.request_active = False
        self.response_len = 0
        self.response_complete = False
        self.response_bytes = b""

    def poll(self, *, max_chunk_size):
        self.call_log.append(("transport", max_chunk_size))


class _InitOnlyJetsonTransport:
    def __init__(self, uart, *, max_request_retries, debug_hook):
        self.uart = uart
        self.max_request_retries = max_request_retries
        self.debug_hook = debug_hook
        self.request_active = False
        self.response_len = 0
        self.response_complete = False
        self.response_bytes = b""

    def poll(self, *, max_chunk_size):
        return None


class _InitOnlySerialBridge:
    def __init__(self, cdc_data, uart):
        self.cdc_data = cdc_data
        self.uart = uart

    def relay_once(self, *, max_chunk_size):
        return 0


class _FakeUploadProtocolHandler:
    def __init__(self, text_preparer):
        self.text_preparer = text_preparer

    def handle_report(self, report):
        return None

    def update_response_state(self, response_bytes, *, complete, active):
        return None


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

    def test_runtime_module_no_longer_exports_lcd_flags(self):
        module = self._load_code_module()

        self.assertFalse(hasattr(module, "LCD_DEBUG_CHECKPOINT"))
        self.assertFalse(hasattr(module, "LCD_SKIP_PALETTE_WRITE"))
        self.assertFalse(hasattr(module, "LCD_SKIP_HIGHLIGHT_UPDATE"))
        self.assertFalse(hasattr(module, "LCD_SKIP_HIGHLIGHT_CLEAR"))

    def test_runtime_module_no_longer_exports_button_debug_toggle(self):
        module = self._load_code_module()

        self.assertFalse(hasattr(module, "BUTTON_EVENT_DEBUG_ENABLED"))

    def test_runtime_module_no_longer_exports_button_drain_helper(self):
        module = self._load_code_module()

        self.assertFalse(hasattr(module, "_drain_button_events"))

    def test_main_runtime_no_longer_imports_lcd_or_button_modules(self):
        module = self._load_code_module()
        steps = []
        stop_error = RuntimeError("stop after setup")

        fake_time = types.SimpleNamespace(monotonic=mock.Mock(side_effect=stop_error), sleep=lambda _: None)
        fake_board = types.SimpleNamespace(GP0=object(), GP1=object())
        fake_busio = types.SimpleNamespace(UART=lambda *args, **kwargs: object())
        fake_supervisor = types.SimpleNamespace(runtime=types.SimpleNamespace(autoreload=True))
        fake_usb_cdc = types.SimpleNamespace(data=object())
        fake_hid_device = types.SimpleNamespace(usage_page=0xFF60, usage=0x61)
        fake_usb_hid = types.SimpleNamespace(devices=[fake_hid_device])

        fake_jetson_transport_module = types.SimpleNamespace(JetsonTransport=_InitOnlyJetsonTransport)
        fake_serial_bridge_module = types.SimpleNamespace(SerialBridge=_InitOnlySerialBridge)
        fake_upload_protocol_module = types.SimpleNamespace(
            AppCommand=types.SimpleNamespace(FEATURE_1=99),
            StatusCode=types.SimpleNamespace(INTERNAL_ERROR=9, BUSY=1),
            UploadProtocolHandler=_FakeUploadProtocolHandler,
        )
        fake_usb_config_module = types.SimpleNamespace(RAW_REPORT_ID=9, RAW_USAGE_ID=0x61, RAW_USAGE_PAGE=0xFF60)

        import_overrides = {
            "time": fake_time,
            "board": fake_board,
            "busio": fake_busio,
            "supervisor": fake_supervisor,
            "usb_cdc": fake_usb_cdc,
            "usb_hid": fake_usb_hid,
            "pico.jetson_transport": fake_jetson_transport_module,
            "pico.serial_bridge": fake_serial_bridge_module,
            "pico.upload_protocol": fake_upload_protocol_module,
            "pico.usb_config": fake_usb_config_module,
        }
        blocked_imports = {"keypad", "pico.lcd_ui", "lcd_ui", "pico.pin_config", "pin_config"}
        original_import = builtins.__import__

        def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in blocked_imports:
                raise AssertionError(f"unexpected import: {name}")
            if name in import_overrides:
                return import_overrides[name]
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=tracking_import):
            with self.assertRaisesRegex(RuntimeError, "stop after setup"):
                module._main(steps.append)

        self.assertIn("core imports ready", steps)
        self.assertIn("spark modules ready", steps)
        self.assertIn("transport ready", steps)

    def test_run_main_loop_iteration_records_post_step_checkpoints(self):
        module = self._load_code_module()
        call_log = []
        serial_bridge = _FakeSerialBridge(call_log)
        jetson_transport = _FakeJetsonTransport(call_log)
        protocol_handler = object()
        custom_hid = object()
        sleeps = []

        module._send_button_debug = lambda message: call_log.append(("debug", message))
        module._sync_response_state = lambda protocol_handler_arg, transport_arg: call_log.append(("sync", None))
        module._drain_hid_reports = (
            lambda custom_hid_arg, protocol_handler_arg, raw_report_id: call_log.append(("hid", raw_report_id))
        )

        last_debug_heartbeat = module._run_main_loop_iteration(
            now=5.0,
            last_debug_heartbeat=0.0,
            serial_bridge=serial_bridge,
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
                ("transport", module.CDC_RELAY_SLICE_BYTES),
                ("sync", None),
                ("hid", 9),
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
