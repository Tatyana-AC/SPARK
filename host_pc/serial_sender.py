"""
SPARK Host serial bridge for the Pico CDC interface.

The Pico exposes a USB CDC serial port alongside its Raw HID interface. This
module keeps the existing framed WINDOW_NEW / WINDOW_UPDATE helpers and also
supports raw bidirectional byte streaming for the summarize flow.

Requires pyserial: pip install pyserial
"""

import glob
import logging
import sys
import threading
import time
from typing import Callable, Optional

from serial.tools import list_ports

from core.protocol import build_window_new, build_window_update

logger = logging.getLogger(__name__)

DEFAULT_BAUD = 115200
SPARK_VID = 0xC4C4
SPARK_PID = 0x5350
ACK = b"\x06"
EOT = b"\x04"


class SerialSender:
    """
    Thread-safe serial bridge for the SPARK Pico CDC interface.

    Existing code may continue sending framed window packets with
    send_window_new() and send_window_update(). New summarize streaming uses
    send_raw() plus a background reader callback.
    """

    def __init__(self, port: Optional[str] = None, baud: int = DEFAULT_BAUD):
        self._port = port
        self._baud = baud
        self._serial = None
        self._lock = threading.Lock()
        self._stream_callback: Optional[Callable[[bytes], None]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()

    @staticmethod
    def _find_pico_port() -> Optional[str]:
        """Return the first serial port that looks like the SPARK Pico."""
        preferred = []
        fallback = []

        for port in list_ports.comports():
            device = getattr(port, "device", None)
            if not device:
                continue

            vid = getattr(port, "vid", None)
            pid = getattr(port, "pid", None)
            description = (getattr(port, "description", "") or "").lower()
            manufacturer = (getattr(port, "manufacturer", "") or "").lower()
            product = (getattr(port, "product", "") or "").lower()

            if vid == SPARK_VID and pid == SPARK_PID:
                preferred.append(device)
                continue

            if "spark" in description or "spark" in manufacturer or "spark" in product:
                preferred.append(device)
                continue

            fallback.append(device)

        if preferred:
            return preferred[0]

        if sys.platform == "darwin":
            candidates = fallback or glob.glob("/dev/tty.usbmodem*")
        elif sys.platform.startswith("win"):
            candidates = fallback or [f"COM{i}" for i in range(1, 20)]
        else:
            candidates = fallback or glob.glob("/dev/ttyACM*")

        return candidates[0] if candidates else None

    def connect(self) -> bool:
        """Open the serial port. Returns True on success."""
        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed - run: pip install pyserial")
            return False

        with self._lock:
            if self._serial and self._serial.is_open:
                self.start_reader()
                return True

            port = self._port or self._find_pico_port()
            if not port:
                logger.warning("SerialSender: no Pico port found")
                return False

            try:
                self._serial = serial.Serial(port, self._baud, timeout=0.1)
            except Exception as exc:
                logger.warning(f"SerialSender: open failed - {exc}")
                return False

        self._stop_reader.clear()
        self.start_reader()
        logger.info("SerialSender: connected on %s @ %s", port, self._baud)
        return True

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def close(self) -> None:
        self._stop_reader.set()
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
        logger.info("SerialSender: closed")

    def set_stream_callback(self, callback: Optional[Callable[[bytes], None]]) -> None:
        self._stream_callback = callback

    def _send(self, packet: bytes) -> bool:
        if not self.is_connected():
            return False

        with self._lock:
            try:
                self._serial.write(packet)
                return True
            except Exception as exc:
                logger.warning(f"SerialSender: write error - {exc}")
                self._serial = None
                return False

    def send_raw(self, payload: bytes, append_eot: bool = False) -> bool:
        if append_eot:
            payload += EOT
        return self._send(payload)

    def read_once(self, max_chunk_size: int = 256) -> bytes:
        if not self.is_connected():
            return b""

        with self._lock:
            try:
                waiting = getattr(self._serial, "in_waiting", 0)
                if waiting <= 0:
                    return b""
                chunk = self._serial.read(min(max_chunk_size, waiting))
            except Exception as exc:
                logger.warning(f"SerialSender: read error - {exc}")
                self._serial = None
                return b""

        filtered = bytes(byte for byte in chunk if byte != ACK[0])
        if filtered and self._stream_callback:
            self._stream_callback(filtered)
        return filtered

    def start_reader(self) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        while not self._stop_reader.is_set():
            if not self.is_connected():
                time.sleep(0.05)
                continue

            chunk = self.read_once()
            if not chunk:
                time.sleep(0.01)

    def send_window_new(self, app_name: str, title: str, text: str) -> bool:
        return self._send(build_window_new(app_name, title, text))

    def send_window_update(self, text: str) -> bool:
        return self._send(build_window_update(text))
