"""
SPARK keyboard HID manager.

Mirrors the structure of host_pc/hotkeys.py:
  - a QObject signals class
  - a manager class with start() / stop() and a background thread

Device identity and packet constants are taken directly from
tools/spark_raw_hid_demo.py in the spark_qmk repo — nothing is invented here.

Packet convention (32 bytes, command byte at position 0):
  Keyboard → Host
    0xA0   CMD_KB_CAPTURE    keyboard key triggered a capture
    0xA1   CMD_KB_RELEASE    keyboard key triggered a release

  Host → Keyboard  (send_status)
    0xB0   CMD_HOST_STATUS   byte[1] = status code
             0x01  STATUS_PROCESSING
             0x02  STATUS_DONE
             0x03  STATUS_ERROR
"""

import logging
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# ── Device identity (from spark_qmk keyboards/spark/keyboard.json) ──
SPARK_VID       = 0xC4C4
SPARK_PID       = 0x5350
RAW_USAGE_PAGE  = 0xFF60   # QMK Raw HID usage page
RAW_USAGE_ID    = 0x61

# ── Wire constants (from spark_raw_hid_demo.py) ──────────────────────
REPORT_SIZE     = 32
READ_TIMEOUT_MS = 500      # short enough to check _running flag frequently

# ── Keyboard → Host command bytes ────────────────────────────────────
CMD_KB_CAPTURE  = 0xA0    # keyboard key: trigger capture
CMD_KB_RELEASE  = 0xA1    # keyboard key: trigger release

# ── Host → Keyboard command bytes ────────────────────────────────────
CMD_HOST_STATUS = 0xB0    # byte[1] carries the status code below

# Status codes for CMD_HOST_STATUS
STATUS_PROCESSING = 0x01
STATUS_DONE       = 0x02
STATUS_ERROR      = 0x03

# How long to wait before a reconnect attempt (seconds)
RECONNECT_DELAY = 2.0


class KeyboardHIDSignals(QObject):
    """Qt signal bridge — emitted from the HID reader thread."""
    capture_triggered  = pyqtSignal()        # keyboard pressed capture key
    release_triggered  = pyqtSignal()        # keyboard pressed release key
    connected_changed  = pyqtSignal(bool)    # True = just connected, False = just disconnected


class KeyboardHIDManager:
    """
    Manages the SPARK keyboard Raw HID connection.

    Runs a background daemon thread that:
      - opens the HID device (best-effort; silently skips if not present)
      - reads 32-byte reports and dispatches keyboard-initiated commands
      - reconnects automatically when the keyboard is replugged

    Public interface:
      start()                    start the background thread
      stop()                     stop the thread and close the device
      send_status(status_byte)   send host-feedback report to keyboard
      signals.capture_triggered  pyqtSignal()  — wire to _on_capture
      signals.release_triggered  pyqtSignal()  — wire to _on_release
      signals.connected_changed  pyqtSignal(bool)
    """

    def __init__(self, vid: int = SPARK_VID, pid: int = SPARK_PID) -> None:
        self.vid     = vid
        self.pid     = pid
        self.signals = KeyboardHIDSignals()

        self._device  = None
        self._thread  = None
        self._running = False
        self._lock    = threading.Lock()   # guards _device for send_status

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the HID reader thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True,
                                         name="spark-hid-reader")
        self._thread.start()
        logger.info("KeyboardHIDManager started")

    def stop(self) -> None:
        """Stop the reader thread and close the device."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._close_device()
        logger.info("KeyboardHIDManager stopped")

    # ── Host → Keyboard feedback ─────────────────────────────────────

    def send_status(self, status_byte: int) -> None:
        """
        Send a 32-byte CMD_HOST_STATUS report back to the keyboard.

        status_byte should be one of:
            STATUS_PROCESSING (0x01)
            STATUS_DONE       (0x02)
            STATUS_ERROR      (0x03)
        """
        report = bytearray(REPORT_SIZE)
        report[0] = CMD_HOST_STATUS
        report[1] = status_byte & 0xFF

        with self._lock:
            if self._device is None:
                logger.debug("send_status: device not connected, skipping")
                return
            try:
                payload = bytes([0]) + bytes(report)   # prepend report-ID 0
                self._device.write(payload)
                logger.debug(f"send_status: sent 0x{status_byte:02X}")
            except Exception as exc:
                logger.warning(f"send_status write failed: {exc}")

    # ── Background thread ────────────────────────────────────────────

    def _run(self) -> None:
        """Outer reconnect loop — runs for the lifetime of the manager."""
        while self._running:
            if self._try_open():
                self.signals.connected_changed.emit(True)
                self._read_loop()                      # blocks until error/stop
                self._close_device()
                if self._running:                      # only log if not deliberate stop
                    logger.warning("HID device disconnected")
                    self.signals.connected_changed.emit(False)
            else:
                # Device not found — wait before retrying
                self._sleep_interruptible(RECONNECT_DELAY)

    def _try_open(self) -> bool:
        """Attempt to open the Raw HID interface.  Returns True on success."""
        try:
            import hid
        except ImportError:
            logger.error("hidapi not installed — run: pip install hid")
            return False

        devices = hid.enumerate(self.vid, self.pid)
        matches = [
            d for d in devices
            if d.get("usage_page") == RAW_USAGE_PAGE and d.get("usage") == RAW_USAGE_ID
        ]
        if not matches and devices:
            matches = devices          # fallback: accept any interface for this VID/PID
        if not matches:
            return False

        try:
            dev = hid.device()
            dev.open_path(matches[0]["path"])
            dev.set_nonblocking(False)
            with self._lock:
                self._device = dev
            logger.info(f"SPARK keyboard connected  "
                        f"(VID 0x{self.vid:04X} PID 0x{self.pid:04X})")
            return True
        except Exception as exc:
            logger.warning(f"HID open failed: {exc}")
            return False

    def _read_loop(self) -> None:
        """Read reports until the device disconnects or stop() is called."""
        while self._running:
            try:
                with self._lock:
                    dev = self._device
                if dev is None:
                    break

                data = dev.read(REPORT_SIZE, READ_TIMEOUT_MS)
                if not data:
                    continue    # timeout — loop and check _running

                report = bytes(data)
                # Strip leading report-ID 0x00 if present
                if len(report) == REPORT_SIZE + 1 and report[0] == 0:
                    report = report[1:]
                if len(report) != REPORT_SIZE:
                    continue

                self._dispatch(report)

            except Exception as exc:
                if self._running:
                    logger.warning(f"HID read error: {exc}")
                break

    def _dispatch(self, report: bytes) -> None:
        """Route an incoming report to the appropriate Qt signal."""
        cmd = report[0]
        if cmd == CMD_KB_CAPTURE:
            logger.debug("HID: capture triggered by keyboard")
            self.signals.capture_triggered.emit()
        elif cmd == CMD_KB_RELEASE:
            logger.debug("HID: release triggered by keyboard")
            self.signals.release_triggered.emit()
        else:
            logger.debug(f"HID: unhandled command 0x{cmd:02X}")

    # ── Helpers ──────────────────────────────────────────────────────

    def _close_device(self) -> None:
        with self._lock:
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:
                    pass
                self._device = None

    def _sleep_interruptible(self, seconds: float) -> None:
        """Sleep in small increments so stop() is noticed quickly."""
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(0.1)
