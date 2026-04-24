"""
SPARK Host serial bridge for the Pico CDC interface.

The host uses USB CDC for continuous context transmission toward the Pico and
Jetson path. Summarize requests continue to use Raw HID on the host side.
"""

from __future__ import annotations

import glob
import logging
import re
import struct
import sys
import threading
import time
from typing import Callable, Optional

from serial.tools import list_ports

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows platforms
    winreg = None

from core.protocol import build_context_new, build_context_update, PKT_DEBUG, PacketParser

logger = logging.getLogger(__name__)

DEFAULT_BAUD = 115200
SPARK_VID = 0xC4C4
SPARK_PID = 0x5350
ACK = b"\x06"
EOT = b"\x04"
RECONNECT_COOLDOWN_S = 3.0  # minimum seconds between connect() attempts
PORT_FAILURE_COOLDOWN_S = 10.0
_MAX_CONTEXT_PACKET_BYTES = 8192


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

    @staticmethod
    def _preferred_port_from_matches(matches) -> Optional[str]:
        devices = [getattr(port, "device", None) for port in matches]
        devices = [device for device in devices if device]
        if not devices:
            return None

        if sys.platform.startswith("win"):
            serial_numbers = {
                getattr(port, "serial_number", None)
                for port in matches
                if getattr(port, "serial_number", None)
            }
            if len(matches) > 1 and len(serial_numbers) == 1:
                interface_numbers = {
                    device: SerialSender._get_windows_interface_number(device)
                    for device in devices
                }
                if all(number is not None for number in interface_numbers.values()):
                    return min(
                        devices,
                        key=lambda device: (interface_numbers[device], SerialSender._sort_port_candidates([device])[0]),
                    )
                return SerialSender._sort_port_candidates(devices)[-1]

        return SerialSender._sort_port_candidates(devices)[0]

    @staticmethod
    def _get_windows_interface_number(device: str) -> Optional[int]:
        if not sys.platform.startswith("win") or winreg is None:
            return None

        target_device = (device or "").upper()
        usb_enum_path = r"SYSTEM\CurrentControlSet\Enum\USB"
        prefix = f"VID_{SPARK_VID:04X}&PID_{SPARK_PID:04X}"

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, usb_enum_path) as usb_root:
                index = 0
                while True:
                    try:
                        device_key_name = winreg.EnumKey(usb_root, index)
                    except OSError:
                        break
                    index += 1

                    if not device_key_name.upper().startswith(prefix):
                        continue

                    interface_match = re.search(r"MI_(\d{2})", device_key_name, re.IGNORECASE)
                    if interface_match is None:
                        continue

                    device_key_path = f"{usb_enum_path}\\{device_key_name}"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, device_key_path) as device_key:
                            instance_index = 0
                            while True:
                                try:
                                    instance_name = winreg.EnumKey(device_key, instance_index)
                                except OSError:
                                    break
                                instance_index += 1

                                params_path = f"{device_key_path}\\{instance_name}\\Device Parameters"
                                try:
                                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, params_path) as params_key:
                                        port_name, _ = winreg.QueryValueEx(params_key, "PortName")
                                except OSError:
                                    continue

                                if str(port_name).upper() == target_device:
                                    return int(interface_match.group(1))
                    except OSError:
                        continue
        except OSError:
            return None

        return None

    def __init__(self, port: Optional[str] = None, baud: int = DEFAULT_BAUD):
        self._port = port
        self._baud = baud
        self._serial = None
        self._lock = threading.Lock()
        self._stream_callback: Optional[Callable[[bytes], None]] = None
        self._packet_callback: Optional[Callable[[dict], None]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()
        self._paused = threading.Event()
        self._last_connect_attempt: float = 0.0
        self._debug_parser = PacketParser(on_packet=self._on_pico_packet)
        self._debug_logger = logging.getLogger("pico.debug")
        self._last_connected_port: Optional[str] = None
        self._connected_port: Optional[str] = None
        self._bad_ports_until: dict[str, float] = {}

    def _port_is_blacklisted(self, port: str, *, now: float) -> bool:
        return self._bad_ports_until.get(port, 0.0) > now

    def _mark_port_failed(self, port: Optional[str], *, reason: str) -> None:
        if not port:
            return
        until = time.monotonic() + PORT_FAILURE_COOLDOWN_S
        self._bad_ports_until[port] = until
        logger.warning("SerialSender: blacklisting %s for %.1fs after %s", port, PORT_FAILURE_COOLDOWN_S, reason)

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
                preferred.append(port)
                continue
            if "spark" in description or "spark" in manufacturer or "spark" in product:
                preferred.append(port)
                continue
            fallback.append(device)

        if preferred:
            return SerialSender._preferred_port_from_matches(preferred)

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
            if self._serial is not None and not self._serial.is_open:
                self._disconnect_locked()

            candidate_ports = []
            if self._port:
                candidate_ports.append(self._port)
            else:
                if self._last_connected_port:
                    candidate_ports.append(self._last_connected_port)
                detected_port = self._find_pico_port()
                if detected_port and detected_port not in candidate_ports:
                    candidate_ports.append(detected_port)

            if not candidate_ports:
                logger.warning("SerialSender: no Pico port found")
                return False

            filtered_ports = []
            for candidate_port in candidate_ports:
                if self._port_is_blacklisted(candidate_port, now=now):
                    remaining = self._bad_ports_until[candidate_port] - now
                    logger.info("SerialSender: skipping blacklisted port %s (%.1fs remaining)", candidate_port, remaining)
                    continue
                filtered_ports.append(candidate_port)

            if not filtered_ports:
                logger.warning("SerialSender: all candidate ports are cooling down")
                return False

            port = None
            last_error = None
            for candidate_port in filtered_ports:
                try:
                    self._serial = serial.Serial(candidate_port, self._baud, timeout=0.1, write_timeout=2.0)
                    port = candidate_port
                    break
                except Exception as exc:
                    last_error = exc

            if port is None:
                logger.warning("SerialSender: open failed - %s", last_error)
                return False

        self._stop_reader.clear()
        self.start_reader()
        self._connected_port = port
        self._last_connected_port = port
        self._bad_ports_until.pop(port, None)
        logger.info("SerialSender: connected on %s @ %s", port, self._baud)
        return True

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def close(self) -> None:
        self._stop_reader.set()
        with self._lock:
            self._disconnect_locked()
        logger.info("SerialSender: closed")

    def _disconnect_locked(self) -> None:
        serial_port = self._serial
        self._serial = None
        self._connected_port = None
        if serial_port is None:
            return
        try:
            serial_port.close()
        except Exception:
            pass

    def set_stream_callback(self, callback: Optional[Callable[[bytes], None]]) -> None:
        self._stream_callback = callback

    def set_packet_callback(self, callback: Optional[Callable[[dict], None]]) -> None:
        self._packet_callback = callback

    def _send(self, packet: bytes) -> bool:
        if not self.is_connected():
            return False

        with self._lock:
            try:
                self._serial.write(packet)
                return True
            except Exception as exc:
                logger.warning("SerialSender: write error - %s", exc)
                self._mark_port_failed(self._connected_port, reason="write error")
                self._disconnect_locked()
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
                self._mark_port_failed(self._connected_port, reason="read error")
                self._disconnect_locked()
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
        if self._packet_callback:
            self._packet_callback(pkt)

    def pause(self) -> None:
        """Suppress context sends and release the serial port so other tools can use it."""
        self._paused.set()
        self._stop_reader.set()
        with self._lock:
            self._disconnect_locked()
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

    @staticmethod
    def _context_packet(payload: dict, build_packet) -> bytes:
        def packet_for_text(text_value: str):
            candidate_payload = dict(payload)
            candidate_payload["text"] = text_value
            try:
                return build_packet(candidate_payload)
            except struct.error:
                return None

        text = payload.get("text") or ""
        packet = packet_for_text(text)
        if packet is None:
            packet = packet_for_text("")
        if packet is None:
            raise ValueError("context packet metadata exceeds protocol payload limit")

        if len(packet) <= _MAX_CONTEXT_PACKET_BYTES:
            return packet

        if not text:
            return packet

        low = 0
        high = len(text)
        best_packet = packet
        while low <= high:
            mid = (low + high) // 2
            candidate_packet = packet_for_text(text[:mid])
            if candidate_packet is not None and len(candidate_packet) <= _MAX_CONTEXT_PACKET_BYTES:
                best_packet = candidate_packet
                low = mid + 1
            else:
                high = mid - 1

        return best_packet

    def send_context_new(self, snapshot) -> bool:
        if self._paused.is_set():
            return False
        payload = self._snapshot_payload(snapshot)
        return self._send(self._context_packet(payload, build_context_new))

    def send_context_update(self, snapshot) -> bool:
        if self._paused.is_set():
            return False
        payload = self._snapshot_payload(snapshot)
        return self._send(self._context_packet(payload, build_context_update))
