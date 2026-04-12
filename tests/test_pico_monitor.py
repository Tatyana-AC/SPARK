import unittest


class PicoMonitorCliTests(unittest.TestCase):
    def test_windows_defaults_to_no_clear(self):
        import pico_monitor as monitor

        args = monitor.build_arg_parser().parse_args([])

        self.assertFalse(monitor.should_clear_screen(args.clear_screen, "nt"))

    def test_clear_flag_enables_dashboard_redraw_on_windows(self):
        import pico_monitor as monitor

        args = monitor.build_arg_parser().parse_args(["--clear-screen"])

        self.assertTrue(monitor.should_clear_screen(args.clear_screen, "nt"))


if __name__ == "__main__":
    unittest.main()
