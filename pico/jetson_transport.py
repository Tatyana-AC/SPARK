from __future__ import annotations

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
    def __init__(self, uart):
        self._uart = uart
        self._response = bytearray()
        self.request_active = False
        self.response_complete = False
        self._parser = PacketParser(on_packet=self._handle_packet)

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
        self._uart.write(build_summarize_request(request_text))

    def poll(self, max_chunk_size=64):
        chunk = self._uart.read(max_chunk_size)
        if not chunk:
            return 0
        self._parser.feed(chunk)
        return len(chunk)

    def _handle_packet(self, pkt):
        pkt_type = pkt["type"]
        if pkt_type == PKT_SUMMARIZE_CHUNK:
            self._response.extend((pkt.get("text") or "").encode("utf-8"))
            return
        if pkt_type == PKT_SUMMARIZE_DONE:
            self.request_active = False
            self.response_complete = True
            return
        if pkt_type == PKT_ERROR:
            self._response = bytearray((pkt.get("message") or "").encode("utf-8"))
            self.request_active = False
            self.response_complete = True
