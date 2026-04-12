"""
SPARK Raw HID upload client.

Sends chunked UTF-8 text to the SPARK Pico Hub (RP2040/CircuitPython) over the
Raw HID upload protocol v0x0002. Reports are 32 bytes; each chunk carries
27 bytes of payload.

Typical flow:
    client = SparkHIDClient()
    if client.is_connected():
        info   = client.get_info()
        status = client.upload(AppCommand.SUBMIT_TEXT, "hello world")
        if status.ok:
            print("device accepted the upload")
"""

import logging
import time
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)

# ── USB / HID constants ────────────────────────────────────────
SPARK_VID          = 0xC4C4
SPARK_PID          = 0x5350
RAW_USAGE_PAGE     = 0xFF60   # SPARK custom Raw HID usage page
RAW_USAGE_ID       = 0x61
RAW_REPORT_ID      = 0x04
REPORT_SIZE        = 32
CHUNK_PAYLOAD_SIZE = 27
INTER_REPORT_GAP_S = 0.01


# ── Protocol enums ─────────────────────────────────────────────

class Command(IntEnum):
    GET_INFO      = 0x01
    GET_RESPONSE_INFO = 0x20
    GET_RESPONSE_CHUNK = 0x21
    GET_RUNTIME_STATUS = 0x22
    GET_DEBUG_EVENT = 0x23
    BEGIN_UPLOAD  = 0x10
    UPLOAD_CHUNK  = 0x11
    COMMIT_UPLOAD = 0x12
    ABORT_UPLOAD  = 0x13
    STATUS        = 0x7F


class StatusCode(IntEnum):
    OK                  = 0x00
    BUSY                = 0x01
    INVALID_STATE       = 0x02
    INVALID_LENGTH      = 0x03
    INVALID_INDEX       = 0x04
    CRC_MISMATCH        = 0x05
    TOO_LARGE           = 0x06
    UNSUPPORTED_COMMAND = 0x07
    INCOMPLETE_UPLOAD   = 0x08
    INTERNAL_ERROR      = 0x09


class AppCommand(IntEnum):
    SUBMIT_TEXT = 0x0001   # device validates and acknowledges uploaded text
    PING        = 0x0002   # device responds with "spark ready"
    FEATURE_1   = 0x0101
    FEATURE_2   = 0x0102
    FEATURE_3   = 0x0103
    FEATURE_4   = 0x0104


# ── Result types ───────────────────────────────────────────────

@dataclass
class DeviceInfo:
    protocol_version:  int
    chunk_payload_size: int
    max_upload_bytes:  int
    max_chunk_count:   int
    capabilities:      int
    upload_active:     bool
    active_message_id: int


@dataclass
class UploadStatus:
    message_id: int
    code:       StatusCode
    value0:     int
    value1:     int
    detail:     str

    @property
    def ok(self) -> bool:
        return self.code == StatusCode.OK

    def __str__(self) -> str:
        return (
            f"msg={self.message_id} status={self.code.name}"
            + (f" detail={self.detail!r}" if self.detail else "")
        )


class SparkProtocolError(RuntimeError):
    """Raised when the device returns an unexpected response."""


@dataclass
class ResponseInfo:
    total_len: int
    chunk_count: int
    complete: bool
    active: bool


@dataclass
class RuntimeStatusInfo:
    complete: bool
    active: bool
    text: str


# ── Client ─────────────────────────────────────────────────────

