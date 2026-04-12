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
        debug_hook=None,
        status_sender=None,
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
        self._debug_hook = debug_hook
        self._status_sender = status_sender
        self._uart_read_count = 0
        self._response_started = False

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
        self._uart_read_count = 0
        self._response_started = False
        self._debug("start_request", payload_len=len(request_text))
        self._send_request()

    def poll(self, max_chunk_size=64):
        self._expire_if_needed()
        chunk = self._uart.read(max_chunk_size)
        if not chunk:
            self._expire_if_needed()
            return 0
        self._last_activity_s = self._time_source()
        self._uart_read_count += 1
        self._debug("uart_read", byte_count=len(chunk))
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
        self._fail_request(
            f"[ERROR] Jetson request timed out (reads={self._uart_read_count}, response_len={len(self._response)})"
        )

    def _send_request(self):
        try:
            self._uart.write(self._request_bytes)
        except Exception as exc:
            self._emit_status(f"[ERROR] Jetson request send failed: {type(exc).__name__}")
            raise
        now = self._time_source()
        self._last_send_s = now
        self._last_activity_s = now
        self._debug("send_request", byte_count=len(self._request_bytes), retry_count=self._retry_count)
        if self._retry_count == 0:
            self._emit_status("[JETSON] Request forwarded")

    def _fail_request(self, message):
        self._emit_status(message)
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
        self._debug("fail_request", message=message, response_len=len(self._response))

    def _debug(self, event, **fields):
        if self._debug_hook is None:
            return
        payload = {"event": event}
        payload.update(fields)
        self._debug_hook(payload)

    def _emit_status(self, message):
        if self._status_sender is None:
            return
        self._status_sender(message)

    def _handle_packet(self, pkt):
        pkt_type = pkt["type"]
        if pkt_type == PKT_SUMMARIZE_CHUNK:
            if not self.request_active:
                return  # discard stale chunk from a previous request/retry
            self._last_activity_s = self._time_source()
            text = pkt.get("text") or ""
            if not self._response_started:
                self._response_started = True
                self._emit_status("[JETSON] Response started")
            self._response.extend(text.encode("utf-8"))
            self._debug("recv_chunk", chunk_len=len(text), response_len=len(self._response))
            return
        if pkt_type == PKT_SUMMARIZE_DONE:
            if not self.request_active:
                return  # discard stale done from a previous request/retry
            self._last_activity_s = self._time_source()
            self.request_active = False
            self.response_complete = True
            self._request_bytes = b""
            self._retry_count = 0
            self._debug("recv_done", response_len=len(self._response))
            return
        if pkt_type == PKT_ERROR:
            if not self.request_active:
                return  # discard stale error from a previous request/retry
            self._last_activity_s = self._time_source()
            self._debug("recv_error", message=pkt.get("message") or "[ERROR] Jetson bridge error")
            self._fail_request(pkt.get("message") or "[ERROR] Jetson bridge error")
