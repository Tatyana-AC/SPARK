ACK = b"\x06"
EOT = b"\x04"


class JetsonTransport:
    def __init__(self, uart):
        self._uart = uart
        self._response = bytearray()
        self._awaiting_ack = False
        self.request_active = False
        self.response_complete = False

    @property
    def response_bytes(self):
        return bytes(self._response)

    @property
    def response_len(self):
        return len(self._response)

    def start_request(self, payload):
        if self.request_active:
            raise RuntimeError("busy")

        self._response = bytearray()
        self._awaiting_ack = True
        self.request_active = True
        self.response_complete = False
        frame = bytearray(payload)
        frame.extend(EOT)
        self._uart.write(frame)

    def poll(self, max_chunk_size=64):
        chunk = self._uart.read(max_chunk_size)
        if not chunk:
            return 0

        consumed = 0
        for byte in chunk:
            if self._awaiting_ack and byte == ACK[0]:
                self._awaiting_ack = False
                consumed += 1
                continue

            self._awaiting_ack = False

            if byte == EOT[0]:
                self.request_active = False
                self.response_complete = True
                consumed += 1
                break

            self._response.append(byte)
            consumed += 1

        return consumed
