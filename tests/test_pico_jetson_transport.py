import unittest


class FakeUart:
    def __init__(self):
        self.writes = []
        self._read_buffer = bytearray()

    @property
    def in_waiting(self):
        return len(self._read_buffer)

    def write(self, payload):
        self.writes.append(bytes(payload))
        return len(payload)

    def read(self, size):
        chunk = bytes(self._read_buffer[:size])
        del self._read_buffer[:size]
        return chunk

    def queue_read(self, payload):
        self._read_buffer.extend(payload)


class JetsonTransportTests(unittest.TestCase):
    def test_start_request_writes_payload_and_eot(self):
        from pico.jetson_transport import EOT, JetsonTransport

        uart = FakeUart()
        transport = JetsonTransport(uart)

        transport.start_request(b"hello jetson")

        self.assertEqual(uart.writes, [b"hello jetson" + EOT])
        self.assertTrue(transport.request_active)
        self.assertFalse(transport.response_complete)
        self.assertEqual(transport.response_bytes, b"")

    def test_poll_ignores_ack_and_appends_streamed_bytes_until_eot(self):
        from pico.jetson_transport import ACK, EOT, JetsonTransport

        uart = FakeUart()
        transport = JetsonTransport(uart)
        transport.start_request(b"summarize this")

        uart.queue_read(ACK + b"Partial ")
        transport.poll()
        self.assertEqual(transport.response_bytes, b"Partial ")
        self.assertTrue(transport.request_active)
        self.assertFalse(transport.response_complete)

        uart.queue_read(b"response" + EOT)
        transport.poll()

        self.assertEqual(transport.response_bytes, b"Partial response")
        self.assertFalse(transport.request_active)
        self.assertTrue(transport.response_complete)


if __name__ == "__main__":
    unittest.main()
