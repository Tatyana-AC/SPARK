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


class _FakeButtonInput:
    def __init__(self, events=()):
        self._events = tuple(events)

    def drain_pressed_events(self):
        return iter(self._events)


class _FakeBridgeRuntime:
    instances = []

    def __init__(
        self,
        *,
        serial_bridge,
        jetson_transport,
        protocol_handler,
        custom_hid,
        raw_report_id,
        button_input,
        debug_sender,
        time_sleep,
        ui=None,
        relay_chunk_size=64,
        button_poll_sleep_s=0.002,
        heartbeat_interval_s=2.0,
    ):
        self.serial_bridge = serial_bridge
        self.jetson_transport = jetson_transport
        self.protocol_handler = protocol_handler
        self.custom_hid = custom_hid
        self.raw_report_id = raw_report_id
        self.button_input = button_input
        self.debug_sender = debug_sender
        self.time_sleep = time_sleep
        self.ui = ui
        self.relay_chunk_size = relay_chunk_size
        self.button_poll_sleep_s = button_poll_sleep_s
        self.heartbeat_interval_s = heartbeat_interval_s
        self.current_status = mock.Mock(
            return_value=types.SimpleNamespace(
                cdc_debug_status="never",
                loop_checkpoint="startup",
                request_active=False,
                response_length=0,
                response_complete=False,
            )
        )
        self.run_forever_calls = []
        self.__class__.instances.append(self)

    def run_forever(self, *, time_module):
        self.run_forever_calls.append(time_module)
        raise RuntimeError("stop after runtime start")


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

    def test_runtime_module_no_longer_exports_task_3_or_4_helpers(self):
        module = self._load_code_module()

        self.assertFalse(hasattr(module, "AUTO_VISUAL_PROBE_DELAY_S"))
        self.assertFalse(hasattr(module, "_drain_button_events"))
        self.assertFalse(hasattr(module, "_run_main_loop_iteration"))
        self.assertFalse(hasattr(module, "_current_runtime_status"))
        self.assertFalse(hasattr(module, "_initialize_lcd_ui"))
        self.assertFalse(hasattr(module, "_board_pin"))

    def test_main_runtime_builds_button_input_without_importing_raw_keypad_details(self):
        module = self._load_code_module()
        _FakeBridgeRuntime.instances = []
        steps = []
        build_button_input_calls = []
        button_input = object()
        fake_ui = object()
        lcd_ui_calls = []

        fake_time = types.SimpleNamespace(monotonic=mock.Mock(return_value=1.0), sleep=lambda _: None)
        fake_board = types.SimpleNamespace(GP0=object(), GP1=object())
        fake_busio = types.SimpleNamespace(UART=lambda *args, **kwargs: object())
        fake_supervisor = types.SimpleNamespace(runtime=types.SimpleNamespace(autoreload=True))
        fake_usb_cdc = types.SimpleNamespace(data=object())
        fake_hid_device = types.SimpleNamespace(usage_page=0xFF60, usage=0x61)
        fake_usb_hid = types.SimpleNamespace(devices=[fake_hid_device])

        fake_jetson_transport_module = types.SimpleNamespace(JetsonTransport=_InitOnlyJetsonTransport)
        fake_serial_bridge_module = types.SimpleNamespace(SerialBridge=_InitOnlySerialBridge)
        fake_upload_protocol_module = types.SimpleNamespace(UploadProtocolHandler=_FakeUploadProtocolHandler)
        fake_usb_config_module = types.SimpleNamespace(RAW_REPORT_ID=9, RAW_USAGE_ID=0x61, RAW_USAGE_PAGE=0xFF60)
        fake_bridge_app_module = types.SimpleNamespace(build_text_preparer=lambda **kwargs: lambda *_: None)
        fake_bridge_runtime_module = types.SimpleNamespace(BridgeRuntime=_FakeBridgeRuntime)
        fake_button_input_module = types.SimpleNamespace(
            build_button_input=lambda: build_button_input_calls.append("called") or button_input
        )
        fake_lcd_ui_module = types.SimpleNamespace(
            initialize_lcd_ui=lambda *, mode="standalone": lcd_ui_calls.append(mode) or fake_ui
        )

        import_overrides = {
            "time": fake_time,
            "board": fake_board,
            "busio": fake_busio,
            "supervisor": fake_supervisor,
            "usb_cdc": fake_usb_cdc,
            "usb_hid": fake_usb_hid,
            "pico.bridge_app": fake_bridge_app_module,
            "pico.jetson_transport": fake_jetson_transport_module,
            "pico.serial_bridge": fake_serial_bridge_module,
            "pico.upload_protocol": fake_upload_protocol_module,
            "pico.usb_config": fake_usb_config_module,
            "pico.bridge_runtime": fake_bridge_runtime_module,
            "pico.button_input": fake_button_input_module,
            "pico.lcd_ui": fake_lcd_ui_module,
        }
        blocked_imports = {"keypad"}
        original_import = builtins.__import__

        def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in blocked_imports:
                raise AssertionError(f"unexpected import: {name}")
            if name in import_overrides:
                return import_overrides[name]
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=tracking_import):
            with self.assertRaisesRegex(RuntimeError, "stop after runtime start"):
                module._main(steps.append)

        self.assertIn("core imports ready", steps)
        self.assertIn("spark modules ready", steps)
        self.assertIn("transport ready", steps)
        self.assertIn("protocol handler ready", steps)
        self.assertIn("lcd ui ready", steps)
        self.assertIn("button input ready", steps)
        self.assertIn("bridge runtime ready", steps)
        self.assertLess(steps.index("protocol handler ready"), steps.index("lcd ui ready"))
        self.assertLess(steps.index("lcd ui ready"), steps.index("button input ready"))
        self.assertEqual(build_button_input_calls, ["called"])
        self.assertEqual(lcd_ui_calls, ["bridge"])
        self.assertEqual(len(_FakeBridgeRuntime.instances), 1)
        runtime = _FakeBridgeRuntime.instances[0]
        self.assertIs(runtime.button_input, button_input)
        self.assertIs(runtime.ui, fake_ui)
        self.assertEqual(runtime.raw_report_id, 9)
        self.assertIs(runtime.time_sleep, fake_time.sleep)
        self.assertEqual(runtime.run_forever_calls, [fake_time])

    def test_main_runtime_builds_text_preparer_from_bridge_app(self):
        module = self._load_code_module()
        _FakeBridgeRuntime.instances = []
        steps = []
        bridge_app_calls = []
        handler_preparers = []

        fake_time = types.SimpleNamespace(monotonic=mock.Mock(return_value=1.0), sleep=lambda _: None)
        fake_board = types.SimpleNamespace(GP0=object(), GP1=object())
        fake_busio = types.SimpleNamespace(UART=lambda *args, **kwargs: object())
        fake_supervisor = types.SimpleNamespace(runtime=types.SimpleNamespace(autoreload=True))
        fake_usb_cdc = types.SimpleNamespace(data=object())
        fake_hid_device = types.SimpleNamespace(usage_page=0xFF60, usage=0x61)
        fake_usb_hid = types.SimpleNamespace(devices=[fake_hid_device])

        fake_jetson_transport_module = types.SimpleNamespace(JetsonTransport=_InitOnlyJetsonTransport)
        fake_serial_bridge_module = types.SimpleNamespace(SerialBridge=_InitOnlySerialBridge)
        fake_button_input_module = types.SimpleNamespace(build_button_input=lambda: object())
        fake_bridge_runtime_module = types.SimpleNamespace(BridgeRuntime=_FakeBridgeRuntime)
        fake_lcd_ui_module = types.SimpleNamespace(initialize_lcd_ui=lambda *, mode="standalone": object())

        class _CapturingUploadProtocolHandler:
            def __init__(self, text_preparer):
                handler_preparers.append(text_preparer)

            def handle_report(self, report):
                return None

            def update_response_state(self, response_bytes, *, complete, active):
                return None

        fake_upload_protocol_module = types.SimpleNamespace(UploadProtocolHandler=_CapturingUploadProtocolHandler)
        fake_usb_config_module = types.SimpleNamespace(RAW_REPORT_ID=9, RAW_USAGE_ID=0x61, RAW_USAGE_PAGE=0xFF60)
        fake_bridge_app_module = types.SimpleNamespace(
            build_text_preparer=lambda *, jetson_transport, runtime_status: bridge_app_calls.append(
                {"jetson_transport": jetson_transport, "runtime_status": runtime_status}
            )
            or "bridge-preparer"
        )

        import_overrides = {
            "time": fake_time,
            "board": fake_board,
            "busio": fake_busio,
            "supervisor": fake_supervisor,
            "usb_cdc": fake_usb_cdc,
            "usb_hid": fake_usb_hid,
            "pico.bridge_app": fake_bridge_app_module,
            "pico.jetson_transport": fake_jetson_transport_module,
            "pico.serial_bridge": fake_serial_bridge_module,
            "pico.upload_protocol": fake_upload_protocol_module,
            "pico.usb_config": fake_usb_config_module,
            "pico.bridge_runtime": fake_bridge_runtime_module,
            "pico.button_input": fake_button_input_module,
            "pico.lcd_ui": fake_lcd_ui_module,
        }
        blocked_imports = {"keypad"}
        original_import = builtins.__import__

        def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in blocked_imports:
                raise AssertionError(f"unexpected import: {name}")
            if name in import_overrides:
                return import_overrides[name]
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=tracking_import):
            with self.assertRaisesRegex(RuntimeError, "stop after runtime start"):
                module._main(steps.append)

        self.assertEqual(handler_preparers, ["bridge-preparer"])
        self.assertEqual(len(bridge_app_calls), 1)
        self.assertIsInstance(bridge_app_calls[0]["jetson_transport"], _InitOnlyJetsonTransport)
        status = bridge_app_calls[0]["runtime_status"]()
        self.assertEqual(status.cdc_debug_status, "never")
        self.assertEqual(status.loop_checkpoint, "startup")
        self.assertFalse(status.request_active)
        self.assertEqual(status.response_length, 0)
        self.assertFalse(status.response_complete)

    def test_main_runtime_initializes_bridge_mode_lcd_ui_and_passes_it_to_runtime(self):
        module = self._load_code_module()
        _FakeBridgeRuntime.instances = []
        steps = []
        fake_ui = object()
        lcd_ui_calls = []

        fake_time = types.SimpleNamespace(monotonic=mock.Mock(return_value=1.0), sleep=lambda _: None)
        fake_board = types.SimpleNamespace(GP0=object(), GP1=object())
        fake_busio = types.SimpleNamespace(UART=lambda *args, **kwargs: object())
        fake_supervisor = types.SimpleNamespace(runtime=types.SimpleNamespace(autoreload=True))
        fake_usb_cdc = types.SimpleNamespace(data=object())
        fake_hid_device = types.SimpleNamespace(usage_page=0xFF60, usage=0x61)
        fake_usb_hid = types.SimpleNamespace(devices=[fake_hid_device])

        fake_jetson_transport_module = types.SimpleNamespace(JetsonTransport=_InitOnlyJetsonTransport)
        fake_serial_bridge_module = types.SimpleNamespace(SerialBridge=_InitOnlySerialBridge)
        fake_upload_protocol_module = types.SimpleNamespace(UploadProtocolHandler=_FakeUploadProtocolHandler)
        fake_usb_config_module = types.SimpleNamespace(RAW_REPORT_ID=9, RAW_USAGE_ID=0x61, RAW_USAGE_PAGE=0xFF60)
        fake_bridge_app_module = types.SimpleNamespace(build_text_preparer=lambda **kwargs: lambda *_: None)
        fake_bridge_runtime_module = types.SimpleNamespace(BridgeRuntime=_FakeBridgeRuntime)
        fake_button_input_module = types.SimpleNamespace(build_button_input=lambda: object())
        fake_lcd_ui_module = types.SimpleNamespace(
            initialize_lcd_ui=lambda *, mode="standalone": lcd_ui_calls.append(mode) or fake_ui
        )

        import_overrides = {
            "time": fake_time,
            "board": fake_board,
            "busio": fake_busio,
            "supervisor": fake_supervisor,
            "usb_cdc": fake_usb_cdc,
            "usb_hid": fake_usb_hid,
            "pico.bridge_app": fake_bridge_app_module,
            "pico.jetson_transport": fake_jetson_transport_module,
            "pico.serial_bridge": fake_serial_bridge_module,
            "pico.upload_protocol": fake_upload_protocol_module,
            "pico.usb_config": fake_usb_config_module,
            "pico.bridge_runtime": fake_bridge_runtime_module,
            "pico.button_input": fake_button_input_module,
            "pico.lcd_ui": fake_lcd_ui_module,
        }
        original_import = builtins.__import__

        def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in import_overrides:
                return import_overrides[name]
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=tracking_import):
            with self.assertRaisesRegex(RuntimeError, "stop after runtime start"):
                module._main(steps.append)

        self.assertEqual(lcd_ui_calls, ["bridge"])
        self.assertEqual(len(_FakeBridgeRuntime.instances), 1)
        self.assertIs(_FakeBridgeRuntime.instances[0].ui, fake_ui)


if __name__ == "__main__":
    unittest.main()
