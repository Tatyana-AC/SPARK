try:
    from core.protocol import build_button_press as build_button_press_packet
except ImportError:
    from protocol import build_button_press as build_button_press_packet


class SerialBridge:
    def __init__(self, cdc_data, uart):
        self._cdc_data = cdc_data
        self._uart = uart

    def relay_once(self, max_chunk_size=64):
        available = getattr(self._cdc_data, "in_waiting", 0)
        if available > 0:
            chunk = self._cdc_data.read(min(max_chunk_size, available))
            if chunk:
                self._uart.write(chunk)
                return len(chunk)
        return 0

    def inject_button_press(self, button_id):
        packet = build_button_press_packet(button_id)
        self._uart.write(packet)
        return len(packet)
