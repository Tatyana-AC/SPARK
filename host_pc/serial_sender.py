"""
SPARK Host serial bridge for the Pico CDC interface.

The host uses USB CDC for continuous context transmission toward the Pico and
Jetson path. Summarize requests continue to use Raw HID on the host side.
"""

from __future__ import annotations

import glob
import logging
import sys
import threading
from typing import Optional

from serial.tools import list_ports

from core.protocol import build_context_new, build_context_update

logger = logging.getLogger(__name__)

DEFAULT_BAUD = 115200
SPARK_VID = 0xC4C4
SPARK_PID = 0x5350


class SerialSender:
    """Thread-safe serial bridge for the SPARK Pico CDC interface."""

    def __init__(self, port: Optional[str] = None, baud: int = DEFAULT_BAUD):
        self._port = port
        self._baud = baud
        self._serial = None
        self._lock = threading.Lock()

    @staticmethod
    def _find_pico_port() -> Optional[str]:
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
        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed - run: pip install pyserial")
            return False

        with self._lock:
            if self._serial and self._serial.is_open:
                return True

            port = self._port or self._find_pico_port()
            if not port:
                logger.warning("SerialSender: no Pico port found")
                return False

            try:
                self._serial = serial.Serial(port, self._baud, timeout=0.1)
            except Exception as exc:
                logger.warning("SerialSender: open failed - %s", exc)
                return False

        logger.info("SerialSender: connected on %s @ %s", port, self._baud)
        return True

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

    def _send(self, packet: bytes) -> bool:
        if not self.is_connected():
            return False

        with self._lock:
            try:
                self._serial.write(packet)
                return True
            except Exception as exc:
                logger.warning("SerialSender: write error - %s", exc)
                self._serial = None
                return False

    @staticmethod
    def _snapshot_payload(snapshot) -> dict:
        return {
            "app_name": snapshot.window_info.app_name,
            "window_title": snapshot.window_info.title,
            "process_name": snapshot.window_info.process_name,
            "pid": snapshot.window_info.pid,
            "source": snapshot.source.value,
            "tab_title": snapshot.tab_title,
            "url": snapshot.url,
            "text": snapshot.text,
            "timestamp": snapshot.timestamp,
        }

    def send_context_new(self, snapshot) -> bool:
        return self._send(build_context_new(self._snapshot_payload(snapshot)))

    def send_context_update(self, snapshot) -> bool:
        return self._send(build_context_update(self._snapshot_payload(snapshot)))