class SparkHIDClient:
    """
    Synchronous Raw HID client for the SPARK device.

    All methods block the calling thread. Run upload() from a background
    thread to keep the Qt event loop responsive.
    """

    def __init__(self, vid: int = SPARK_VID, pid: int = SPARK_PID) -> None:
        self.vid = vid
        self.pid = pid
        self._device = None
        self._message_id = 0

    # ── Connection helpers ─────────────────────────────────────

    def _matching_interfaces(self) -> list:
        try:
            import hid
        except ImportError:
            logger.error("hidapi not installed — run: pip install hidapi")
            return []

        devices = hid.enumerate(self.vid, self.pid)
        matches = [
            d for d in devices
            if d.get("usage_page") == RAW_USAGE_PAGE and d.get("usage") == RAW_USAGE_ID
        ]
        # Fallback: accept any interface for this VID/PID
        return matches if matches else devices

    def is_connected(self) -> bool:
        """Return True if the SPARK Raw HID interface is visible on USB."""
        return bool(self._matching_interfaces())

    def poll_connected(self) -> bool:
        """Alias for is_connected(), used by the UI poll timer."""
        return self.is_connected()

    def _open(self) -> None:
        """Open the HID device if not already open."""
        try:
            import hid
        except ImportError:
            raise SparkProtocolError("hidapi not installed — run: pip install hidapi")

        if self._device is not None:
            return

        matches = self._matching_interfaces()
        if not matches:
            raise SparkProtocolError(
                f"SPARK device not found (VID 0x{self.vid:04X} PID 0x{self.pid:04X})"
            )

        self._device = hid.device()
        self._device.open_path(matches[0]["path"])
        self._device.set_nonblocking(False)
        logger.info("Opened SPARK Raw HID device")

    def close(self) -> None:
        """Close the HID device."""
        if self._device is not None:
            try:
                self._device.close()
            except Exception as exc:
                logger.warning(f"Error closing HID device: {exc}")
            finally:
                self._device = None
            logger.info("Closed SPARK Raw HID device")

    # ── Low-level I/O ──────────────────────────────────────────

    def _write(self, report: bytes) -> None:
        payload = bytes([RAW_REPORT_ID]) + report
        for attempt in range(2):
            self._open()
            try:
                written = self._device.write(payload)
            except Exception as exc:
                can_retry = attempt == 0 and self._device is not None and self.is_connected()
                self.close()
                if can_retry:
                    logger.warning("HID write failed; reopening device and retrying: %s", exc)
                    continue
                raise SparkProtocolError(f"HID write failed: {exc}") from exc

            if written in (len(payload), len(report)):
                return

            can_retry = attempt == 0 and self._device is not None and self.is_connected()
            self.close()
            if can_retry:
                logger.warning(
                    "Short HID write (%s of %s); reopening device and retrying",
                    written,
                    len(payload),
                )
                continue
            raise SparkProtocolError(
                f"Short HID write: wrote {written} of {len(payload)} bytes"
            )

    def _read(self, timeout_ms: int = 2000) -> bytes:
        for attempt in range(2):
            self._open()
            try:
                data = self._device.read(REPORT_SIZE + 1, timeout_ms)
            except Exception as exc:
                can_retry = attempt == 0 and self._device is not None and self.is_connected()
                self.close()
                if can_retry:
                    logger.warning("HID read failed; reopening device and retrying: %s", exc)
                    continue
                raise SparkProtocolError(f"HID read failed: {exc}") from exc

            if not data:
                can_retry = attempt == 0 and self._device is not None and self.is_connected()
                self.close()
                if can_retry:
                    logger.warning("HID read timed out; reopening device and retrying once")
                    continue
                raise SparkProtocolError("Timed out waiting for device response")

            report = bytes(data)
            # Strip leading report-ID byte if present
            if len(report) == REPORT_SIZE + 1 and report[0] == RAW_REPORT_ID:
                report = report[1:]
            if len(report) != REPORT_SIZE:
                raise SparkProtocolError(
                    f"Unexpected report size: {len(report)} (expected {REPORT_SIZE})"
                )
            return report

    def _next_message_id(self) -> int:
        self._message_id = (self._message_id % 0xFFFF) + 1
        return self._message_id

    def _report_gap(self) -> None:
        time.sleep(INTER_REPORT_GAP_S)

    # ── Protocol helpers ───────────────────────────────────────

    @staticmethod
    def _u16(data: bytes, offset: int) -> int:
        return data[offset] | (data[offset + 1] << 8)

    @staticmethod
    def _u32(data: bytes, offset: int) -> int:
        return (
            data[offset]
            | (data[offset + 1] << 8)
            | (data[offset + 2] << 16)
            | (data[offset + 3] << 24)
        )

    @staticmethod
    def _parse_detail(raw: bytes) -> str:
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    def _read_until(self, predicate, timeout_ms: int = 2000) -> bytes:
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        last_report = None

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            report = self._read(remaining_ms)
            last_report = report
            if predicate(report):
                return report

        if last_report is None:
            raise SparkProtocolError("Timed out waiting for expected device response")
        raise SparkProtocolError(
            f"Timed out waiting for expected device response; last report was 0x{last_report[0]:02X}"
        )

    def _read_status(self, expected_cmd: int, message_id: int, timeout_ms: int = 2000) -> UploadStatus:
        def matches(report: bytes) -> bool:
            if report[0] != Command.STATUS:
                return False
            related_cmd = report[1]
            reply_msg_id = self._u16(report, 2)
            return related_cmd == expected_cmd and reply_msg_id == message_id

        reply = self._read_until(matches, timeout_ms)
        if reply[0] != Command.STATUS:
            raise SparkProtocolError(
                f"Expected STATUS (0x7F), got 0x{reply[0]:02X}"
            )
        related_cmd    = reply[1]
        reply_msg_id   = self._u16(reply, 2)
        status_code    = reply[4]
        value0         = self._u32(reply, 6)
        value1         = self._u32(reply, 10)
        detail         = self._parse_detail(reply[14:32])

        if related_cmd != expected_cmd or reply_msg_id != message_id:
            raise SparkProtocolError(
                f"STATUS mismatch: cmd=0x{related_cmd:02X} (expected 0x{expected_cmd:02X}), "
                f"msg={reply_msg_id} (expected {message_id})"
            )

        try:
            code = StatusCode(status_code)
        except ValueError:
            code = StatusCode.INTERNAL_ERROR

        return UploadStatus(
            message_id=message_id,
            code=code,
            value0=value0,
            value1=value1,
            detail=detail,
        )

    # ── Public API ─────────────────────────────────────────────

    def get_info(self) -> DeviceInfo:
        """Query device capabilities."""
        report = bytearray(REPORT_SIZE)
        report[0] = Command.GET_INFO
        self._write(bytes(report))
        reply = self._read_until(lambda response: response[0] == Command.GET_INFO)

        if reply[0] != Command.GET_INFO:
            raise SparkProtocolError(
                f"Expected GET_INFO response, got 0x{reply[0]:02X}"
            )

        return DeviceInfo(
            protocol_version  = self._u16(reply, 1),
            chunk_payload_size= reply[3],
            max_upload_bytes  = self._u32(reply, 4),
            max_chunk_count   = self._u16(reply, 8),
            capabilities      = reply[10],
            upload_active     = bool(reply[11]),
            active_message_id = self._u16(reply, 12),
        )

    def fetch_response(self, info: Optional[ResponseInfo] = None) -> str:
        if info is None:
            info = self.get_response_info()
        if info.total_len == 0 or info.chunk_count == 0:
            return ""
        return self._fetch_response_from_info(info)

    def get_response_info(self) -> ResponseInfo:
        report = bytearray(REPORT_SIZE)
        report[0] = Command.GET_RESPONSE_INFO
        self._write(bytes(report))
        info = self._read_until(lambda reply: reply[0] == Command.GET_RESPONSE_INFO)

        if info[0] != Command.GET_RESPONSE_INFO:
            raise SparkProtocolError(
                f"Expected GET_RESPONSE_INFO response, got 0x{info[0]:02X}"
            )

        flags = info[7]
        return ResponseInfo(
            total_len=self._u32(info, 1),
            chunk_count=self._u16(info, 5),
            complete=bool(flags & 0x01),
            active=bool(flags & 0x02),
        )

    def get_runtime_status(self) -> RuntimeStatusInfo:
        report = bytearray(REPORT_SIZE)
        report[0] = Command.GET_RUNTIME_STATUS
        self._write(bytes(report))
        info = self._read_until(lambda reply: reply[0] == Command.GET_RUNTIME_STATUS)

        if info[0] != Command.GET_RUNTIME_STATUS:
            raise SparkProtocolError(
                f"Expected GET_RUNTIME_STATUS response, got 0x{info[0]:02X}"
            )

        flags = info[1]
        text = bytes(info[2:32]).split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        return RuntimeStatusInfo(
            complete=bool(flags & 0x01),
            active=bool(flags & 0x02),
            text=text,
        )

    def get_debug_event(self) -> Optional[str]:
        report = bytearray(REPORT_SIZE)
        report[0] = Command.GET_DEBUG_EVENT
        self._write(bytes(report))
        info = self._read_until(lambda reply: reply[0] == Command.GET_DEBUG_EVENT)

        if info[0] != Command.GET_DEBUG_EVENT:
            raise SparkProtocolError(
                f"Expected GET_DEBUG_EVENT response, got 0x{info[0]:02X}"
            )

        if not info[1]:
            return None
        return bytes(info[2:32]).split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    def _fetch_response_from_info(self, info: ResponseInfo) -> str:
        total_len = info.total_len
        chunk_count = info.chunk_count
        response = bytearray()
        for index in range(chunk_count):
            chunk_report = bytearray(REPORT_SIZE)
            chunk_report[0] = Command.GET_RESPONSE_CHUNK
            chunk_report[1] = index & 0xFF
            chunk_report[2] = (index >> 8) & 0xFF
            self._write(bytes(chunk_report))
            chunk = self._read_until(
                lambda reply: reply[0] == Command.STATUS
                or (reply[0] == Command.GET_RESPONSE_CHUNK and reply[1] == (index & 0xFF))
            )

            if chunk[0] == Command.STATUS:
                raise SparkProtocolError(
                    f"GET_RESPONSE_CHUNK failed: {self._parse_detail(chunk[14:32])}"
                )
            if chunk[0] != Command.GET_RESPONSE_CHUNK:
                raise SparkProtocolError(
                    f"Expected GET_RESPONSE_CHUNK response, got 0x{chunk[0]:02X}"
                )

            remaining = total_len - len(response)
            response.extend(chunk[2:2 + min(CHUNK_PAYLOAD_SIZE, remaining)])

        return bytes(response[:total_len]).decode("utf-8", errors="replace")

    def _ensure_idle(self) -> None:
        """
        If the device is stuck in an active upload session after a timeout,
        abort it so the next upload can proceed cleanly.
        """
        try:
            info = self.get_info()
            if info.upload_active and info.active_message_id:
                logger.warning(
                    "Device has stale upload session msg=%d - sending ABORT",
                    info.active_message_id,
                )
                self.abort(info.active_message_id)
        except SparkProtocolError as exc:
            logger.warning("_ensure_idle failed (device may be in unknown state): %s", exc)

    def upload(self, app_command: AppCommand, text: str) -> UploadStatus:
        """
        Upload UTF-8 text to the device.

        Handles BEGIN_UPLOAD → chunks → COMMIT_UPLOAD and returns the final
        status. Raises SparkProtocolError on transport or protocol errors.
        """
        self._ensure_idle()
        payload    = text.encode("utf-8")
        message_id = self._next_message_id()
        crc32      = zlib.crc32(payload) & 0xFFFFFFFF
        total_len  = len(payload)
        chunks     = [
            payload[i : i + CHUNK_PAYLOAD_SIZE]
            for i in range(0, total_len, CHUNK_PAYLOAD_SIZE)
        ]

        logger.info(
            f"upload msg={message_id} cmd=0x{app_command:04X} "
            f"len={total_len} chunks={len(chunks)}"
        )

        # ── BEGIN_UPLOAD ──────────────────────────────────────
        begin = bytearray(REPORT_SIZE)
        begin[0]  = Command.BEGIN_UPLOAD
        begin[1]  = message_id & 0xFF
        begin[2]  = (message_id >> 8) & 0xFF
        begin[3]  = int(app_command) & 0xFF
        begin[4]  = (int(app_command) >> 8) & 0xFF
        begin[5]  = 0x01                          # ENCODING_UTF8
        begin[7]  = total_len & 0xFF
        begin[8]  = (total_len >> 8) & 0xFF
        begin[9]  = (total_len >> 16) & 0xFF
        begin[10] = (total_len >> 24) & 0xFF
        begin[11] = crc32 & 0xFF
        begin[12] = (crc32 >> 8) & 0xFF
        begin[13] = (crc32 >> 16) & 0xFF
        begin[14] = (crc32 >> 24) & 0xFF
        self._write(bytes(begin))

        begin_status = self._read_status(Command.BEGIN_UPLOAD, message_id)
        if not begin_status.ok:
            logger.warning(f"BEGIN_UPLOAD rejected: {begin_status}")
            return begin_status

        # ── UPLOAD_CHUNKs ─────────────────────────────────────
        for idx, chunk in enumerate(chunks):
            pkt = bytearray(REPORT_SIZE)
            pkt[0] = Command.UPLOAD_CHUNK
            pkt[1] = message_id & 0xFF
            pkt[2] = (message_id >> 8) & 0xFF
            pkt[3] = idx & 0xFF
            pkt[4] = (idx >> 8) & 0xFF
            pkt[5 : 5 + len(chunk)] = chunk
            self._write(bytes(pkt))
            self._report_gap()

        # ── COMMIT_UPLOAD ─────────────────────────────────────
        commit = bytearray(REPORT_SIZE)
        commit[0] = Command.COMMIT_UPLOAD
        commit[1] = message_id & 0xFF
        commit[2] = (message_id >> 8) & 0xFF
        self._write(bytes(commit))

        final = self._read_status(Command.COMMIT_UPLOAD, message_id)
        if final.ok:
            logger.info(f"upload complete: {final}")
        else:
            logger.warning(f"upload failed: {final}")
        return final

    def abort(self, message_id: int) -> UploadStatus:
        """Abort an in-progress upload."""
        report = bytearray(REPORT_SIZE)
        report[0] = Command.ABORT_UPLOAD
        report[1] = message_id & 0xFF
        report[2] = (message_id >> 8) & 0xFF
        self._write(bytes(report))
        return self._read_status(Command.ABORT_UPLOAD, message_id)

    def ping(self) -> UploadStatus:
        """Send PING — device responds with 'spark ready'."""
        return self.upload(AppCommand.PING, "ping")

    def round_trip_text(self, app_command: AppCommand, text: str) -> str:
        status = self.upload(app_command, text)
        if not status.ok:
            raise SparkProtocolError(str(status))
        return self.fetch_response()

    def stream_round_trip_text(
        self,
        app_command: AppCommand,
        text: str,
        on_update=None,
        timeout_ms: int = 30000,
        poll_interval_s: float = 0.05,
    ) -> str:
        status = self.upload(app_command, text)
        if not status.ok:
            raise SparkProtocolError(str(status))

        deadline = time.monotonic() + (timeout_ms / 1000.0)
        last_len = -1
        last_text = ""

        while time.monotonic() < deadline:
            info = self.get_response_info()

            if info.total_len != last_len and info.total_len > 0:
                last_text = self.fetch_response(info)
                last_len = info.total_len
                if on_update is not None:
                    on_update(last_text)

            if info.complete:
                return last_text

            time.sleep(poll_interval_s)

        raise SparkProtocolError("Timed out waiting for streamed device response")
