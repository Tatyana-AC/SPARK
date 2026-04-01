import unittest

from core.protocol import build_button_press


class FakeCDC:
    def __init__(self, payload=b""):
        self._payload = bytearray(payload)
        self.writes = []

    @property
    def in_waiting(self):
        return len(self._payload)

    def read(self, count):
        data = bytes(self._payload[:count])
        del self._payload[:count]
        return data

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)


class FakeUART:
    def __init__(self, payload=b""):
        self.writes = []
        self._payload = bytearray(payload)

    @property
    def in_waiting(self):
        return len(self._payload)

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, count):
        data = bytes(self._payload[:count])
        del self._payload[:count]
        return data


class FailingUART(FakeUART):
    def write(self, data):
        raise OSError("uart write failed")


class SerialBridgeTests(unittest.TestCase):
    def test_build_button_press_packet_matches_shared_protocol(self):
        from pico.serial_bridge import build_button_press_packet

        self.assertEqual(build_button_press_packet(3), build_button_press(3))

    def test_relay_once_forwards_cdc_bytes_to_uart_in_bounded_chunk(self):
        from pico.serial_bridge import SerialBridge

        cdc = FakeCDC(b"abcdefghijklmnopqrstuvwxyz")
        uart = FakeUART()
        bridge = SerialBridge(cdc, uart)

        written = bridge.relay_once(max_chunk_size=8)

        self.assertEqual(written, 8)
        self.assertEqual(uart.writes, [b"abcdefgh"])
        self.assertEqual(cdc.in_waiting, 18)

    def test_relay_once_does_not_consume_uart_response_bytes(self):
        from pico.serial_bridge import SerialBridge

        cdc = FakeCDC()
        uart = FakeUART(b"summary")
        bridge = SerialBridge(cdc, uart)

        written = bridge.relay_once(max_chunk_size=8)

        self.assertEqual(written, 0)
        self.assertEqual(cdc.writes, [])
        self.assertEqual(uart.in_waiting, 7)

    def test_inject_button_press_writes_framed_packet_to_uart(self):
        from pico.serial_bridge import SerialBridge

        uart = FakeUART()
        bridge = SerialBridge(FakeCDC(), uart)

        written = bridge.inject_button_press(2)

        self.assertEqual(written, len(build_button_press(2)))
        self.assertEqual(uart.writes, [build_button_press(2)])

    def test_inject_button_press_tolerates_uart_write_failure(self):
        from pico.serial_bridge import SerialBridge

        bridge = SerialBridge(FakeCDC(), FailingUART())

        written = bridge.inject_button_press(2)

        self.assertEqual(written, 0)


if __name__ == "__main__":
    unittest.main()
