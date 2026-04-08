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
import time
from typing import Callable, Optional

from serial.tools import list_ports

from core.protocol import build_context_new, build_context_update, PKT_DEBUG, PacketParser

logger = logging.getLogger(__name__)

DEFAULT_BAUD = 115200
SPARK_VID = 0xC4C4
SPARK_PID = 0x5350
ACK = b"\x06"
EOT = b"\x04"
RECONNECT_COOLDOWN_S = 3.0  # minimum seconds between connect() attempts


class SerialSender:
    """Thread-safe serial bridge for the SPARK Pico CDC interface."""

    @staticmethod
    def _sort_port_candidates(devices: list[str]) -> list[str]:
        if not sys.platform.startswith("win"):
            return sorted(devices)

        def sort_key(device: str):
            upper = device.upper()
            if upper.startswith("COM"):
                suffix = upper[3:]
                if suffix.isdigit():
                    return (0, int(suffix))
            return (1, upper)

        return sorted(devices, key=sort_key)

    def __init__(self, port: Optional[str] = None, baud: int = DEFAULT_BAUD):
        self._port = port
        self._baud = baud
        self._serial = None
        self._lock = threading.Lock()
        self._stream_callback: Optional[Callable[[bytes], None]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()
        self._paused = threading.Event()
        self._last_connect_attempt: float = 0.0
        self._debug_parser = PacketParser(on_packet=self._on_pico_packet)
        self._debug_logger = logging.getLogger("pico.debug")

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
            return SerialSender._sort_port_candidates(preferred)[0]

        if sys.platform == "darwin":
            candidates = fallback or glob.glob("/dev/tty.usbmodem*")
        elif sys.platform.startswith("win"):
            candidates = fallback or [f"COM{i}" for i in range(1, 20)]
        else:
            candidates = fallback or glob.glob("/dev/ttyACM*")

        sorted_candidates = SerialSender._sort_port_candidates(candidates)
        return sorted_candidates[0] if sorted_candidates else None

    def connect(self) -> bool:
        # Skip if already connected
        if self._serial and self._serial.is_open:
            self.start_reader()
            return True

        # Cooldown: don't hammer USB bus with repeated scans
        now = time.monotonic()
        if now - self._last_connect_attempt < RECONNECT_COOLDOWN_S:
            return False
        self._last_connect_attempt = now

        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed - run: pip install pyserial")
            return False

        with self._lock:

            port = self._port or self._find_pico_port()
            if not port:
                logger.warning("SerialSender: no Pico port found")
                return False

            try:
                self._serial = serial.Serial(port, self._baud, timeout=0.1, write_timeout=2.0)
            except Exception as exc:
                logger.warning("SerialSender: open failed - %s", exc)
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
                logger.warning("SerialSender: write error - %s", exc)
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
                logger.warning("SerialSender: read error - %s", exc)
                self._serial = None
                return b""

        filtered = bytes(byte for byte in chunk if byte != ACK[0])
        if filtered:
            self._debug_parser.feed(filtered)
            if self._stream_callback:
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

    def _on_pico_packet(self, pkt: dict) -> None:
        if pkt.get("type") == PKT_DEBUG:
            self._debug_logger.info("[PICO] %s", pkt.get("msg", ""))

    def pause(self) -> None:
        """Suppress context sends and release the serial port so other tools can use it."""
        self._paused.set()
        self._stop_reader.set()
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
        logger.info("SerialSender: paused and port released")

    def resume(self) -> None:
        """Re-enable context sends and reopen the serial port."""
        self._paused.clear()
        self._stop_reader.clear()
        self.connect()
        logger.info("SerialSender: resumed")

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
        if self._paused.is_set():
            return False
        return self._send(build_context_new(self._snapshot_payload(snapshot)))

    def send_context_update(self, snapshot) -> bool:
        if self._paused.is_set():
            return False
        return self._send(build_context_update(self._snapshot_payload(snapshot)))
