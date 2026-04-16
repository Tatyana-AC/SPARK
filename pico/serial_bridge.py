class SerialBridge:
    def __init__(self, cdc_data, uart):
        self._cdc_data = cdc_data
        self._uart = uart

    def relay_once(self, max_chunk_size=64):
        available = getattr(self._cdc_data, "in_waiting", 0)
        if available <= 0:
            return 0

        read_size = min(max_chunk_size, available)
        chunk = self._cdc_data.read(read_size)
        if chunk:
            offset = 0
            while offset < len(chunk):
                written = self._uart.write(chunk[offset:])
                if written is None:
                    written = 0
                written = int(written)
                if written <= 0:
                    raise OSError("uart write returned no progress")
                offset += written
            return len(chunk)
        return 0
