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


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


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

    def test_request_timeout_finishes_stuck_request_with_error(self):
        from pico.jetson_transport import JetsonTransport

        uart = FakeUart()
        clock = FakeClock()
        transport = JetsonTransport(
            uart,
            request_timeout_s=5.0,
            max_request_retries=0,
            time_source=clock,
        )
        transport.start_request("summarize this")

        clock.advance(6.0)
        transport.poll()

        self.assertFalse(transport.request_active)
        self.assertTrue(transport.response_complete)
        self.assertIn(b"timed out", transport.response_bytes)

    def test_timeout_uses_last_chunk_activity_before_failing(self):
        from pico.jetson_transport import JetsonTransport

        uart = FakeUart()
        clock = FakeClock()
        transport = JetsonTransport(
            uart,
            request_timeout_s=5.0,
            max_request_retries=0,
            time_source=clock,
        )
        transport.start_request("summarize this")

        clock.advance(3.0)
        uart.queue_read(build_summarize_chunk("Partial "))
        transport.poll()

        self.assertTrue(transport.request_active)
        self.assertEqual(transport.response_bytes, b"Partial ")

        clock.advance(6.0)
        transport.poll()

        self.assertFalse(transport.request_active)
        self.assertTrue(transport.response_complete)
        self.assertIn(b"Partial ", transport.response_bytes)
        self.assertIn(b"timed out", transport.response_bytes)

    def test_request_retries_once_before_timeout(self):
        from pico.jetson_transport import JetsonTransport

        uart = FakeUart()
        clock = FakeClock()
        transport = JetsonTransport(
            uart,
            request_timeout_s=10.0,
            request_retry_s=2.0,
            max_request_retries=1,
            time_source=clock,
        )
        transport.start_request("summarize this")

        self.assertEqual(len(uart.writes), 1)

        clock.advance(2.1)
        transport.poll()

        self.assertEqual(len(uart.writes), 2)
        self.assertTrue(transport.request_active)
        self.assertFalse(transport.response_complete)

    def test_request_stops_retrying_after_response_starts(self):
        from pico.jetson_transport import JetsonTransport

        uart = FakeUart()
        clock = FakeClock()
        transport = JetsonTransport(
            uart,
            request_timeout_s=10.0,
            request_retry_s=2.0,
            max_request_retries=2,
            time_source=clock,
        )
        transport.start_request("summarize this")

        clock.advance(1.0)
        uart.queue_read(build_summarize_chunk("Partial "))
        transport.poll()

        clock.advance(3.0)
        transport.poll()

        self.assertEqual(len(uart.writes), 1)
        self.assertEqual(transport.response_bytes, b"Partial ")


if __name__ == "__main__":
    unittest.main()
