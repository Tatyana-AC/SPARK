import types
import unittest
from unittest import mock

from core.protocol import PacketParser, PKT_CONTEXT_NEW, PKT_CONTEXT_UPDATE, build_debug
from host_pc import serial_sender
from host_pc.accessibility.base import TextSource, WindowContextSnapshot, WindowInfo


class FakeSerialPort:
    def __init__(self, reads=None):
        self.is_open = True
        self.writes = []
        self._reads = list(reads or [])
        self.in_waiting = len(self._reads[0]) if self._reads else 0
        self.closed = False

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

    def close(self):
        self.is_open = False
        self.closed = True


class FailingReadSerialPort(FakeSerialPort):
    def __init__(self):
        super().__init__(reads=[b"x"])

    def read(self, size):
        raise PermissionError(13, "The device does not recognize the command.", None, 22)


class FailingWriteSerialPort(FakeSerialPort):
    def write(self, data):
        raise TimeoutError("Write timeout")


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
            mock.patch.object(serial_sender.SerialSender, "_get_windows_interface_number", return_value=None),
            mock.patch("serial.tools.list_ports.comports", return_value=[other, matching]),
        ):
            port = serial_sender.SerialSender._find_pico_port()

        self.assertEqual(port, "COM7")

    def test_find_pico_port_prefers_lowest_interface_number_for_same_pico_serial(self):
        console_port = types.SimpleNamespace(device="COM5", vid=0xC4C4, pid=0x5350, serial_number="abc")
        data_port = types.SimpleNamespace(device="COM10", vid=0xC4C4, pid=0x5350, serial_number="abc")

        with (
            mock.patch.object(serial_sender.sys, "platform", "win32"),
            mock.patch.object(
                serial_sender.SerialSender,
                "_get_windows_interface_number",
                side_effect=lambda device: {"COM5": 2, "COM10": 0}[device],
            ),
            mock.patch("serial.tools.list_ports.comports", return_value=[console_port, data_port]),
        ):
            port = serial_sender.SerialSender._find_pico_port()

        self.assertEqual(port, "COM10")

    def test_find_pico_port_falls_back_to_higher_com_number_when_interface_unknown(self):
        console_port = types.SimpleNamespace(device="COM5", vid=0xC4C4, pid=0x5350, serial_number="abc")
        data_port = types.SimpleNamespace(device="COM10", vid=0xC4C4, pid=0x5350, serial_number="abc")

        with (
            mock.patch.object(serial_sender.sys, "platform", "win32"),
            mock.patch.object(serial_sender.SerialSender, "_get_windows_interface_number", return_value=None),
            mock.patch("serial.tools.list_ports.comports", return_value=[console_port, data_port]),
        ):
            port = serial_sender.SerialSender._find_pico_port()

        self.assertEqual(port, "COM10")

    def test_read_once_closes_broken_serial_handle_after_windows_error(self):
        sender = serial_sender.SerialSender(port="COM10")
        broken_port = FailingReadSerialPort()
        sender._serial = broken_port

        chunk = sender.read_once()

        self.assertEqual(chunk, b"")
        self.assertIsNone(sender._serial)
        self.assertTrue(broken_port.closed)

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

    def test_send_context_new_preserves_full_text_payload(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()
        parser_packets = []
        parser = PacketParser(on_packet=parser_packets.append)

        ok = sender.send_context_new(make_snapshot(text="x" * 2000))

        self.assertTrue(ok)
        parser.feed(b"".join(sender._serial.writes))
        self.assertEqual(parser_packets[0]["type"], PKT_CONTEXT_NEW)
        self.assertEqual(len(parser_packets[0]["text"]), 2000)
        self.assertEqual(parser_packets[0]["text"], "x" * 2000)

    def test_send_context_new_paces_large_packet_in_bounded_serial_chunks(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()
        parser_packets = []
        parser = PacketParser(on_packet=parser_packets.append)

        with mock.patch.object(serial_sender.time, "sleep") as sleep:
            ok = sender.send_context_new(make_snapshot(text="x" * 1500))

        self.assertTrue(ok)
        self.assertGreater(len(sender._serial.writes), 1)
        self.assertTrue(
            all(len(chunk) <= serial_sender._SERIAL_WRITE_CHUNK_BYTES for chunk in sender._serial.writes)
        )
        sleep.assert_called()
        parser.feed(b"".join(sender._serial.writes))
        self.assertEqual(parser_packets[0]["type"], PKT_CONTEXT_NEW)
        self.assertEqual(parser_packets[0]["text"], "x" * 1500)

    def test_send_context_new_truncates_large_text_to_transport_budget(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()
        parser_packets = []
        parser = PacketParser(on_packet=parser_packets.append)
        huge_text = "x" * 30000

        ok = sender.send_context_new(make_snapshot(text=huge_text))

        self.assertTrue(ok)
        self.assertLessEqual(
            len(b"".join(sender._serial.writes)),
            serial_sender._MAX_CONTEXT_PACKET_BYTES,
        )
        parser.feed(b"".join(sender._serial.writes))
        self.assertEqual(parser_packets[0]["type"], PKT_CONTEXT_NEW)
        self.assertLess(len(parser_packets[0]["text"]), len(huge_text))
        self.assertEqual(
            parser_packets[0]["text"],
            huge_text[: len(parser_packets[0]["text"])],
        )

    def test_send_context_update_truncates_text_too_large_for_protocol_header(self):
        sender = serial_sender.SerialSender(port="COM7")
        sender._serial = FakeSerialPort()
        parser_packets = []
        parser = PacketParser(on_packet=parser_packets.append)
        huge_text = "x" * 100000

        ok = sender.send_context_update(make_snapshot(text=huge_text))

        self.assertTrue(ok)
        self.assertLessEqual(
            len(b"".join(sender._serial.writes)),
            serial_sender._MAX_CONTEXT_PACKET_BYTES,
        )
        parser.feed(b"".join(sender._serial.writes))
        self.assertEqual(parser_packets[0]["type"], PKT_CONTEXT_UPDATE)
        self.assertLess(len(parser_packets[0]["text"]), len(huge_text))
        self.assertEqual(
            parser_packets[0]["text"],
            huge_text[: len(parser_packets[0]["text"])],
        )

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

    def test_debug_packet_callback_receives_parsed_debug_payload(self):
        sender = serial_sender.SerialSender(port="COM7")
        debug_packets = []
        sender.set_packet_callback(debug_packets.append)

        sender._on_pico_packet({"type": serial_sender.PKT_DEBUG, "msg": "button:1"})

        self.assertEqual(debug_packets, [{"type": serial_sender.PKT_DEBUG, "msg": "button:1"}])

    def test_write_error_blacklists_port_and_falls_back_to_next_candidate(self):
        sender = serial_sender.SerialSender()
        sender._serial = FailingWriteSerialPort()
        sender._connected_port = "COM6"
        sender._last_connected_port = "COM6"

        opened_ports = []

        class _FakeSerialModule:
            @staticmethod
            def Serial(port, baud, timeout, write_timeout):
                opened_ports.append(port)
                return FakeSerialPort()

        with (
            mock.patch.object(serial_sender, "time", mock.Mock(monotonic=mock.Mock(side_effect=[10.0, 10.0, 10.0]))),
            mock.patch.object(serial_sender.SerialSender, "_find_pico_port", return_value="COM10"),
            mock.patch.dict("sys.modules", {"serial": _FakeSerialModule}),
        ):
            ok = sender.send_context_new(make_snapshot())
            reconnected = sender.connect()

        self.assertFalse(ok)
        self.assertTrue(reconnected)
        self.assertEqual(opened_ports, ["COM10"])

    def test_connect_skips_blacklisted_port_until_cooldown_expires(self):
        sender = serial_sender.SerialSender()
        sender._last_connected_port = "COM6"
        sender._bad_ports_until["COM6"] = 20.0

        opened_ports = []

        class _FakeSerialModule:
            @staticmethod
            def Serial(port, baud, timeout, write_timeout):
                opened_ports.append(port)
                return FakeSerialPort()

        with (
            mock.patch.object(serial_sender, "time", mock.Mock(monotonic=mock.Mock(return_value=10.0))),
            mock.patch.object(serial_sender.SerialSender, "_find_pico_port", return_value="COM10"),
            mock.patch.dict("sys.modules", {"serial": _FakeSerialModule}),
        ):
            connected = sender.connect()

        self.assertTrue(connected)
        self.assertEqual(opened_ports, ["COM10"])


if __name__ == "__main__":
    unittest.main()
