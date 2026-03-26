import types
import unittest
from unittest import mock

from host_pc import serial_sender


class FakeSerialPort:
    def __init__(self, payloads=None):
        self.is_open = True
        self.writes = []
        self._payloads = list(payloads or [])

    @property
    def in_waiting(self):
        if not self._payloads:
            return 0
        return len(self._payloads[0])

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, count):
        if not self._payloads:
            return b""
        payload = self._payloads.pop(0)
        return bytes(payload[:count])


class SerialSenderTests(unittest.TestCase):
    def test_find_pico_port_prefers_matching_vid_pid_on_windows(self):
        matching = types.SimpleNamespace(device="COM7", vid=0xC4C4, pid=0x5350)
        other = types.SimpleNamespace(device="COM2", vid=0x1111, pid=0x2222)

        with (
            mock.patch.object(serial_sender.sys, "platform", "win32"),
            mock.patch("serial.tools.list_ports.comports", return_value=[other, matching]),
        ):
            port = serial_sender.SerialSender._find_pico_port()

        self.assertEqual(port, "COM7")

    def test_send_raw_appends_eot_when_requested(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()

        ok = sender.send_raw(b"hello", append_eot=True)

        self.assertTrue(ok)
        self.assertEqual(sender._serial.writes, [b"hello\x04"])

    def test_read_once_ignores_ack_and_streams_other_bytes_to_callback(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort([b"\x06partial", b" more\x04"])
        seen = []
        sender.set_stream_callback(seen.append)

        first = sender.read_once()
        second = sender.read_once()

        self.assertEqual(first, b"partial")
        self.assertEqual(second, b" more\x04")
        self.assertEqual(seen, [b"partial", b" more\x04"])


if __name__ == "__main__":
    unittest.main()
