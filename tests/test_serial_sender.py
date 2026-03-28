import types
import unittest
from unittest import mock

from core.protocol import PacketParser, PKT_CONTEXT_NEW, PKT_CONTEXT_UPDATE
from host_pc import serial_sender
from host_pc.accessibility.base import TextSource, WindowContextSnapshot, WindowInfo


class FakeSerialPort:
    def __init__(self):
        self.is_open = True
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)


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


if __name__ == "__main__":
    unittest.main()
