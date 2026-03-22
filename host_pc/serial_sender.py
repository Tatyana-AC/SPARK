"""
SPARK Host — serial packet sender to the Pico Hub.

Sends WINDOW_NEW (0x01) and WINDOW_UPDATE (0x02) packets over USB CDC serial.
Requires pyserial:  pip install pyserial
"""

import glob
import logging
import sys
import threading
from typing import Optional

from core.protocol import build_window_new, build_window_update

logger = logging.getLogger(__name__)

DEFAULT_BAUD = 115200


class SerialSender:
    """
    Thread-safe serial writer for the SPARK Hub-and-Spoke protocol.

    Call connect() once; then call send_window_new() on context switch and
    send_window_update() on every poll tick (8 Hz) to keep the Jetson
    Brain in sync.
    """

    def __init__(self, port: Optional[str] = None, baud: int = DEFAULT_BAUD):
        self._port   = port          # None → auto-detect Pico
        self._baud   = baud
        self._serial = None
        self._lock   = threading.Lock()

    # ── Connection ───────────────────────────────────────────────

    @staticmethod
    def _find_pico_port() -> Optional[str]:
        """Return the first USB CDC serial port that looks like a Pico."""
        if sys.platform == 'darwin':
            candidates = glob.glob('/dev/tty.usbmodem*')
        elif sys.platform.startswith('win'):
            candidates = [f'COM{i}' for i in range(1, 20)]
        else:
            candidates = glob.glob('/dev/ttyACM*')
        return candidates[0] if candidates else None

    def connect(self) -> bool:
        """Open the serial port.  Returns True on success."""
        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed — run: pip install pyserial")
            return False

        with self._lock:
            if self._serial and self._serial.is_open:
                return True

            port = self._port or self._find_pico_port()
            if not port:
                logger.warning("SerialSender: no Pico port found")
                return False

            try:
                import serial as _serial
                self._serial = _serial.Serial(port, self._baud, timeout=1)
                logger.info(f"SerialSender: connected on {port} @ {self._baud}")
                return True
            except Exception as exc:
                logger.warning(f"SerialSender: open failed — {exc}")
                return False

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def close(self) -> None:
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
        logger.info("SerialSender: closed")

    # ── Internal write ───────────────────────────────────────────

    def _send(self, packet: bytes) -> bool:
        if not self.is_connected():
            return False
        with self._lock:
            try:
                self._serial.write(packet)
                return True
            except Exception as exc:
                logger.warning(f"SerialSender: write error — {exc}")
                self._serial = None   # mark disconnected; caller may reconnect
                return False

    # ── Public API ───────────────────────────────────────────────

    def send_window_new(self, app_name: str, title: str, text: str) -> bool:
        """Send WINDOW_NEW (0x01) — call on every context switch."""
        return self._send(build_window_new(app_name, title, text))

    def send_window_update(self, text: str) -> bool:
        """Send WINDOW_UPDATE (0x02) — call at 8 Hz while context unchanged."""
        return self._send(build_window_update(text))
