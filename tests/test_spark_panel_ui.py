import unittest
from unittest import mock

try:
    from PyQt6.QtWidgets import QApplication, QTextEdit
except ImportError:  # pragma: no cover - environment-dependent test guard
    QApplication = None
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
    def connect(self):
        return None

    def close(self):
        return None

    def is_connected(self):
        return False


@unittest.skipUnless(QApplication is not None, "PyQt6 is not installed")
class SparkPanelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_release_output_uses_fixed_height_scrollable_text_widget(self):
        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=_DummySerialSender()),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
        ):
            panel = spark_app_v2.SparkPanel()

        self.assertIsInstance(panel.release_output_lbl, QTextEdit)
        self.assertTrue(panel.release_output_lbl.isReadOnly())
        self.assertEqual(panel.release_output_lbl.minimumHeight(), 120)
        self.assertEqual(panel.release_output_lbl.maximumHeight(), 120)
        self.assertEqual(panel.release_output_lbl.toPlainText(), "No released text yet…")

    def test_summarize_uses_last_non_spark_snapshot_when_panel_is_focused(self):
        manager = mock.Mock()
        manager.get_active_window_info.return_value = mock.Mock(
            pid=12345,
            app_name="python",
            title="SPARK",
        )
        tracker = mock.Mock()
        tracker.get_current.return_value = mock.Mock(
            text="hello from cursor",
            window_info=mock.Mock(
                pid=54321,
                app_name="Cursor",
                title="Transport debug session",
            ),
        )
        hid_client = mock.Mock()
        hid_client.is_connected.return_value = True

        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=manager),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=tracker),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=hid_client),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=_DummySerialSender()),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started..."])),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hotkeys", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_connect_hid", return_value=None),
            mock.patch.object(spark_app_v2.SparkPanel, "_restore_position", return_value=None),
            mock.patch.object(spark_app_v2.os, "getpid", return_value=12345),
        ):
            panel = spark_app_v2.SparkPanel()
            panel._start_summary_request = mock.Mock()
            panel._on_summarize()

        manager.get_window_text.assert_not_called()
        panel._start_summary_request.assert_called_once()
        kwargs = panel._start_summary_request.call_args.kwargs
        self.assertIn("Cursor", kwargs["capture_label"])
        self.assertIn("hello from cursor", kwargs["request"])


if __name__ == "__main__":
    unittest.main()
