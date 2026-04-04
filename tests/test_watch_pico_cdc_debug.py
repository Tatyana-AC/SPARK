import types
import unittest


class WatchPicoCdcDebugTests(unittest.TestCase):
    def test_select_port_prefers_matching_vid_pid(self):
        import watch_pico_cdc_debug as monitor

        ports = [
            types.SimpleNamespace(device="COM6", vid=0x0955, pid=0x7020),
            types.SimpleNamespace(device="COM11", vid=0xC4C4, pid=0x5350),
        ]

        self.assertEqual(monitor.select_port(ports), "COM11")

    def test_select_port_rejects_multiple_matching_picos(self):
        import watch_pico_cdc_debug as monitor

        ports = [
            types.SimpleNamespace(device="COM11", vid=0xC4C4, pid=0x5350),
            types.SimpleNamespace(device="COM12", vid=0xC4C4, pid=0x5350),
        ]

        with self.assertRaisesRegex(RuntimeError, "Multiple Pico CDC ports"):
            monitor.select_port(ports)

    def test_select_port_requires_device_when_no_match(self):
        import watch_pico_cdc_debug as monitor

        ports = [
            types.SimpleNamespace(device="COM6", vid=0x0955, pid=0x7020),
        ]

        with self.assertRaisesRegex(RuntimeError, "Could not find Pico CDC port"):
            monitor.select_port(ports)


if __name__ == "__main__":
    unittest.main()
