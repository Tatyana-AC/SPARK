import unittest


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


class PartialWriteUART(FakeUART):
    def __init__(self, accepted_sizes, payload=b""):
        super().__init__(payload=payload)
        self._accepted_sizes = list(accepted_sizes)

    def write(self, data):
        accepted = self._accepted_sizes.pop(0) if self._accepted_sizes else len(data)
        accepted = max(0, min(int(accepted), len(data)))
        self.writes.append(bytes(data[:accepted]))
        return accepted


class SerialBridgeTests(unittest.TestCase):
    def test_relay_once_forwards_cdc_bytes_to_uart_in_bounded_chunk(self):
        from pico.serial_bridge import SerialBridge

        cdc = FakeCDC(b"abcdefghijklmnopqrstuvwxyz")
        uart = FakeUART()
        bridge = SerialBridge(cdc, uart)

        written = bridge.relay_once(max_chunk_size=8)

        self.assertEqual(written, 8)
        self.assertEqual(uart.writes, [b"abcdefgh"])
        self.assertEqual(cdc.in_waiting, 18)

    def test_relay_once_retries_until_full_chunk_is_written_to_uart(self):
        from pico.serial_bridge import SerialBridge

        cdc = FakeCDC(b"abcdefgh")
        uart = PartialWriteUART([3, 3, 2])
        bridge = SerialBridge(cdc, uart)

        written = bridge.relay_once(max_chunk_size=8)

        self.assertEqual(written, 8)
        self.assertEqual(uart.writes, [b"abc", b"def", b"gh"])
        self.assertEqual(cdc.in_waiting, 0)

    def test_relay_once_does_not_consume_uart_response_bytes(self):
        from pico.serial_bridge import SerialBridge

        cdc = FakeCDC()
        uart = FakeUART(b"summary")
        bridge = SerialBridge(cdc, uart)

        written = bridge.relay_once(max_chunk_size=8)

        self.assertEqual(written, 0)
        self.assertEqual(cdc.writes, [])
        self.assertEqual(uart.in_waiting, 7)

    def test_relay_once_skips_read_when_cdc_in_waiting_is_zero(self):
        from pico.serial_bridge import SerialBridge

        class _ZeroWaitingCDC(FakeCDC):
            def __init__(self, payload=b""):
                super().__init__(payload)
                self.read_calls = []

            @property
            def in_waiting(self):
                return 0

            def read(self, count):
                self.read_calls.append(count)
                return super().read(count)

        cdc = _ZeroWaitingCDC(b"context-packet")
        uart = FakeUART()
        bridge = SerialBridge(cdc, uart)

        written = bridge.relay_once(max_chunk_size=8)

        self.assertEqual(written, 0)
        self.assertEqual(uart.writes, [])
        self.assertEqual(cdc.read_calls, [])

    def test_serial_bridge_has_no_button_injection_helper(self):
        from pico.serial_bridge import SerialBridge

        bridge = SerialBridge(FakeCDC(), FakeUART())

        self.assertFalse(hasattr(bridge, "inject_button_press"))


if __name__ == "__main__":
    unittest.main()
