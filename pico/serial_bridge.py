import struct


def _crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x01:
                crc = (crc >> 1) ^ 0x8C
            else:
                crc >>= 1
    return crc & 0xFF


def build_button_press_packet(button_id):
    payload = struct.pack("<B", button_id)
    header = struct.pack("<2sBH", b"SP", 0x05, len(payload))
    body = header + payload
    return body + struct.pack("<B", _crc8(body))


class SerialBridge:
    def __init__(self, cdc_data, uart):
        self._cdc_data = cdc_data
        self._uart = uart

    def relay_once(self, max_chunk_size=64):
        if getattr(self._cdc_data, "in_waiting", 0) <= 0:
            return 0
        chunk = self._cdc_data.read(max_chunk_size)
        if not chunk:
            return 0
        self._uart.write(chunk)
        return len(chunk)

    def inject_button_press(self, button_id):
        packet = build_button_press_packet(button_id)
        self._uart.write(packet)
        return len(packet)
