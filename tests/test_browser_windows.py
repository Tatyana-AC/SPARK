import importlib
import sys
import unittest
from unittest import mock

from host_pc import browser_windows


class BrowserWindowsTests(unittest.TestCase):
    def test_notepad_is_not_a_supported_browser(self):
        self.assertIsNone(browser_windows.get_browser_tab("notepad"))

    def test_display_names_are_supported(self):
        with (
            mock.patch.object(browser_windows, "_connect_to_active_window", return_value=object()),
            mock.patch.object(
                browser_windows,
                "_find_address_bar",
                return_value=object(),
            ),
            mock.patch.object(
                browser_windows,
                "_read_address_bar_url",
                return_value="https://example.com",
            ),
            mock.patch.object(browser_windows, "_read_tab_title", return_value="Window Title"),
        ):
            self.assertIsNotNone(browser_windows.get_browser_tab("Google Chrome"))
            self.assertIsNotNone(browser_windows.get_browser_tab("Microsoft Edge"))
            self.assertIsNotNone(browser_windows.get_browser_tab("chrome.exe"))

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

    def test_schemeless_browser_address_is_normalized_to_https(self):
        address_bar = object()

        with mock.patch.object(
            browser_windows,
            "_control_text",
            return_value="youtube.com/watch?v=WkHdkwDQJ5o",
        ):
            url = browser_windows._read_address_bar_url(address_bar)

        self.assertEqual(url, "https://youtube.com/watch?v=WkHdkwDQJ5o")

    def test_find_address_bar_prefers_schemeless_url_value_over_search_input(self):
        class _ElementInfo:
            def __init__(self, automation_id):
                self._automation_id = automation_id

            def automation_id(self):
                return self._automation_id

        class _Control:
            def __init__(self, text, value, automation_id, friendly_class_name="Edit"):
                self._text = text
                self._value = value
                self.element_info = _ElementInfo(automation_id)
                self._friendly_class_name = friendly_class_name

            def window_text(self):
                return self._text

            def get_value(self):
                return self._value

            def friendly_class_name(self):
                return self._friendly_class_name

        address_control = _Control(
            text="en.wikipedia.org/wiki/Boston_Tea_Party",
            value="en.wikipedia.org/wiki/Boston_Tea_Party",
            automation_id="view_1012",
        )
        search_control = _Control(
            text="Search Wikipedia",
            value="",
            automation_id="searchInput",
        )

        fake_window = mock.Mock()
        fake_window.descendants.side_effect = [
            [address_control, search_control],
            [],
        ]

        selected = browser_windows._find_address_bar(fake_window)

        self.assertIs(selected, address_control)

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
