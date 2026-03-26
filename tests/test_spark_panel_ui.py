import unittest
from unittest import mock

from PyQt6.QtWidgets import QApplication, QTextEdit

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


class _DummyDB:
    def get_pref(self, key):
        return None

    def set_pref(self, key, value):
        return None

    def close(self):
        return None


class _DummyDBViewer:
    def __init__(self, db):
        self._visible = False

    def isVisible(self):
        return self._visible

    def refresh(self):
        return None

    def close(self):
        return None


class SparkPanelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_release_output_uses_fixed_height_scrollable_text_widget(self):
        with (
            mock.patch.object(spark_app_v2, "AccessibilityManager", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "GlobalHotkeyManager", return_value=_DummyHotkeys()),
            mock.patch.object(spark_app_v2, "SparkDB", return_value=_DummyDB()),
            mock.patch.object(spark_app_v2, "WindowContextTracker", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "DatabaseViewerWindow", side_effect=lambda db: _DummyDBViewer(db)),
            mock.patch.object(spark_app_v2, "SparkHIDClient", return_value=mock.Mock()),
            mock.patch.object(spark_app_v2, "SerialSender", return_value=_DummySerialSender()),
            mock.patch.object(spark_app_v2, "LiveCaptureFeed", return_value=mock.Mock(lines=["Polling not started…"])),
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


if __name__ == "__main__":
    unittest.main()
