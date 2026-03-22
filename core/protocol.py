"""
SPARK distributed protocol — shared packet definitions.

All multi-byte fields are little-endian.

Wire format
───────────
  ┌──────────┬──────┬────────┬─────────────┬──────┐
  │ MAGIC    │ TYPE │ LEN    │ PAYLOAD      │ CRC8 │
  │ 2 bytes  │ 1 B  │ 2 B LE │ LEN bytes    │ 1 B  │
  └──────────┴──────┴────────┴─────────────┴──────┘

C equivalent (firmware side):

    typedef struct __attribute__((packed)) {
        uint8_t  magic[2];    // { 0x53, 0x50 }  i.e. 'S', 'P'
        uint8_t  type;
        uint16_t length;      // little-endian payload byte count
    } spark_header_t;         // 5 bytes

    // Footer — 1 byte appended after payload
    uint8_t crc8;

Packet types and their payload layouts
───────────────────────────────────────
  0x01  WINDOW_NEW

        typedef struct __attribute__((packed)) {
            uint8_t  app_name_len;
            char     app_name[app_name_len];   // UTF-8, no null terminator
            uint8_t  title_len;
            char     title[title_len];
            uint16_t text_len;                 // little-endian
            char     text[text_len];
        } spark_window_new_t;

  0x02  WINDOW_UPDATE

        typedef struct __attribute__((packed)) {
            uint16_t text_len;                 // little-endian
            char     text[text_len];
        } spark_window_update_t;

  0x05  BUTTON_PRESS

        typedef struct __attribute__((packed)) {
            uint8_t button_id;                 // 0–3
        } spark_button_press_t;

CRC: CRC-8/MAXIM (poly 0x31, reflected).  Computed over the entire packet
     excluding the CRC byte itself (i.e. over magic+type+length+payload).
"""

import struct

# ── Constants ────────────────────────────────────────────────────

MAGIC             = b'SP'       # 0x53 0x50

PKT_WINDOW_NEW    = 0x01
PKT_WINDOW_UPDATE = 0x02
PKT_BUTTON_PRESS  = 0x05

# struct format strings — '<' = little-endian, matching C packed structs
_HEADER_FMT = '<2sBH'           # magic[2] + type(B) + payload_len(H)
_CRC_FMT    = '<B'              # trailing CRC byte

HEADER_SIZE = struct.calcsize(_HEADER_FMT)   # 5 bytes
FOOTER_SIZE = struct.calcsize(_CRC_FMT)      # 1 byte
OVERHEAD    = HEADER_SIZE + FOOTER_SIZE      # 6 bytes


# ── CRC-8/MAXIM  (poly=0x31, reflected) ─────────────────────────
# C equivalent:
#   uint8_t crc8(const uint8_t *data, size_t len) {
#       uint8_t crc = 0;
#       for (size_t i = 0; i < len; i++) {
#           crc ^= data[i];
#           for (int b = 0; b < 8; b++)
#               crc = (crc & 1) ? (crc >> 1) ^ 0x8C : (crc >> 1);
#       }
#       return crc;
#   }

def _crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc & 0xFF


# ── Packet building ──────────────────────────────────────────────

def build_packet(pkt_type: int, payload: bytes) -> bytes:
    """Wrap a raw payload in the SPARK wire frame."""
    header = struct.pack(_HEADER_FMT, MAGIC, pkt_type, len(payload))
    body   = header + payload
    return body + struct.pack(_CRC_FMT, _crc8(body))


def build_window_new(app_name: str, title: str, text: str) -> bytes:
    app_b   = app_name.encode('utf-8')[:255]
    title_b = title.encode('utf-8')[:255]
    text_b  = text.encode('utf-8')
    payload = (
        struct.pack('<B', len(app_b))   + app_b   +   # uint8_t  len + chars
        struct.pack('<B', len(title_b)) + title_b +   # uint8_t  len + chars
        struct.pack('<H', len(text_b))  + text_b      # uint16_t len + chars (LE)
    )
    return build_packet(PKT_WINDOW_NEW, payload)


def build_window_update(text: str) -> bytes:
    text_b = text.encode('utf-8')
    payload = struct.pack('<H', len(text_b)) + text_b  # uint16_t len + chars (LE)
    return build_packet(PKT_WINDOW_UPDATE, payload)


def build_button_press(button_id: int) -> bytes:
    return build_packet(PKT_BUTTON_PRESS, struct.pack('<B', button_id))


# ── Packet parsing ───────────────────────────────────────────────

def _unpack_str8(data: bytes, offset: int):
    """Read a uint8_t-prefixed string.  Returns (str, new_offset)."""
    (n,) = struct.unpack_from('<B', data, offset)
    s    = data[offset + 1 : offset + 1 + n].decode('utf-8', 'replace')
    return s, offset + 1 + n


def _unpack_str16(data: bytes, offset: int):
    """Read a uint16_t LE-prefixed string.  Returns (str, new_offset)."""
    (n,) = struct.unpack_from('<H', data, offset)
    s    = data[offset + 2 : offset + 2 + n].decode('utf-8', 'replace')
    return s, offset + 2 + n


def _parse_payload(pkt_type: int, payload: bytes):
    """Decode a payload into a dict.  Returns None on error."""
    try:
        if pkt_type == PKT_WINDOW_NEW:
            app_name, off = _unpack_str8(payload, 0)
            title,    off = _unpack_str8(payload, off)
            text,     _   = _unpack_str16(payload, off)
            return {'type': pkt_type, 'app_name': app_name,
                    'title': title, 'text': text}

        if pkt_type == PKT_WINDOW_UPDATE:
            text, _ = _unpack_str16(payload, 0)
            return {'type': pkt_type, 'text': text}

        if pkt_type == PKT_BUTTON_PRESS:
            (button_id,) = struct.unpack_from('<B', payload, 0)
            return {'type': pkt_type, 'button_id': button_id}

    except struct.error:
        pass
    return None


# ── Streaming parser ─────────────────────────────────────────────

class PacketParser:
    """
    Streaming parser — feed bytes in any chunk size via feed().
    on_packet(dict) fires for every valid, CRC-checked packet.

    Works on CPython 3.x and MicroPython (struct is available on both).
    """

    _SYNC   = 0
    _HEADER = 1
    _BODY   = 2

    def __init__(self, on_packet=None):
        self.on_packet = on_packet
        self._buf      = bytearray()
        self._state    = self._SYNC
        self._pkt_type = 0
        self._pkt_len  = 0

    def feed(self, data):
        for byte in data:
            self._buf.append(byte)

            if self._state == self._SYNC:
                if len(self._buf) >= 2 and self._buf[-2] == 0x53 and self._buf[-1] == 0x50:
                    self._buf   = bytearray(MAGIC)
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

    def _dispatch(self):
        header_and_payload = bytes(self._buf[:-1])
        (received_crc,)    = struct.unpack_from(_CRC_FMT, self._buf, len(self._buf) - 1)

        if _crc8(header_and_payload) != received_crc:
            self._reset()
            return

        payload = bytes(self._buf[HEADER_SIZE : HEADER_SIZE + self._pkt_len])
        pkt     = _parse_payload(self._pkt_type, payload)
        if pkt is not None and self.on_packet:
            self.on_packet(pkt)
        self._reset()

    def _reset(self):
        self._buf   = bytearray()
        self._state = self._SYNC
