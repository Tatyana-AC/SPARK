import importlib
import sys
import unittest
from unittest import mock

from host_pc import browser_windows


class BrowserWindowsTests(unittest.TestCase):
    def test_notepad_is_not_a_supported_browser(self):
        self.assertIsNone(browser_windows.get_browser_tab("notepad"))

    def test_address_bar_url_is_preferred_for_url(self):
        fake_window = object()
        address_bar = object()

        with (
            mock.patch.object(
                browser_windows,
                "_connect_to_active_window",
                return_value=fake_window,
            ),
            mock.patch.object(browser_windows, "_find_address_bar", return_value=address_bar),
            mock.patch.object(
                browser_windows,
                "_read_address_bar_url",
                return_value="chrome://new-tab/page",
            ),
            mock.patch.object(
                browser_windows,
                "_read_tab_title",
                return_value="Window Title",
            ) as read_tab_title,
        ):
            result = browser_windows.get_browser_tab("chrome")

        self.assertIsNotNone(result)
        self.assertEqual(result.url, "chrome://new-tab/page")
        self.assertEqual(result.tab_title, "Window Title")
        read_tab_title.assert_called_once_with(fake_window)

    def test_returns_none_when_active_window_connection_fails(self):
        with mock.patch.object(browser_windows, "_connect_to_active_window", return_value=None):
            self.assertIsNone(browser_windows.get_browser_tab("chrome"))

    def test_module_is_safe_to_import_without_windows_dependencies(self):
        module_name = "host_pc.browser_windows"
        if module_name in sys.modules:
            del sys.modules[module_name]

        with mock.patch.dict(
            "sys.modules",
            {
                "win32gui": None,
                "win32process": None,
                "pywinauto": None,
            },
            clear=False,
        ):
            module = importlib.import_module(module_name)
            self.assertIsNone(module.get_browser_tab("chrome"))

        self.assertIsNotNone(module)


if __name__ == "__main__":
    unittest.main()
