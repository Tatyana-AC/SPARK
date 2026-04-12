"""
Local copy of the shared SPARK framed packet contract for Jetson deployment.

This lets the `jetson/` folder be copied directly into the bridge folder on the
Jetson without depending on the repo root package layout.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Callable

MAGIC = b"SP"
PROTOCOL_VERSION = 0x01

PKT_CONTEXT_NEW = 0x01
PKT_CONTEXT_UPDATE = 0x02
PKT_SUMMARIZE_REQUEST = 0x03
PKT_SUMMARIZE_CHUNK = 0x04
PKT_BUTTON_PRESS = 0x05
PKT_SUMMARIZE_DONE = 0x06
PKT_ERROR = 0x07

_HEADER_FMT = "<2sBH"
_CRC_FMT = "<B"

HEADER_SIZE = struct.calcsize(_HEADER_FMT)
FOOTER_SIZE = struct.calcsize(_CRC_FMT)

_JSON_PACKET_TYPES = {
    PKT_CONTEXT_NEW,
    PKT_CONTEXT_UPDATE,
    PKT_SUMMARIZE_REQUEST,
    PKT_SUMMARIZE_CHUNK,
    PKT_SUMMARIZE_DONE,
    PKT_ERROR,
}


def _crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc & 0xFF


def build_packet(pkt_type: int, payload: bytes) -> bytes:
    header = struct.pack(_HEADER_FMT, MAGIC, pkt_type, len(payload))
    body = header + payload
    return body + struct.pack(_CRC_FMT, _crc8(body))


def _json_payload(data: dict[str, Any]) -> bytes:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return bytes([PROTOCOL_VERSION]) + encoded


def _build_json_packet(pkt_type: int, payload: dict[str, Any]) -> bytes:
    return build_packet(pkt_type, _json_payload(payload))


def build_summarize_chunk(text: str) -> bytes:
    return _build_json_packet(PKT_SUMMARIZE_CHUNK, {"text": text})


def build_summarize_done() -> bytes:
    return _build_json_packet(PKT_SUMMARIZE_DONE, {"done": True})


def build_error(message: str) -> bytes:
    return _build_json_packet(PKT_ERROR, {"message": message})


class PacketParser:
    _SYNC = 0
    _HEADER = 1
    _BODY = 2

    def __init__(
        self,
        on_packet: Callable[[dict[str, Any]], None] | None = None,
        diagnostic_hook: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.on_packet = on_packet
        self.diagnostic_hook = diagnostic_hook
        self._buf = bytearray()
        self._state = self._SYNC
        self._pkt_type = 0
        self._pkt_len = 0

    def feed(self, data: bytes) -> None:
        for byte in data:
            self._buf.append(byte)

            if self._state == self._SYNC:
                if len(self._buf) >= 2 and self._buf[-2] == 0x53 and self._buf[-1] == 0x50:
                    self._buf = bytearray(MAGIC)
                    self._state = self._HEADER
                elif len(self._buf) > 2:
                    self._buf = bytearray([self._buf[-1]])
            elif self._state == self._HEADER:
                if len(self._buf) == HEADER_SIZE:
                    _, self._pkt_type, self._pkt_len = struct.unpack_from(
                        _HEADER_FMT, bytes(self._buf), 0
                    )
                    self._state = self._BODY
            elif self._state == self._BODY:
                if len(self._buf) == HEADER_SIZE + self._pkt_len + FOOTER_SIZE:
                    self._dispatch()

    def _dispatch(self) -> None:
        header_and_payload = bytes(self._buf[:-1])
        (received_crc,) = struct.unpack_from(_CRC_FMT, self._buf, len(self._buf) - 1)

        if _crc8(header_and_payload) != received_crc:
            self._diagnose("crc_mismatch", pkt_type=self._pkt_type, pkt_len=self._pkt_len)
            self._reset()
            return

        payload = bytes(self._buf[HEADER_SIZE : HEADER_SIZE + self._pkt_len])
        pkt = self._parse_payload(self._pkt_type, payload)
        if pkt is not None and self.on_packet:
            self.on_packet(pkt)
        self._reset()

    def _parse_payload(self, pkt_type: int, payload: bytes) -> dict[str, Any] | None:
        if pkt_type in _JSON_PACKET_TYPES:
            if not payload:
                self._diagnose("invalid_payload", pkt_type=pkt_type, reason="empty_json_payload")
                return None
            version = payload[0]
            if version != PROTOCOL_VERSION:
                self._diagnose("invalid_payload", pkt_type=pkt_type, reason="version_mismatch")
                return None
            try:
                data = json.loads(payload[1:].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._diagnose("invalid_payload", pkt_type=pkt_type, reason="json_decode_failed")
                return None
            if not isinstance(data, dict):
                self._diagnose("invalid_payload", pkt_type=pkt_type, reason="json_not_object")
                return None
            data["type"] = pkt_type
            return data
        if pkt_type == PKT_BUTTON_PRESS:
            try:
                (button_id,) = struct.unpack_from("<B", payload, 0)
            except struct.error:
                self._diagnose("invalid_payload", pkt_type=pkt_type, reason="button_payload_short")
                return None
            return {"type": pkt_type, "button_id": button_id}
        return None

    def _diagnose(self, event: str, **fields: Any) -> None:
        if self.diagnostic_hook is None:
            return
        payload = {"event": event}
        payload.update(fields)
        self.diagnostic_hook(payload)

    def _reset(self) -> None:
        self._buf = bytearray()
        self._state = self._SYNC
