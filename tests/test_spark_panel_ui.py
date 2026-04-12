import types
import unittest
from unittest import mock

try:
    from PyQt6.QtWidgets import QApplication, QLabel, QTextEdit
except ImportError:  # pragma: no cover - environment-dependent test guard
    QApplication = None
    QLabel = None
    QTextEdit = None
    spark_app_v2 = None
else:
    import spark_app_v2


class _DummyHotkeys:
    def start(self):
        return None

    def stop(self):
        return None


class _DummySerialSender:
    def __init__(self):
        self.connect_calls = 0
        self.packet_callback = None

    def connect(self):
        self.connect_calls += 1
        return None

    def close(self):
        return None

    def is_connected(self):
        return False

    def set_packet_callback(self, callback):
        self.packet_callback = callback


@unittest.skipUnless(QApplication is not None, "PyQt6 is not installed")
class SparkPanelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_panel(self, *, hid_client=None):
        hid_client = hid_client or mock.Mock()

        patches = (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=hid_client),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=_DummySerialSender()),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
        )

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            return spark_app_v2.SparkPanel()

    def test_release_output_uses_fixed_height_scrollable_text_widget(self):
        panel = self._make_panel()

        self.assertIsInstance(panel.release_output_lbl, QTextEdit)
        self.assertTrue(panel.release_output_lbl.isReadOnly())
        self.assertEqual(panel.release_output_lbl.toPlainText(), "No released text yet…")

    def test_summarize_sends_lightweight_command(self):
        """_on_summarize sends a lightweight DB-backed command, no window scraping."""
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True

        panel = self._make_panel(hid_client=hid_client)
        panel._start_summary_request = mock.Mock()
        panel._on_summarize()

        panel._start_summary_request.assert_called_once()
        kwargs = panel._start_summary_request.call_args.kwargs
        self.assertIn("summarize", kwargs["request"])
        self.assertNotIn("window_text", kwargs["request"])

    def test_unsolicited_device_response_updates_release_output(self):
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True
        info = types.SimpleNamespace(total_len=14, complete=False, active=True)
        hid_client.get_response_info.return_value = info
        hid_client.fetch_response.return_value = "Partial output"

        panel = self._make_panel(hid_client=hid_client)

        panel._poll_device_response()

        hid_client.fetch_response.assert_called_once_with(info)
        self.assertEqual(panel.release_output_lbl.toPlainText(), "Partial output")
        self.assertEqual(panel.status_lbl.text(), "Streaming summary from Jetson…")

    def test_response_poll_timer_starts_idle(self):
        panel = self._make_panel()

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_button_zero_debug_message_starts_response_polling(self):
        panel = self._make_panel()

        panel._on_pico_debug_message("button:0")

        self.assertTrue(panel._response_poll_timer.isActive())

    def test_heartbeat_debug_message_does_not_start_response_polling(self):
        panel = self._make_panel()

        panel._on_pico_debug_message("heartbeat")

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_hid_runtime_status_button_message_starts_response_polling(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=True,
            complete=False,
            text="button:0|after_button_events",
        )

        panel = self._make_panel(hid_client=hid_client)

        panel._poll_pico_runtime_status()

        self.assertTrue(panel._response_poll_timer.isActive())

    def test_hid_runtime_status_heartbeat_does_not_emit_duplicate_debug(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=False,
            complete=False,
            text="heartbeat|after_sleep",
        )

        panel = self._make_panel(hid_client=hid_client)
        received = []
        panel.hid_signals.pico_debug.connect(received.append)

        panel._poll_pico_runtime_status()
        panel._poll_pico_runtime_status()

        self.assertEqual(received, ["heartbeat"])

    def test_unsolicited_device_response_skips_while_host_summary_in_flight(self):
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True

        panel = self._make_panel(hid_client=hid_client)
        panel._summary_request_in_flight = True

        panel._poll_device_response()

        hid_client.get_response_info.assert_not_called()

    def test_toggle_polling_logs_start_and_stop(self):
        panel = self._make_panel()

        with (
            mock.patch.object(panel, "_on_poll_tick", return_value=None),
            mock.patch.object(spark_app_v2.logger, "info") as log_info,
        ):
            panel._on_toggle_polling()
            panel._on_toggle_polling()

        log_info.assert_any_call("[POLL] Started live context polling")
        log_info.assert_any_call("[POLL] Stopped live context polling")

    def test_serial_reconnect_poll_retries_when_disconnected(self):
        serial_sender = _DummySerialSender()

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
        ):
            panel = spark_app_v2.SparkPanel()

        serial_sender.is_connected = mock.Mock(return_value=False)

        panel._poll_serial_connection()

        self.assertGreaterEqual(serial_sender.connect_calls, 2)

    def test_poll_tick_does_not_send_context_update_when_text_is_unchanged(self):
        info = mock.Mock(app_name="Cursor", pid=123, bundle_id="cursor", title="Editor", process_name="cursor.exe")
        snapshot = types.SimpleNamespace(
            context_key="Cursor|Editor",
            text="same text",
            url=None,
            window_info=types.SimpleNamespace(
                app_name="Cursor",
                title="Editor",
            ),
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        manager.get_focused_element_text.return_value = "same text"
        manager.get_window_text.return_value = None

        tracker = mock.Mock()
        tracker.get_current.return_value = snapshot
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
        ):
            panel = spark_app_v2.SparkPanel()
            panel._on_poll_tick()
            panel._on_poll_tick()

            serial_sender.send_context_new.assert_called_once_with(snapshot)
            serial_sender.send_context_update.assert_not_called()

    def test_close_button_quits_app_instead_of_hiding_panel(self):
        panel = self._make_panel()
        close_button = panel.findChild(QLabel, "close_btn")

        with (
            mock.patch.object(self.app, "quit") as quit_app,
            mock.patch.object(panel, "hide") as hide,
        ):
            close_button.mousePressEvent(None)

        quit_app.assert_called_once_with()
        hide.assert_not_called()


if __name__ == "__main__":
    unittest.main()
