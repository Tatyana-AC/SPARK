import unittest
from unittest import mock

from host_pc import browser
from host_pc.browser import BrowserTabInfo


class BrowserTests(unittest.TestCase):
    def test_macos_google_chrome_keeps_full_url(self):
        long_url = (
            "https://example.com/path/with/many/parts?" + "q=" + "a" * 120
        )

        with (
            mock.patch.object(browser.sys, "platform", "darwin"),
            mock.patch.object(
                browser,
                "_run_applescript",
                side_effect=["Example Tab", long_url],
            ),
        ):
            tab = browser.get_browser_tab("Google Chrome")

        self.assertIsNotNone(tab)
        self.assertEqual(tab.url, long_url)

    def test_windows_browser_names_dispatch_to_windows_helper(self):
        expected = BrowserTabInfo(tab_title="Window", url="https://example.com")

        with (
            mock.patch.object(browser.sys, "platform", "win32"),
            mock.patch.object(browser, "_get_windows_browser_tab", return_value=expected) as helper,
        ):
            tab = browser.get_browser_tab("chrome")

        self.assertIs(tab, expected)
        helper.assert_called_once_with("chrome", None)

    def test_unsupported_platform_returns_none(self):
        with (
            mock.patch.object(browser.sys, "platform", "linux"),
            mock.patch.object(browser, "_get_macos_browser_tab", side_effect=AssertionError("should not call mac")),
            mock.patch.object(browser, "_get_windows_browser_tab", side_effect=AssertionError("should not call windows")),
        ):
            tab = browser.get_browser_tab("Google Chrome")

        self.assertIsNone(tab)


if __name__ == "__main__":
    unittest.main()
