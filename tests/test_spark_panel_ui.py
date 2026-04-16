import types
import unittest
from unittest import mock

try:
    from PyQt6.QtWidgets import QApplication, QLabel, QTextEdit, QPushButton
except ImportError:  # pragma: no cover - environment-dependent test guard
    QApplication = None
    QLabel = None
    QTextEdit = None
    QPushButton = None
    spark_app_v2 = None
else:
    import spark_app_v2
    from host_pc.web_content import BrowserExtractionResult


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

    def test_reformat_button_is_visible(self):
        panel = self._make_panel()

        btn_candidates = [
            btn for btn in panel.findChildren(QPushButton)
            if btn.property("test_id") == "btn_reformat"
        ]
        self.assertEqual(len(btn_candidates), 1)
        btn_reformat = btn_candidates[0]
        self.assertIsNotNone(btn_reformat)
        self.assertTrue(btn_reformat.isEnabled())

    def test_action_grid_hides_legacy_buttons_without_resizing_panel(self):
        panel = self._make_panel()

        self.assertEqual(panel.width(), 1500)

        visible_titles = sorted(
            btn._title_lbl.text()
            for btn in panel.findChildren(spark_app_v2.ActionButton)
            if not btn.isHidden()
        )

        self.assertEqual(
            visible_titles,
            [
                "Custom Context",
                "Reformat Selection",
                "Test Context",
                "View Jetson DB",
            ],
        )

        self.assertTrue(panel.btn_capture.isHidden())
        self.assertTrue(panel.btn_release.isHidden())
        self.assertTrue(panel.btn_summarize.isHidden())
        self.assertTrue(panel.btn_history.isHidden())

    def test_view_jetson_db_button_opens_dialog(self):
        panel = self._make_panel()

        with mock.patch.object(spark_app_v2, "JetsonDbViewerDialog") as dialog_cls:
            dialog = mock.Mock()
            dialog_cls.return_value = dialog

            panel.btn_view_jetson_db.click()

        dialog_cls.assert_called_once_with(panel)
        dialog.exec.assert_called_once()

    def test_reformat_blocked_when_selection_from_private_window(self):
        manager = mock.Mock()
        manager.get_active_window_info.return_value = types.SimpleNamespace(
            bundle_id="com.private.app",
            title="Private App",
        )
        panel = self._make_panel()
        panel.manager = manager

        panel._set_status = mock.Mock()

        with (
            mock.patch.object(spark_app_v2, "build_reformat_request") as build_reformat,
            mock.patch.object(panel, "_start_feature_request") as start_feature_request,
        ):
            panel._on_reformat()

        panel._set_status.assert_called_once_with(
            "Cannot reformat: Sensitive window detected",
            spark_app_v2.RED,
        )
        build_reformat.assert_not_called()
        start_feature_request.assert_not_called()

    def test_reformat_does_not_launch_when_device_disconnected(self):
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = False
        manager = mock.Mock()
        manager.get_active_window_info.return_value = types.SimpleNamespace(
            bundle_id="com.test.app",
            title="Editor",
        )
        manager.get_selected_text.return_value = "selected text"

        panel = self._make_panel(hid_client=hid_client)
        panel.manager = manager

        panel._set_status = mock.Mock()

        with mock.patch("spark_app_v2.threading.Thread") as thread_cls:
            panel._on_reformat()

        thread_cls.assert_not_called()
        panel._set_status.assert_called_once_with("SPARK device not connected", spark_app_v2.RED)

    def test_reformat_inlines_current_selection_without_capture(self):
        manager = mock.Mock()
        manager.get_active_window_info.return_value = types.SimpleNamespace(bundle_id="com.test.app", title="Editor")

        panel = self._make_panel()
        panel.manager = manager
        panel.processed_text = "old captured text"
        panel.manager.get_selected_text.return_value = "  inline selected text  "

        with (
            mock.patch.object(spark_app_v2, "build_reformat_request") as build_reformat,
            mock.patch.object(panel, "_start_feature_request") as start_feature_request,
        ):
            build_reformat.return_value = "REFORMAT_REQUEST"
            panel._on_reformat()

        build_reformat.assert_called_once_with("  inline selected text  ")
        start_feature_request.assert_called_once()
        call_args = start_feature_request.call_args
        args, kwargs = call_args
        self.assertEqual(kwargs.get("app_command", args[0]), spark_app_v2.AppCommand.FEATURE_2)
        request = kwargs.get("request", args[1] if len(args) > 1 else None)
        self.assertEqual(request, "REFORMAT_REQUEST")

    def test_reformat_fails_fast_when_selection_is_empty(self):
        manager = mock.Mock()
        manager.get_active_window_info.return_value = types.SimpleNamespace(bundle_id="com.test.app", title="Editor")

        panel = self._make_panel()
        panel.manager = manager
        panel.manager.get_selected_text.return_value = "   "

        panel._set_status = mock.Mock()

        with (
            mock.patch.object(spark_app_v2, "build_reformat_request") as build_reformat,
            mock.patch.object(panel, "_start_feature_request") as start_feature_request,
        ):
            panel._on_reformat()
            build_reformat.assert_not_called()

        start_feature_request.assert_not_called()
        panel._set_status.assert_called_once_with("No text selected — highlight text first", spark_app_v2.RED)

    def test_start_feature_request_uses_feature_2_round_trip(self):
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True

        panel = self._make_panel(hid_client=hid_client)

        def immediate_thread(*args, **kwargs):
            if args:
                target = args[0]
                thread_args = args[1] if len(args) > 1 else tuple()
            else:
                target = kwargs["target"]
                thread_args = kwargs.get("args", tuple())
            t = mock.Mock()
            t.start.side_effect = lambda: target(*thread_args)
            return t

        with (
            mock.patch("spark_app_v2.threading.Thread", mock.Mock(side_effect=immediate_thread)) as thread_cls,
            mock.patch.object(hid_client, "stream_round_trip_text", return_value="refactored") as stream_round_trip,
        ):
            panel._start_feature_request(
                app_command=spark_app_v2.AppCommand.FEATURE_2,
                request="request-payload",
                capture_label="[REFORMAT] selection",
                status_text="Sending reformat selection request",
            )

        thread_cls.assert_called_once()
        stream_round_trip.assert_called_once()
        args, kwargs = stream_round_trip.call_args
        self.assertEqual(args[0], spark_app_v2.AppCommand.FEATURE_2)
        self.assertEqual(args[1], "request-payload")
        self.assertIn("on_update", kwargs)

    def test_start_feature_request_preserves_existing_release_output(self):
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True

        panel = self._make_panel(hid_client=hid_client)
        panel.release_output_lbl.setPlainText("existing output")

        def immediate_thread(*args, **kwargs):
            if args:
                target = args[0]
                thread_args = args[1] if len(args) > 1 else tuple()
            else:
                target = kwargs["target"]
                thread_args = kwargs.get("args", tuple())
            t = mock.Mock()
            t.start.side_effect = lambda: target(*thread_args)
            return t

        with (
            mock.patch("spark_app_v2.threading.Thread", mock.Mock(side_effect=immediate_thread)),
            mock.patch.object(hid_client, "stream_round_trip_text", return_value="refactored"),
        ):
            panel._start_feature_request(
                app_command=spark_app_v2.AppCommand.FEATURE_2,
                request="request-payload",
                capture_label="[REFORMAT] selection",
                status_text="Sending reformat selection request",
            )

        self.assertEqual(panel.release_output_lbl.toPlainText(), "existing output")

    def test_reformat_success_does_not_mutate_processed_text(self):
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True

        panel = self._make_panel(hid_client=hid_client)
        panel.processed_text = "already captured"

        manager = mock.Mock()
        manager.get_active_window_info.return_value = types.SimpleNamespace(bundle_id="com.test.app", title="Editor")
        manager.get_selected_text.return_value = "selection for reformat"
        panel.manager = manager

        def immediate_thread(*args, **kwargs):
            if args:
                target = args[0]
                thread_args = args[1] if len(args) > 1 else tuple()
            else:
                target = kwargs["target"]
                thread_args = kwargs.get("args", tuple())
            return mock.Mock(start=lambda: target(*thread_args))

        with (
            mock.patch("spark_app_v2.threading.Thread", immediate_thread),
            mock.patch.object(
                panel,
                "_set_status",
                wraps=panel._set_status,
            ),
        ):
            panel._on_reformat()
        
        self.assertEqual(panel.processed_text, "already captured")

    def test_reformat_completion_status_text_is_feature_specific(self):
        panel = self._make_panel()
        panel._active_feature_command = spark_app_v2.AppCommand.FEATURE_2
        panel._set_status = mock.Mock()

        panel._on_summarize_succeeded("reformatted text")

        panel._set_status.assert_called_once_with("Jetson reformat complete — output updated", spark_app_v2.GREEN)
        self.assertEqual(panel.release_output_lbl.toPlainText(), "reformatted text")

    def test_reformat_completion_copies_final_text_to_clipboard(self):
        panel = self._make_panel()
        panel._active_feature_command = spark_app_v2.AppCommand.FEATURE_2
        panel._set_status = mock.Mock()
        clipboard = mock.Mock()

        with mock.patch.object(spark_app_v2.QApplication, "clipboard", return_value=clipboard):
            panel._on_summarize_succeeded("reformatted text")

        clipboard.setText.assert_called_once_with("reformatted text")

    def test_summary_completion_does_not_copy_text_to_clipboard(self):
        panel = self._make_panel()
        panel._active_feature_command = spark_app_v2.AppCommand.FEATURE_1
        panel._set_status = mock.Mock()
        clipboard = mock.Mock()

        with mock.patch.object(spark_app_v2.QApplication, "clipboard", return_value=clipboard):
            panel._on_summarize_succeeded("summary text")

        clipboard.setText.assert_not_called()

    def test_reformat_streaming_status_text_is_feature_specific(self):
        panel = self._make_panel()
        panel._active_feature_command = spark_app_v2.AppCommand.FEATURE_2
        panel._set_status = mock.Mock()
        clipboard = mock.Mock()

        with mock.patch.object(spark_app_v2.QApplication, "clipboard", return_value=clipboard):
            panel._on_summarize_progress("partial chunk")

        panel._set_status.assert_called_once_with("Streaming reformat from Jetson…", spark_app_v2.ORANGE)
        self.assertEqual(panel.release_output_lbl.toPlainText(), "partial chunk")
        clipboard.setText.assert_not_called()

    def test_finished_feature_request_drains_stale_hid_debug_events(self):
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True
        hid_client.get_debug_event.side_effect = [
            "button:2",
            "pre_press:2",
            "post_press:2",
            None,
        ]

        panel = self._make_panel(hid_client=hid_client)
        panel._summary_request_in_flight = True

        panel._on_summarize_finished()

        self.assertEqual(hid_client.get_debug_event.call_count, 4)

    def test_summarize_sends_lightweight_command(self):
        """_on_summarize sends a lightweight DB-backed command, no window scraping."""
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True

        panel = self._make_panel(hid_client=hid_client)
        panel._start_feature_request = mock.Mock()
        panel._on_summarize()

        panel._start_feature_request.assert_called_once()
        args, kwargs = panel._start_feature_request.call_args
        request = kwargs.get("request", args[1] if len(args) > 1 else None)
        app_command = kwargs.get("app_command", args[0])
        self.assertIn("summarize", request)
        self.assertNotIn("window_text", request)
        self.assertEqual(app_command, spark_app_v2.AppCommand.FEATURE_1)

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

    def test_button_one_debug_message_starts_response_polling(self):
        panel = self._make_panel()

        panel._on_pico_debug_message("button:1")

        self.assertTrue(panel._response_poll_timer.isActive())

    def test_button_two_edge_debug_message_does_not_trigger_reformat(self):
        panel = self._make_panel()

        with mock.patch.object(panel, "_on_reformat") as on_reformat:
            panel._on_pico_debug_message("button:2")

        on_reformat.assert_not_called()

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_button_two_post_press_triggers_reformat_without_starting_response_polling(self):
        panel = self._make_panel()

        with mock.patch.object(panel, "_on_reformat") as on_reformat:
            panel._on_pico_debug_message("post_press:2")

        on_reformat.assert_called_once_with()

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_button_two_post_press_is_ignored_while_request_in_flight(self):
        panel = self._make_panel()
        panel._summary_request_in_flight = True

        with mock.patch.object(panel, "_on_reformat") as on_reformat:
            panel._on_pico_debug_message("post_press:2")

        on_reformat.assert_not_called()

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_button_two_post_press_is_debounced(self):
        panel = self._make_panel()

        with (
            mock.patch.object(panel, "_on_reformat") as on_reformat,
            mock.patch.object(spark_app_v2.time, "monotonic", side_effect=[10.0, 10.2]),
        ):
            panel._on_pico_debug_message("post_press:2")
            panel._on_pico_debug_message("post_press:2")

        on_reformat.assert_called_once_with()

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_buttons_three_and_four_do_not_start_response_polling(self):
        panel = self._make_panel()

        panel._on_pico_debug_message("button:3")
        self.assertFalse(panel._response_poll_timer.isActive())
        panel._on_pico_debug_message("button:4")

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_heartbeat_debug_message_does_not_start_response_polling(self):
        panel = self._make_panel()

        panel._on_pico_debug_message("heartbeat")

        self.assertFalse(panel._response_poll_timer.isActive())

    def test_hid_runtime_status_button_message_starts_response_polling(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=True,
            complete=False,
            text="button:1|after_button_events",
        )

        panel = self._make_panel(hid_client=hid_client)

        panel._poll_pico_runtime_status()

        self.assertTrue(panel._response_poll_timer.isActive())

    def test_hid_runtime_status_complete_does_not_retrigger_same_response_state(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=False,
            complete=True,
            text="heartbeat|after_response_sync",
        )
        hid_client.get_debug_event.return_value = None

        panel = self._make_panel(hid_client=hid_client)

        with mock.patch.object(panel, "_start_device_response_polling") as start_poll:
            panel._poll_pico_runtime_status()
            panel._poll_pico_runtime_status()

        start_poll.assert_called_once_with()

    def test_runtime_status_poll_is_skipped_while_device_response_polling_is_active(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=False,
            complete=False,
            text="heartbeat|after_sleep",
        )

        panel = self._make_panel(hid_client=hid_client)
        panel._response_poll_timer.start()

        panel._poll_pico_runtime_status()

        hid_client.get_runtime_status.assert_not_called()

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

    def test_hid_runtime_status_logs_pico_debug_message(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=False,
            complete=False,
            text="button:2|after_button_events",
        )
        hid_client.get_debug_event.side_effect = ["button:2", None]

        panel = self._make_panel(hid_client=hid_client)

        with mock.patch.object(spark_app_v2.logging.getLogger("pico.debug"), "info") as log_info:
            panel._poll_pico_runtime_status()

        log_info.assert_called_once_with("[PICO] %s", "button:2")

    def test_hid_runtime_status_logs_heartbeat_again_after_interval(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=False,
            complete=False,
            text="heartbeat|after_sleep",
        )
        hid_client.get_debug_event.side_effect = ["heartbeat", None, "heartbeat", None]

        panel = self._make_panel(hid_client=hid_client)

        with (
            mock.patch.object(spark_app_v2.logging.getLogger("pico.debug"), "info") as log_info,
            mock.patch.object(spark_app_v2.time, "monotonic", side_effect=[0.0, 5.1]),
        ):
            panel._poll_pico_runtime_status()
            panel._poll_pico_runtime_status()

        self.assertEqual(log_info.call_args_list, [mock.call("[PICO] %s", "heartbeat"), mock.call("[PICO] %s", "heartbeat")])

    def test_hid_runtime_status_drains_multiple_debug_events_in_order(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=False,
            complete=False,
            text="pre:2|ui_post",
        )
        hid_client.get_debug_event.side_effect = ["button:2", "pre_press:2", "draw_press:2", None]

        panel = self._make_panel(hid_client=hid_client)

        with mock.patch.object(spark_app_v2.logging.getLogger("pico.debug"), "info") as log_info:
            panel._poll_pico_runtime_status()

        self.assertEqual(
            log_info.call_args_list,
            [
                mock.call("[PICO] %s", "button:2"),
                mock.call("[PICO] %s", "pre_press:2"),
                mock.call("[PICO] %s", "draw_press:2"),
            ],
        )

    def test_runtime_status_fallback_logs_alias_when_debug_queue_is_empty(self):
        hid_client = mock.Mock()
        hid_client.get_runtime_status.return_value = types.SimpleNamespace(
            active=False,
            complete=False,
            text="pre:2|ui_post",
        )
        hid_client.get_debug_event.return_value = None

        panel = self._make_panel(hid_client=hid_client)

        with mock.patch.object(spark_app_v2.logging.getLogger("pico.debug"), "info") as log_info:
            panel._poll_pico_runtime_status()

        log_info.assert_called_once_with("[PICO] %s", "pre:2|ui_post")

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

    def test_poll_tick_uses_browser_extraction_when_available(self):
        info = mock.Mock(
            app_name="Google Chrome",
            pid=123,
            bundle_id="com.google.Chrome",
            title="Editor",
            process_name="chrome.exe",
        )
        tab = types.SimpleNamespace(tab_title="Docs", url="https://example.com")
        browser_result = BrowserExtractionResult(
            text="browser text",
            source="live_tab",
            title=None,
            error=None,
            is_useful=True,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info

        tracker = mock.Mock()
        tracker.get_current.return_value = None
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab) as get_browser_tab,
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "linux"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

            get_browser_tab.assert_called_once_with("Google Chrome", window_target=None)
            tracker.update.assert_called_once()
            update_args, update_kwargs = tracker.update.call_args
            self.assertEqual(update_args[0], info)
            self.assertEqual(update_args[1], "browser text")
            self.assertEqual(update_args[2], spark_app_v2.TextSource.WEB_CONTENT)
            self.assertEqual(update_kwargs["tab"], tab)
            manager.get_focused_element_text.assert_not_called()
            manager.get_window_text.assert_not_called()
            web_extractor.extract_page.assert_called_once_with(
                "https://example.com",
                "Google Chrome",
                window_target=None,
            )
            self.assertEqual(panel.ctx_card_active.title_lbl.text(), "Google Chrome")
            self.assertEqual(
                panel.ctx_card_active.sub_lbl.text(),
                "Docs\nURL: https://example.com\nKey: Google Chrome|https://example.com",
            )

    def test_poll_tick_uses_browser_extraction_for_windows_browser_app_names(self):
        info = mock.Mock(
            app_name="chrome",
            pid=123,
            bundle_id="chrome.exe",
            title="Editor",
            process_name="chrome.exe",
        )
        tab = types.SimpleNamespace(tab_title="Docs", url="https://example.com")
        browser_result = BrowserExtractionResult(
            text="browser text",
            source="live_tab",
            title=None,
            error=None,
            is_useful=True,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        tracker = mock.Mock()
        tracker.get_current.return_value = None
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
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab) as get_browser_tab,
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "linux"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

            get_browser_tab.assert_called_once_with("chrome", window_target=None)
            tracker.update.assert_called_once()
            update_args, update_kwargs = tracker.update.call_args
            self.assertEqual(update_args[0], info)
            self.assertEqual(update_args[1], "browser text")
            self.assertEqual(update_args[2], spark_app_v2.TextSource.WEB_CONTENT)
            self.assertEqual(update_kwargs["tab"], tab)
            manager.get_focused_element_text.assert_not_called()
            manager.get_window_text.assert_not_called()
            web_extractor.extract_page.assert_called_once_with(
                "https://example.com",
                "chrome",
                window_target=None,
            )

    def test_is_browser_app_for_poll_normalizes_names(self):
        self.assertTrue(spark_app_v2.SparkPanel._is_browser_app_for_poll("chrome"))
        self.assertTrue(spark_app_v2.SparkPanel._is_browser_app_for_poll("chrome.exe"))
        self.assertTrue(spark_app_v2.SparkPanel._is_browser_app_for_poll("Google Chrome"))
        self.assertTrue(spark_app_v2.SparkPanel._is_browser_app_for_poll("MsEdge"))
        self.assertFalse(spark_app_v2.SparkPanel._is_browser_app_for_poll("not-a-browser"))

    def test_poll_tick_passes_window_handle_to_browser_tab_lookup(self):
        info = mock.Mock(
            app_name="chrome",
            pid=123,
            bundle_id="chrome.exe",
            title="Editor",
            process_name="chrome.exe",
            window_handle=777,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        manager.get_focused_element_text.return_value = "focused text"

        tracker = mock.Mock()
        tracker.get_current.return_value = None
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
            mock.patch.object(spark_app_v2, "get_browser_tab") as get_browser_tab,
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
        ):
            get_browser_tab.return_value = None

            panel = spark_app_v2.SparkPanel()

            panel._on_poll_tick()

        get_browser_tab.assert_called_once_with("chrome", window_target=777)
        tracker.update.assert_called_once()

    def test_poll_tick_shows_context_key_with_window_title_when_browser_url_missing(self):
        info = mock.Mock(
            app_name="Google Chrome",
            pid=123,
            bundle_id="chrome.exe",
            title="Theo stream - YouTube - Google Chrome",
            process_name="chrome.exe",
        )
        tab = types.SimpleNamespace(tab_title="Theo stream - YouTube - Google Chrome", url="")
        browser_result = BrowserExtractionResult(
            text="browser text",
            source="live_tab",
            title=None,
            error=None,
            is_useful=True,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info

        tracker = mock.Mock()
        tracker.get_current.return_value = None
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "linux"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

            self.assertEqual(
                panel.ctx_card_active.sub_lbl.text(),
                "Theo stream - YouTube - Google Chrome\nURL: (missing)\nKey: Google Chrome|Theo stream - YouTube - Google Chrome",
            )

    def test_poll_tick_falls_back_to_focused_element_when_browser_text_missing(self):
        info = mock.Mock(
            app_name="Google Chrome",
            pid=123,
            bundle_id="com.google.Chrome",
            title="Editor",
            process_name="chrome.exe",
        )
        tab = types.SimpleNamespace(tab_title="Docs", url="https://example.com")
        browser_result = BrowserExtractionResult(
            text="",
            source="live_tab",
            title=None,
            error="empty",
            is_useful=False,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        manager.get_focused_element_text.return_value = "focused text"
        manager.get_window_text.return_value = "window text"

        tracker = mock.Mock()
        tracker.get_current.return_value = None
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "linux"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

            tracker.update.assert_called_once()
            update_args, _ = tracker.update.call_args
            self.assertEqual(update_args[2], spark_app_v2.TextSource.FOCUSED_ELEMENT)

    def test_poll_tick_runs_browser_extraction_for_browser_tab_without_url(self):
        info = mock.Mock(
            app_name="chrome",
            pid=123,
            bundle_id="chrome.exe",
            title="Theo stream",
            process_name="chrome.exe",
            window_handle=999,
        )
        tab = types.SimpleNamespace(tab_title="Theo stream", url="")
        browser_result = BrowserExtractionResult(
            text="",
            source="live_tab",
            title=None,
            error="no useful live text",
            is_useful=False,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        manager.get_focused_element_text.return_value = None
        manager.get_window_text.return_value = (
            "Useful full window content that should become context after filtering "
            "because browser text was unavailable."
        )

        tracker = mock.Mock()
        tracker.get_current.return_value = None
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "win32"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

        web_extractor.extract_page.assert_called_once_with(
            "",
            "chrome",
            window_target=999,
        )
        manager.get_focused_element_text.assert_called_once_with()
        manager.get_window_text.assert_called_once_with()
        tracker.update.assert_called_once()
        update_args, _ = tracker.update.call_args
        self.assertEqual(update_args[0], info)
        self.assertEqual(update_args[1], manager.get_window_text.return_value)
        self.assertEqual(update_args[2], spark_app_v2.TextSource.WEB_CONTENT)

    def test_poll_tick_does_not_fall_back_to_raw_accessibility_when_browser_fallback_is_noisy(self):
        info = mock.Mock(
            app_name="chrome",
            pid=123,
            bundle_id="chrome.exe",
            title="Theo stream",
            process_name="chrome.exe",
            window_handle=222,
        )
        tab = types.SimpleNamespace(tab_title="Theo stream", url="https://example.com/watch?v=1")
        browser_result = BrowserExtractionResult(
            text="Bookmarks Extensions Apps Settings Profile Search Address",
            source="live_tab",
            title=None,
            error="heuristics rejected",
            is_useful=False,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        manager.get_focused_element_text.return_value = "Back Reload"
        manager.get_window_text.return_value = "Address Bar"

        tracker = mock.Mock()
        tracker.get_current.return_value = None
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "win32"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

        web_extractor.extract_page.assert_called_once_with(
            "https://example.com/watch?v=1",
            "chrome",
            window_target=222,
        )
        self.assertEqual(tracker.update.call_count, 0)
        serial_sender.send_context_new.assert_not_called()

    def test_poll_tick_rejects_noisy_browser_output_and_uses_filtered_window_fallback(self):
        info = mock.Mock(
            app_name="chrome",
            pid=123,
            bundle_id="chrome.exe",
            title="Theo stream",
            process_name="chrome.exe",
            window_handle=333,
        )
        tab = types.SimpleNamespace(tab_title="Theo stream", url="https://example.com/watch?v=1")
        browser_result = BrowserExtractionResult(
            text="Bookmarks Extensions Apps Settings Profile Search Address",
            source="live_tab",
            title=None,
            error="heuristics rejected",
            is_useful=False,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        manager.get_focused_element_text.return_value = "Back Reload Forward Address Search"
        manager.get_window_text.return_value = (
            "A filtered full-window fallback that contains enough diverse words "
            "to be accepted as useful page context for this sample."
        )

        tracker = mock.Mock()
        tracker.get_current.return_value = None
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "win32"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

        web_extractor.extract_page.assert_called_once_with(
            "https://example.com/watch?v=1",
            "chrome",
            window_target=333,
        )
        manager.get_focused_element_text.assert_called_once_with()
        manager.get_window_text.assert_called_once_with()
        tracker.update.assert_called_once()
        update_args, _ = tracker.update.call_args
        self.assertEqual(update_args[1], manager.get_window_text.return_value)
        self.assertEqual(update_args[2], spark_app_v2.TextSource.WEB_CONTENT)

    def test_poll_tick_drops_sample_if_active_window_changes_before_commit(self):
        chrome_info = mock.Mock(
            app_name="Google Chrome",
            pid=123,
            bundle_id="com.google.Chrome",
            title="Theo stream",
            process_name="chrome.exe",
        )
        terminal_info = mock.Mock(
            app_name="WindowsTerminal",
            pid=456,
            bundle_id="terminal",
            title="OC terminal",
            process_name="WindowsTerminal.exe",
        )

        manager = mock.Mock()
        manager.get_active_window_info.side_effect = [chrome_info, terminal_info]
        manager.get_focused_element_text.return_value = "terminal text"
        manager.get_window_text.return_value = None

        tracker = mock.Mock()
        tracker.get_current.return_value = None
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
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
        ):
            panel = spark_app_v2.SparkPanel()

            panel._on_poll_tick()

            tracker.update.assert_not_called()
            serial_sender.send_context_new.assert_not_called()

    def test_poll_tick_falls_back_to_window_when_focused_element_is_empty(self):
        info = mock.Mock(
            app_name="Google Chrome",
            pid=123,
            bundle_id="com.google.Chrome",
            title="Editor",
            process_name="chrome.exe",
        )
        tab = types.SimpleNamespace(tab_title="Docs", url="https://example.com")
        browser_result = BrowserExtractionResult(
            text=None,
            source="live_tab",
            title=None,
            error="empty",
            is_useful=False,
        )

        manager = mock.Mock()
        manager.get_active_window_info.return_value = info
        manager.get_focused_element_text.return_value = ""
        manager.get_window_text.return_value = "window text"

        tracker = mock.Mock()
        tracker.get_current.return_value = None
        tracker.get_all_previous.return_value = []

        serial_sender = mock.Mock()
        serial_sender.is_connected.return_value = True
        serial_sender.send_context_new.return_value = True

        web_extractor = mock.Mock()
        web_extractor.extract_page.return_value = browser_result

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=serial_sender),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2, "get_browser_tab", return_value=tab),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2, "is_relevant_snapshot", return_value=True),
            mock.patch.object(spark_app_v2.sys, "platform", "linux"),
        ):
            panel = spark_app_v2.SparkPanel()
            panel.web_extractor = web_extractor

            panel._on_poll_tick()

            tracker.update.assert_called_once()
            update_args, _ = tracker.update.call_args
            self.assertEqual(update_args[2], spark_app_v2.TextSource.FULL_WINDOW)

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
