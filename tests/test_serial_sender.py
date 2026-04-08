import types
import unittest
from unittest import mock

from core.protocol import PacketParser, PKT_CONTEXT_NEW, PKT_CONTEXT_UPDATE
from host_pc import serial_sender
from host_pc.accessibility.base import TextSource, WindowContextSnapshot, WindowInfo


class FakeSerialPort:
    def __init__(self, reads=None):
        self.is_open = True
        self.writes = []
        self._reads = list(reads or [])
        self.in_waiting = len(self._reads[0]) if self._reads else 0

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, size):
        if not self._reads:
            self.in_waiting = 0
            return b""
        chunk = bytes(self._reads.pop(0))
        self.in_waiting = len(self._reads[0]) if self._reads else 0
        return chunk


def make_snapshot(text="hello world"):
    return WindowContextSnapshot(
        window_info=WindowInfo(
            title="Plan",
            app_name="Codex",
            process_name="Codex.exe",
            pid=42,
        ),
        text=text,
        source=TextSource.FULL_WINDOW,
        timestamp=123.45,
    )


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

    def test_find_pico_port_prefers_lower_com_number_when_multiple_pico_ports_exist(self):
        console_port = types.SimpleNamespace(device="COM10", vid=0xC4C4, pid=0x5350)
        data_port = types.SimpleNamespace(device="COM5", vid=0xC4C4, pid=0x5350)

        with (
            mock.patch.object(serial_sender.sys, "platform", "win32"),
            mock.patch("serial.tools.list_ports.comports", return_value=[console_port, data_port]),
        ):
            port = serial_sender.SerialSender._find_pico_port()

        self.assertEqual(port, "COM5")

    def test_send_context_new_serializes_rich_snapshot_payload(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()
        parser_packets = []
        parser = PacketParser(on_packet=parser_packets.append)

        ok = sender.send_context_new(make_snapshot())

        self.assertTrue(ok)
        parser.feed(sender._serial.writes[0])
        self.assertEqual(parser_packets[0]["type"], PKT_CONTEXT_NEW)
        self.assertEqual(parser_packets[0]["app_name"], "Codex")
        self.assertEqual(parser_packets[0]["text"], "hello world")

    def test_send_context_update_serializes_update_packet(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()
        parser_packets = []
        parser = PacketParser(on_packet=parser_packets.append)

        ok = sender.send_context_update(make_snapshot(text="updated"))

        self.assertTrue(ok)
        parser.feed(sender._serial.writes[0])
        self.assertEqual(parser_packets[0]["type"], PKT_CONTEXT_UPDATE)
        self.assertEqual(parser_packets[0]["text"], "updated")

    def test_send_raw_appends_eot_when_requested(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()

        ok = sender.send_raw(b"hello", append_eot=True)

        self.assertTrue(ok)
        self.assertEqual(sender._serial.writes[0], b"hello" + serial_sender.EOT)

    def test_pause_blocks_context_packets_until_resume(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()
        resumed_serial = FakeSerialPort()

        def fake_connect():
            sender._serial = resumed_serial
            return True

        with mock.patch.object(sender, "connect", side_effect=fake_connect):
            sender.pause()
            paused_ok = sender.send_context_new(make_snapshot())
            sender.resume()
        resumed_ok = sender.send_context_new(make_snapshot())

        self.assertFalse(paused_ok)
        self.assertTrue(resumed_ok)
        self.assertEqual(len(resumed_serial.writes), 1)

    def test_read_once_filters_ack_and_notifies_callback(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort(reads=[b"\x06hello"])
        updates = []
        sender.set_stream_callback(updates.append)

        chunk = sender.read_once()

        self.assertEqual(chunk, b"hello")
        self.assertEqual(updates, [b"hello"])


if __name__ == "__main__":
    unittest.main()
