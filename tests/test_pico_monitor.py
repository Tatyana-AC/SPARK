import unittest
from unittest import mock


class PicoMonitorCliTests(unittest.TestCase):
    def test_windows_defaults_to_no_clear(self):
        from tools.monitoring import pico_monitor as monitor

        args = monitor.build_arg_parser().parse_args([])

        self.assertFalse(monitor.should_clear_screen(args.clear_screen, "nt"))

    def test_clear_flag_enables_dashboard_redraw_on_windows(self):
        from tools.monitoring import pico_monitor as monitor

        args = monitor.build_arg_parser().parse_args(["--clear-screen"])

        self.assertTrue(monitor.should_clear_screen(args.clear_screen, "nt"))

    def test_hid_poller_keeps_runtime_status_text_verbatim(self):
        from tools.monitoring import pico_monitor as monitor

        fake_hid = mock.Mock()
        fake_hid.enumerate.return_value = []
        fake_hid.device.return_value = mock.Mock()
        runtime_reply = bytearray(monitor.REPORT_SIZE)
        runtime_reply[0] = monitor.CMD_GET_RUNTIME_STATUS
        runtime_reply[1] = monitor.RESPONSE_FLAG_ACTIVE
        runtime_reply[2:15] = b"pre:2|ui_post"

        with mock.patch.dict("sys.modules", {"hid": fake_hid}):
            poller = monitor.HIDPoller()

        poller._open = lambda: True
        poller._send_and_match = lambda command: runtime_reply if command == monitor.CMD_GET_RUNTIME_STATUS else None

        state = poller.poll()

        self.assertEqual(state.runtime_status_text, "pre:2|ui_post")


if __name__ == "__main__":
    unittest.main()
