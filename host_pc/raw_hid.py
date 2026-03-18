"""
Raw HID communication layer for SPARK device.

Handles USB communication with the RP2040 microcontroller running SPARK firmware.
Provides background thread-based report reading with callbacks for device events
(button presses, encoder changes, parameter updates).

The SPARK device is identified by VID 0xC4C4 and PID 0x5350.

Protocol:
    Report byte 0:  Message type (0x01=button, 0x02=encoder, 0x03=param_update)
    Report bytes 1–4:  Payload (button_id, encoder_delta, or float-encoded parameter value)
    Report size:  64 bytes total (padded with 0x00)
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Any
import struct

logger = logging.getLogger(__name__)

# USB identifiers for SPARK device
SPARK_VID = 0xC4C4
SPARK_PID = 0x5350
SPARK_REPORT_SIZE = 64


class MessageType(Enum):
    """HID report message types from firmware."""
    BUTTON = 0x01
    ENCODER = 0x02
    PARAM_UPDATE = 0x03


@dataclass
class ButtonEvent:
    """A button press/release event from the device."""
    button_id: int
    pressed: bool

    def __repr__(self) -> str:
        state = "pressed" if self.pressed else "released"
        return f"ButtonEvent(id={self.button_id}, {state})"


@dataclass
class EncoderEvent:
    """An encoder rotation event from the device."""
    encoder_id: int
    delta: int  # positive = clockwise, negative = counter-clockwise

    def __repr__(self) -> str:
        direction = "CW" if self.delta > 0 else "CCW"
        return f"EncoderEvent(id={self.encoder_id}, delta={self.delta} {direction})"


@dataclass
class ParameterUpdateEvent:
    """A parameter update event (temperature, top_p, max_tokens, etc.)."""
    param_id: int
    value: float

    def __repr__(self) -> str:
        return f"ParameterUpdateEvent(id={self.param_id}, value={self.value})"


class HIDDevice(ABC):
    """Abstract base class for HID device implementations."""

    @abstractmethod
    def open(self) -> bool:
        """Open connection to device. Returns True on success."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connection to device."""
        pass

    @abstractmethod
    def is_open(self) -> bool:
        """Check if device is currently open."""
        pass

    @abstractmethod
    def read(self, size: int = SPARK_REPORT_SIZE) -> Optional[bytes]:
        """
        Read a report from the device.

        Args:
            size: Expected report size in bytes

        Returns:
            Bytes read, or None if no data available or error
        """
        pass

    @abstractmethod
    def write(self, data: bytes) -> int:
        """
        Write a report to the device.

        Args:
            data: Bytes to write (will be padded to SPARK_REPORT_SIZE)

        Returns:
            Number of bytes written, or -1 on error
        """
        pass


class RealHIDDevice(HIDDevice):
    """Real HID device using hid library."""

    def __init__(self, vid: int, pid: int):
        self.vid = vid
        self.pid = pid
        self.device = None
        self._lock = threading.Lock()

    def open(self) -> bool:
        """Open connection to SPARK device by VID/PID."""
        try:
            import hid
        except ImportError:
            logger.error("hid module not found. Install: pip install hidapi")
            return False

        try:
            with self._lock:
                if self.device is not None:
                    return True

                self.device = hid.device()
                self.device.open(self.vid, self.pid)
                self.device.set_nonblocking(True)
                logger.info(f"Opened HID device {self.vid:04x}:{self.pid:04x}")
                return True
        except Exception as e:
            logger.error(f"Failed to open HID device: {e}")
            self.device = None
            return False

    def close(self) -> None:
        """Close connection to device."""
        with self._lock:
            if self.device is not None:
                try:
                    self.device.close()
                except Exception as e:
                    logger.warning(f"Error closing HID device: {e}")
                finally:
                    self.device = None
                logger.info("Closed HID device")

    def is_open(self) -> bool:
        """Check if device is open."""
        with self._lock:
            return self.device is not None

    def read(self, size: int = SPARK_REPORT_SIZE) -> Optional[bytes]:
        """Read a report from device."""
        with self._lock:
            if self.device is None:
                return None
            try:
                data = self.device.read(size, timeout_ms=100)
                return bytes(data) if data else None
            except Exception as e:
                logger.warning(f"HID read error: {e}")
                return None

    def write(self, data: bytes) -> int:
        """Write a report to device."""
        with self._lock:
            if self.device is None:
                return -1
            try:
                # Pad to report size
                padded = data + b'\x00' * (SPARK_REPORT_SIZE - len(data))
                padded = padded[:SPARK_REPORT_SIZE]
                return self.device.write(padded)
            except Exception as e:
                logger.warning(f"HID write error: {e}")
                return -1


class MockHIDDevice(HIDDevice):
    """Mock HID device for testing without physical hardware."""

    def __init__(self):
        self._open = False
        self._write_queue = []

    def open(self) -> bool:
        """Mock open (always succeeds)."""
        self._open = True
        logger.info("Opened mock HID device")
        return True

    def close(self) -> None:
        """Mock close."""
        self._open = False
        logger.info("Closed mock HID device")

    def is_open(self) -> bool:
        """Check if mock device is open."""
        return self._open

    def read(self, size: int = SPARK_REPORT_SIZE) -> Optional[bytes]:
        """Mock read (returns None — no data)."""
        return None

    def write(self, data: bytes) -> int:
        """Mock write (stores for verification in tests)."""
        if not self._open:
            return -1
        self._write_queue.append(data)
        return len(data)


