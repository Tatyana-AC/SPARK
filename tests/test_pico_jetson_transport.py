import unittest

from core.protocol import build_error, build_summarize_chunk, build_summarize_done, build_summarize_request


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
    def test_start_request_writes_framed_summarize_request(self):
        from pico.jetson_transport import JetsonTransport

        uart = FakeUart()
        transport = JetsonTransport(uart)

        transport.start_request("hello jetson")

        self.assertEqual(uart.writes, [build_summarize_request("hello jetson")])
        self.assertTrue(transport.request_active)
        self.assertFalse(transport.response_complete)
        self.assertEqual(transport.response_bytes, b"")

    def test_poll_accumulates_chunk_packets_until_done(self):
        from pico.jetson_transport import JetsonTransport

        uart = FakeUart()
        transport = JetsonTransport(uart)
        transport.start_request("summarize this")

        uart.queue_read(build_summarize_chunk("Partial "))
        transport.poll()
        self.assertEqual(transport.response_bytes, b"Partial ")
        self.assertTrue(transport.request_active)
        self.assertFalse(transport.response_complete)

        uart.queue_read(build_summarize_chunk("response") + build_summarize_done())
        transport.poll(256)

        self.assertEqual(transport.response_bytes, b"Partial response")
        self.assertFalse(transport.request_active)
        self.assertTrue(transport.response_complete)

    def test_error_packet_finishes_request_with_message(self):
        from pico.jetson_transport import JetsonTransport

        uart = FakeUart()
        transport = JetsonTransport(uart)
        transport.start_request("summarize this")

        uart.queue_read(build_error("summarize failed"))
        transport.poll()

        self.assertEqual(transport.response_bytes, b"summarize failed")
        self.assertFalse(transport.request_active)
        self.assertTrue(transport.response_complete)


if __name__ == "__main__":
    unittest.main()
