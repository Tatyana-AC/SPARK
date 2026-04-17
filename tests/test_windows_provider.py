import unittest
from unittest.mock import Mock, patch

from host_pc.accessibility.windows_provider import WindowsAccessibilityProvider


class WindowsAccessibilityProviderTests(unittest.TestCase):
    @patch.object(WindowsAccessibilityProvider, "_init_libraries", autospec=True)
    def test_get_window_text_connects_to_active_window_before_querying(self, mock_init):
        provider = WindowsAccessibilityProvider()
        hwnd = 123
        provider.win32gui = Mock()
        provider.win32gui.GetForegroundWindow.return_value = hwnd

        app = Mock()
        window = Mock()
        window.exists.return_value = True
        app.window.return_value = window

        provider.pywinauto = Mock(return_value=app)
        provider._extract_window_text_recursive = Mock(
            side_effect=lambda control, text_parts, depth=0: text_parts.append("window text")
        )

        text = provider.get_window_text()

        self.assertEqual(text, "window text")
        provider.pywinauto.assert_called_once_with(backend="uia")
        app.connect.assert_called_once_with(handle=hwnd)
        app.window.assert_called_once_with(handle=hwnd)

    @patch.object(WindowsAccessibilityProvider, "_init_libraries", autospec=True)
    def test_get_focused_element_text_connects_and_reads_focused_value(self, mock_init):
        provider = WindowsAccessibilityProvider()
        hwnd = 456
        provider.win32gui = Mock()
        provider.win32gui.GetForegroundWindow.return_value = hwnd

        focused = Mock()
        focused.get_value.return_value = "focused text"

        window = Mock()
        window.exists.return_value = True
        window.get_focus.return_value = focused

        app = Mock()
        app.window.return_value = window

        provider.pywinauto = Mock(return_value=app)

        text = provider.get_focused_element_text()

        self.assertEqual(text, "focused text")
        provider.pywinauto.assert_called_once_with(backend="uia")
        app.connect.assert_called_once_with(handle=hwnd)
        app.window.assert_called_once_with(handle=hwnd)

    @patch.object(WindowsAccessibilityProvider, "_init_libraries", autospec=True)
    def test_get_focused_element_text_prefers_editor_like_descendant_text(self, mock_init):
        provider = WindowsAccessibilityProvider()

        editor = Mock()
        editor.element_info.control_type = "Document"
        editor.get_value.return_value = "This is the proof that the square root of 2 is irrational."

        focused = Mock()
        focused.get_value.return_value = ""
        focused.window_text.return_value = ""
        focused.texts.return_value = []
        focused.descendants.return_value = [editor]
        focused.element_info.control_type = "Pane"

        window = Mock()
        window.get_focus.return_value = focused

        provider._connect_to_active_window = Mock(return_value=window)

        text = provider.get_focused_element_text()

        self.assertEqual(text, "This is the proof that the square root of 2 is irrational.")

    @patch.object(WindowsAccessibilityProvider, "_init_libraries", autospec=True)
    def test_get_focused_element_text_prefers_editor_body_over_tab_label(self, mock_init):
        provider = WindowsAccessibilityProvider()

        editor = Mock()
        editor.element_info.control_type = "Document"
        editor.get_value.return_value = "This is the proof that the square root of 2 is irrational."

        focused = Mock()
        focused.get_value.return_value = ""
        focused.window_text.return_value = "math proof.txt"
        focused.texts.return_value = ["math proof.txt"]
        focused.descendants.return_value = [editor]
        focused.element_info.control_type = "TabItem"

        window = Mock()
        window.get_focus.return_value = focused

        provider._connect_to_active_window = Mock(return_value=window)

        text = provider.get_focused_element_text()

        self.assertEqual(text, "This is the proof that the square root of 2 is irrational.")

    @patch.object(WindowsAccessibilityProvider, "_init_libraries", autospec=True)
    def test_get_window_text_prefers_editor_like_descendant_over_window_chrome(self, mock_init):
        provider = WindowsAccessibilityProvider()
        provider.win32gui = Mock()
        provider.pywinauto = Mock()

        tab = Mock()
        tab.element_info.control_type = "TabItem"
        tab.get_value.return_value = ""
        tab.window_text.return_value = "github token.txt"
        tab.texts.return_value = ["github token.txt"]

        toolbar = Mock()
        toolbar.element_info.control_type = "ToolBar"
        toolbar.get_value.return_value = ""
        toolbar.window_text.return_value = "Bold"
        toolbar.texts.return_value = ["Bold"]

        editor = Mock()
        editor.element_info.control_type = "Document"
        editor.get_value.return_value = "This is the proof that the square root of 2 is irrational."

        window = Mock()
        window.descendants.return_value = [tab, toolbar, editor]

        provider._connect_to_active_window = Mock(return_value=window)
        provider._extract_window_text_recursive = Mock(
            side_effect=lambda control, text_parts, depth=0: text_parts.extend(
                ["github token.txt", "Bold", "This is the proof that the square root of 2 is irrational."]
            )
        )

        text = provider.get_window_text()

        self.assertEqual(text, "This is the proof that the square root of 2 is irrational.")

    @patch.object(WindowsAccessibilityProvider, "_init_libraries", autospec=True)
    def test_get_active_window_info_includes_window_handle(self, mock_init):
        provider = WindowsAccessibilityProvider()
        hwnd = 789
        provider.win32gui = Mock()
        provider.win32process = Mock()
        provider.psutil = Mock()
        provider.win32gui.GetForegroundWindow.return_value = hwnd
        provider.win32gui.GetWindowText.return_value = "Window Title"
        provider.win32process.GetWindowThreadProcessId.return_value = (None, 321)
        provider.win32gui.GetWindowRect.return_value = (1, 2, 401, 202)
        provider.psutil.Process.return_value.name.return_value = "chrome.exe"

        info = provider.get_active_window_info()

        self.assertIsNotNone(info)
        self.assertEqual(info.window_handle, hwnd)
        self.assertEqual(info.pid, 321)
        self.assertEqual(info.process_name, "chrome.exe")


if __name__ == "__main__":
    unittest.main()