class RawHIDListener:
    """
    Background thread-based HID report reader for SPARK device.

    Continuously reads 64-byte reports from the device and parses them into
    structured events (button, encoder, parameter update). Fires registered
    callbacks when events are received.

    Supports auto-reconnect on device disconnect.
    """

    def __init__(self, device: Optional[HIDDevice] = None, auto_reconnect: bool = True):
        """
        Initialize the HID listener.

        Args:
            device: HIDDevice instance (defaults to RealHIDDevice)
            auto_reconnect: Automatically reconnect on device disconnect
        """
        self.device = device or RealHIDDevice(SPARK_VID, SPARK_PID)
        self.auto_reconnect = auto_reconnect

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Callbacks
        self._on_button_press: Optional[Callable[[ButtonEvent], None]] = None
        self._on_encoder_change: Optional[Callable[[EncoderEvent], None]] = None
        self._on_param_update: Optional[Callable[[ParameterUpdateEvent], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None

    def start(self) -> bool:
        """
        Start the background listener thread.

        Returns:
            True if started successfully, False otherwise
        """
        with self._lock:
            if self._running:
                logger.warning("RawHIDListener already running")
                return False

            if not self.device.open():
                logger.error("Failed to open HID device")
                return False

            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            logger.info("RawHIDListener thread started")
            return True

    def stop(self) -> None:
        """Stop the background listener thread."""
        with self._lock:
            self._running = False

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        self.device.close()
        logger.info("RawHIDListener thread stopped")

    def is_running(self) -> bool:
        """Check if listener is running."""
        with self._lock:
            return self._running

    def on_button_press(self, callback: Callable[[ButtonEvent], None]) -> None:
        """Register callback for button press events."""
        self._on_button_press = callback

    def on_encoder_change(self, callback: Callable[[EncoderEvent], None]) -> None:
        """Register callback for encoder change events."""
        self._on_encoder_change = callback

    def on_param_update(self, callback: Callable[[ParameterUpdateEvent], None]) -> None:
        """Register callback for parameter update events."""
        self._on_param_update = callback

    def on_error(self, callback: Callable[[str], None]) -> None:
        """Register callback for error messages."""
        self._on_error = callback

    def send_report(self, data: bytes) -> bool:
        """
        Send a report to the device.

        Args:
            data: Bytes to send (will be padded to 64 bytes)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.device.is_open():
            logger.warning("Cannot send report: device not open")
            return False

        result = self.device.write(data)
        if result < 0:
            logger.error("Failed to send report to device")
            return False

        logger.debug(f"Sent {result} bytes to device")
        return True

    def _read_loop(self) -> None:
        """Background thread main loop that reads and parses HID reports."""
        reconnect_delay = 1.0

        while True:
            with self._lock:
                if not self._running:
                    break

            if not self.device.is_open():
                if self.auto_reconnect:
                    logger.info(f"Device disconnected, reconnecting in {reconnect_delay}s...")
                    time.sleep(reconnect_delay)
                    if self.device.open():
                        reconnect_delay = 1.0
                    else:
                        reconnect_delay = min(reconnect_delay * 1.5, 10.0)
                else:
                    break
                continue

            try:
                data = self.device.read(SPARK_REPORT_SIZE)
                if data is None:
                    time.sleep(0.01)  # No data available, small sleep
                    continue

                self._parse_report(data)
            except Exception as e:
                error_msg = f"Error in HID read loop: {e}"
                logger.error(error_msg)
                if self._on_error:
                    self._on_error(error_msg)
                self.device.close()

    def _parse_report(self, data: bytes) -> None:
        """
        Parse a 64-byte HID report into structured events.

        Args:
            data: Raw 64-byte report from device
        """
        if not data or len(data) < 5:
            logger.warning("Invalid report size")
            return

        msg_type = data[0]

        try:
            if msg_type == MessageType.BUTTON.value:
                self._parse_button(data)
            elif msg_type == MessageType.ENCODER.value:
                self._parse_encoder(data)
            elif msg_type == MessageType.PARAM_UPDATE.value:
                self._parse_param_update(data)
            else:
                logger.warning(f"Unknown message type: 0x{msg_type:02x}")
        except Exception as e:
            logger.error(f"Error parsing report: {e}")

    def _parse_button(self, data: bytes) -> None:
        """Parse a button event from report bytes 1-4."""
        if not self._on_button_press:
            return

        button_id = data[1]
        pressed = bool(data[2])
        event = ButtonEvent(button_id=button_id, pressed=pressed)
        logger.debug(f"Parsed button event: {event}")
        self._on_button_press(event)

    def _parse_encoder(self, data: bytes) -> None:
        """Parse an encoder event from report bytes 1-4."""
        if not self._on_encoder_change:
            return

        encoder_id = data[1]
        # Delta is signed int32, little-endian
        delta = struct.unpack('<i', data[2:6])[0]
        event = EncoderEvent(encoder_id=encoder_id, delta=delta)
        logger.debug(f"Parsed encoder event: {event}")
        self._on_encoder_change(event)

    def _parse_param_update(self, data: bytes) -> None:
        """Parse a parameter update event from report bytes 1-4."""
        if not self._on_param_update:
            return

        param_id = data[1]
        # Value is float32, little-endian
        value = struct.unpack('<f', data[2:6])[0]
        event = ParameterUpdateEvent(param_id=param_id, value=value)
        logger.debug(f"Parsed param update: {event}")
        self._on_param_update(event)


def create_listener(mock: bool = False, auto_reconnect: bool = True) -> RawHIDListener:
    """
    Factory function to create a RawHIDListener instance.

    Args:
        mock: If True, use MockHIDDevice for testing
        auto_reconnect: Enable automatic reconnection on device disconnect

    Returns:
        Configured RawHIDListener instance
    """
    device = MockHIDDevice() if mock else RealHIDDevice(SPARK_VID, SPARK_PID)
    return RawHIDListener(device=device, auto_reconnect=auto_reconnect)
