import unittest

try:
    from host_pc.hotkeys import get_hotkey_config
except ImportError:  # pragma: no cover - environment-dependent test guard
    get_hotkey_config = None


@unittest.skipUnless(get_hotkey_config is not None, "PyQt6 is not installed")
class HotkeyConfigTests(unittest.TestCase):
    def test_macos_hotkeys_remain_unchanged(self):
        config = get_hotkey_config("darwin")

        self.assertEqual(config["capture_combo"], "<cmd>+<ctrl>+c")
        self.assertEqual(config["release_combo"], "<cmd>+<ctrl>+r")
        self.assertEqual(config["toggle_combo"], "<cmd>+<ctrl>+<space>")
        self.assertEqual(config["capture_label"], "Cmd+Ctrl+C")
        self.assertEqual(config["release_label"], "Cmd+Ctrl+R")
        self.assertEqual(config["toggle_label"], "Cmd+Ctrl+Space")

    def test_windows_hotkeys_use_non_conflicting_defaults(self):
        config = get_hotkey_config("win32")

        self.assertEqual(config["capture_combo"], "<cmd>+<alt>+c")
        self.assertEqual(config["release_combo"], "<cmd>+<alt>+v")
        self.assertEqual(config["toggle_combo"], "<ctrl>+<f1>")
        self.assertEqual(config["capture_label"], "Win+Alt+C")
        self.assertEqual(config["release_label"], "Win+Alt+V")
        self.assertEqual(config["toggle_label"], "Ctrl+F1")


if __name__ == "__main__":
    unittest.main()
