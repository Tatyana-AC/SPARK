from __future__ import annotations

import time

try:
    from core.protocol import (
        PacketParser,
        PKT_ERROR,
        PKT_SUMMARIZE_CHUNK,
        PKT_SUMMARIZE_DONE,
        build_summarize_request,
    )
except ImportError:
    from protocol import (
        PacketParser,
        PKT_ERROR,
        PKT_SUMMARIZE_CHUNK,
        PKT_SUMMARIZE_DONE,
        build_summarize_request,
    )


class JetsonTransport:
    def __init__(
        self,
        uart,
        request_timeout_s=30.0,
        request_retry_s=2.0,
        max_request_retries=1,
        time_source=None,
    ):
        self._uart = uart
        self._response = bytearray()
        self.request_active = False
        self.response_complete = False
        self._parser = PacketParser(on_packet=self._handle_packet)
        self._request_timeout_s = float(request_timeout_s)
        self._request_retry_s = float(request_retry_s)
        self._max_request_retries = int(max_request_retries)
        self._time_source = time_source or time.monotonic
        self._last_activity_s = 0.0
        self._last_send_s = 0.0
        self._request_bytes = b""
        self._retry_count = 0

    @property
    def response_bytes(self):
        return bytes(self._response)

    @property
    def response_len(self):
        return len(self._response)

    def start_request(self, payload):
        if self.request_active:
            raise RuntimeError("busy")

        if isinstance(payload, bytes):
            request_text = payload.decode("utf-8")
        else:
            request_text = str(payload)

        self._response = bytearray()
        self.request_active = True
        self.response_complete = False
        self._last_activity_s = self._time_source()
        self._request_bytes = build_summarize_request(request_text)
        self._retry_count = 0
        self._send_request()

    def poll(self, max_chunk_size=64):
        self._expire_if_needed()
        chunk = self._uart.read(max_chunk_size)
        if not chunk:
            self._expire_if_needed()
            return 0
        self._last_activity_s = self._time_source()
        self._parser.feed(chunk)
        return len(chunk)

    def _expire_if_needed(self):
        if not self.request_active:
            return
        if self.response_complete:
            return
        if (
            not self._response
            and
            self._retry_count < self._max_request_retries
            and (self._time_source() - self._last_send_s) >= self._request_retry_s
        ):
            self._retry_count += 1
            self._send_request()
            return
        if (self._time_source() - self._last_activity_s) < self._request_timeout_s:
            return
        self._fail_request("[ERROR] Jetson request timed out")

    def _send_request(self):
        self._uart.write(self._request_bytes)
        now = self._time_source()
        self._last_send_s = now
        self._last_activity_s = now

    def _fail_request(self, message):
        existing = bytes(self._response)
        if existing:
            combined = existing + b"\n" + message.encode("utf-8")
        else:
            combined = message.encode("utf-8")
        self._response = bytearray(combined)
        self.request_active = False
        self.response_complete = True
        self._request_bytes = b""
        self._retry_count = 0

    def _handle_packet(self, pkt):
        pkt_type = pkt["type"]
        if pkt_type == PKT_SUMMARIZE_CHUNK:
            self._last_activity_s = self._time_source()
            self._response.extend((pkt.get("text") or "").encode("utf-8"))
            return
        if pkt_type == PKT_SUMMARIZE_DONE:
            self._last_activity_s = self._time_source()
            self.request_active = False
            self.response_complete = True
            self._request_bytes = b""
            self._retry_count = 0
            return
        if pkt_type == PKT_ERROR:
            self._last_activity_s = self._time_source()
            self._fail_request(pkt.get("message") or "[ERROR] Jetson bridge error")
