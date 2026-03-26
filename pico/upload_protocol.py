import binascii


REPORT_SIZE = 32
CHUNK_PAYLOAD_SIZE = 27
PROTOCOL_VERSION = 0x0002
MAX_UPLOAD_BYTES = 4096
MAX_CHUNK_COUNT = (MAX_UPLOAD_BYTES + CHUNK_PAYLOAD_SIZE - 1) // CHUNK_PAYLOAD_SIZE
CAPABILITY_FLAGS = 0x00
ENCODING_UTF8 = 0x01
RESPONSE_FLAG_COMPLETE = 0x01
RESPONSE_FLAG_ACTIVE = 0x02


class Command:
    GET_INFO = 0x01
    GET_RESPONSE_INFO = 0x20
    GET_RESPONSE_CHUNK = 0x21
    BEGIN_UPLOAD = 0x10
    UPLOAD_CHUNK = 0x11
    COMMIT_UPLOAD = 0x12
    ABORT_UPLOAD = 0x13
    STATUS = 0x7F


class StatusCode:
    OK = 0x00
    BUSY = 0x01
    INVALID_STATE = 0x02
    INVALID_LENGTH = 0x03
    INVALID_INDEX = 0x04
    CRC_MISMATCH = 0x05
    TOO_LARGE = 0x06
    UNSUPPORTED_COMMAND = 0x07
    INCOMPLETE_UPLOAD = 0x08
    INTERNAL_ERROR = 0x09


class AppCommand:
    SUBMIT_TEXT = 0x0001
    PING = 0x0002
    FEATURE_1 = 0x0101
    FEATURE_2 = 0x0102
    FEATURE_3 = 0x0103
    FEATURE_4 = 0x0104


VALID_APP_COMMANDS = {
    AppCommand.SUBMIT_TEXT,
    AppCommand.PING,
    AppCommand.FEATURE_1,
    AppCommand.FEATURE_2,
    AppCommand.FEATURE_3,
    AppCommand.FEATURE_4,
}


class UploadProtocolHandler:
    def __init__(self, text_preparer=None):
        self._text_preparer = text_preparer or self._default_prepare_text
        self._pending_typeback = []
        self._response_bytes = b""
        self._response_complete = False
        self._response_active = False
        self._reset_upload()

    @staticmethod
    def _u16(report, offset):
        return report[offset] | (report[offset + 1] << 8)

    @staticmethod
    def _u32(report, offset):
        return (
            report[offset]
            | (report[offset + 1] << 8)
            | (report[offset + 2] << 16)
            | (report[offset + 3] << 24)
        )

    @staticmethod
    def _write_u16(report, offset, value):
        report[offset] = value & 0xFF
        report[offset + 1] = (value >> 8) & 0xFF

    @staticmethod
    def _write_u32(report, offset, value):
        report[offset] = value & 0xFF
        report[offset + 1] = (value >> 8) & 0xFF
        report[offset + 2] = (value >> 16) & 0xFF
        report[offset + 3] = (value >> 24) & 0xFF

    @staticmethod
    def _default_prepare_text(app_command, text):
        if app_command == AppCommand.PING:
            return {
                "typed_text": "",
                "typable_count": 0,
                "skipped_count": 0,
                "detail": "spark ready",
            }

        if app_command != AppCommand.SUBMIT_TEXT:
            raise ValueError("unsupported app command")

        return {
            "accepted_text": text,
            "accepted_count": len(text),
            "skipped_count": 0,
            "detail": "accepted",
        }

    def has_pending_typeback(self):
        return bool(self._pending_typeback)

    def dequeue_typeback_text(self):
        if not self._pending_typeback:
            return None
        return self._pending_typeback.pop(0)

    def handle_report(self, report):
        if len(report) == REPORT_SIZE + 1:
            report = report[1:]

        if len(report) != REPORT_SIZE:
            raise ValueError(f"expected {REPORT_SIZE}-byte report")

        command = report[0]
        if command == Command.GET_INFO:
            return self._handle_get_info()
        if command == Command.GET_RESPONSE_INFO:
            return self._handle_get_response_info()
        if command == Command.GET_RESPONSE_CHUNK:
            return self._handle_get_response_chunk(report)
        if command == Command.BEGIN_UPLOAD:
            return self._handle_begin(report)
        if command == Command.UPLOAD_CHUNK:
            return self._handle_chunk(report)
        if command == Command.COMMIT_UPLOAD:
            return self._handle_commit(report)
        if command == Command.ABORT_UPLOAD:
            return self._handle_abort(report)
        return self._status(command, 0, StatusCode.UNSUPPORTED_COMMAND, detail="unsupported")

    def _handle_get_info(self):
        report = bytearray(REPORT_SIZE)
        report[0] = Command.GET_INFO
        self._write_u16(report, 1, PROTOCOL_VERSION)
        report[3] = CHUNK_PAYLOAD_SIZE
        self._write_u32(report, 4, MAX_UPLOAD_BYTES)
        self._write_u16(report, 8, MAX_CHUNK_COUNT)
        report[10] = CAPABILITY_FLAGS
        report[11] = 1 if self._active else 0
        self._write_u16(report, 12, self._message_id if self._active else 0)
        return bytes(report)

    def _handle_begin(self, report):
        message_id = self._u16(report, 1)
        app_command = self._u16(report, 3)
        encoding = report[5]
        total_len = self._u32(report, 7)
        expected_crc32 = self._u32(report, 11)

        if self._active:
            return self._status(Command.BEGIN_UPLOAD, message_id, StatusCode.BUSY, detail="busy")
        if encoding != ENCODING_UTF8:
            return self._status(Command.BEGIN_UPLOAD, message_id, StatusCode.INVALID_LENGTH, detail="encoding")
        if total_len > MAX_UPLOAD_BYTES:
            return self._status(Command.BEGIN_UPLOAD, message_id, StatusCode.TOO_LARGE, detail="too large")
        if app_command not in VALID_APP_COMMANDS:
            return self._status(Command.BEGIN_UPLOAD, message_id, StatusCode.UNSUPPORTED_COMMAND, detail="app cmd")

        self._active = True
        self._message_id = message_id
        self._app_command = app_command
        self._expected_crc32 = expected_crc32
        self._total_len = total_len
        self._chunk_count = (total_len + CHUNK_PAYLOAD_SIZE - 1) // CHUNK_PAYLOAD_SIZE if total_len else 0
        self._buffer = bytearray(total_len)
        self._received = [False] * self._chunk_count
        return self._status(Command.BEGIN_UPLOAD, message_id, StatusCode.OK)

    def _handle_get_response_info(self):
        report = bytearray(REPORT_SIZE)
        report[0] = Command.GET_RESPONSE_INFO
        self._write_u32(report, 1, len(self._response_bytes))
        chunk_count = (len(self._response_bytes) + CHUNK_PAYLOAD_SIZE - 1) // CHUNK_PAYLOAD_SIZE if self._response_bytes else 0
        self._write_u16(report, 5, chunk_count)
        flags = 0
        if self._response_complete:
            flags |= RESPONSE_FLAG_COMPLETE
        if self._response_active:
            flags |= RESPONSE_FLAG_ACTIVE
        report[7] = flags
        return bytes(report)

    def _handle_get_response_chunk(self, report):
        index = self._u16(report, 1)
        chunk_count = (len(self._response_bytes) + CHUNK_PAYLOAD_SIZE - 1) // CHUNK_PAYLOAD_SIZE if self._response_bytes else 0
        if index >= chunk_count:
            return self._status(Command.GET_RESPONSE_CHUNK, 0, StatusCode.INVALID_INDEX, detail="index")

        start = index * CHUNK_PAYLOAD_SIZE
        end = min(start + CHUNK_PAYLOAD_SIZE, len(self._response_bytes))
        reply = bytearray(REPORT_SIZE)
        reply[0] = Command.GET_RESPONSE_CHUNK
        reply[1] = index & 0xFF
        reply[2:2 + (end - start)] = self._response_bytes[start:end]
        return bytes(reply)

    def _handle_chunk(self, report):
        message_id = self._u16(report, 1)
        index = self._u16(report, 3)

        if not self._active or message_id != self._message_id:
            return self._status(Command.UPLOAD_CHUNK, message_id, StatusCode.INVALID_STATE, detail="inactive")
        if index >= self._chunk_count:
            return self._status(Command.UPLOAD_CHUNK, message_id, StatusCode.INVALID_INDEX, detail="index")

        start = index * CHUNK_PAYLOAD_SIZE
        end = min(start + CHUNK_PAYLOAD_SIZE, self._total_len)
        chunk_len = max(0, end - start)
        self._buffer[start:end] = report[5 : 5 + chunk_len]
        self._received[index] = True
        return None

    def _handle_commit(self, report):
        message_id = self._u16(report, 1)

        if not self._active or message_id != self._message_id:
            return self._status(Command.COMMIT_UPLOAD, message_id, StatusCode.INVALID_STATE, detail="inactive")
        if self._received and not all(self._received):
            self._reset_upload()
            return self._status(Command.COMMIT_UPLOAD, message_id, StatusCode.INCOMPLETE_UPLOAD, detail="missing")

        payload = bytes(self._buffer)
        crc32 = binascii.crc32(payload) & 0xFFFFFFFF
        if crc32 != self._expected_crc32:
            self._reset_upload()
            return self._status(Command.COMMIT_UPLOAD, message_id, StatusCode.CRC_MISMATCH, detail="crc")

        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            self._reset_upload()
            return self._status(Command.COMMIT_UPLOAD, message_id, StatusCode.INVALID_LENGTH, detail="utf8")

        if self._app_command == AppCommand.PING:
            prepared = {
                "accepted_text": "",
                "accepted_count": 0,
                "skipped_count": 0,
                "detail": "spark ready",
            }
        else:
            try:
                prepared = self._text_preparer(self._app_command, text)
            except ValueError:
                self._reset_upload()
                return self._status(Command.COMMIT_UPLOAD, message_id, StatusCode.UNSUPPORTED_COMMAND, detail="app cmd")
            except Exception:
                self._reset_upload()
                return self._status(Command.COMMIT_UPLOAD, message_id, StatusCode.INTERNAL_ERROR, detail="prepare")

        accepted_text = prepared.get("accepted_text", "")
        response_text = prepared.get("response_text", accepted_text)
        accepted_count = int(prepared.get("accepted_count", len(accepted_text)))
        skipped_count = int(prepared.get("skipped_count", 0))
        detail = prepared.get("detail", "ok")
        status_code = int(prepared.get("status_code", StatusCode.OK))
        response_complete = bool(prepared.get("response_complete", True))
        response_active = bool(prepared.get("response_active", False))

        if status_code != StatusCode.OK:
            self._reset_upload()
            return self._status(
                Command.COMMIT_UPLOAD,
                message_id,
                status_code,
                value0=accepted_count,
                value1=skipped_count,
                detail=detail,
            )

        self.update_response_state(
            response_text.encode("utf-8"),
            complete=response_complete,
            active=response_active,
        )

        self._reset_upload()
        return self._status(
            Command.COMMIT_UPLOAD,
            message_id,
            StatusCode.OK,
            value0=accepted_count,
            value1=skipped_count,
            detail=detail,
        )

    def update_response_state(self, response_bytes, complete=False, active=False):
        self._response_bytes = bytes(response_bytes)
        self._response_complete = bool(complete)
        self._response_active = bool(active)

    def _handle_abort(self, report):
        message_id = self._u16(report, 1)

        if not self._active or message_id != self._message_id:
            return self._status(Command.ABORT_UPLOAD, message_id, StatusCode.INVALID_STATE, detail="inactive")
        self._reset_upload()
        return self._status(Command.ABORT_UPLOAD, message_id, StatusCode.OK)

    def _status(self, related_cmd, message_id, status_code, value0=0, value1=0, detail=""):
        report = bytearray(REPORT_SIZE)
        report[0] = Command.STATUS
        report[1] = int(related_cmd) & 0xFF
        self._write_u16(report, 2, message_id)
        report[4] = int(status_code) & 0xFF
        self._write_u32(report, 6, value0)
        self._write_u32(report, 10, value1)
        detail_bytes = detail.encode("utf-8")[:18]
        report[14 : 14 + len(detail_bytes)] = detail_bytes
        return bytes(report)

    def _reset_upload(self):
        self._active = False
        self._message_id = 0
        self._app_command = None
        self._expected_crc32 = 0
        self._total_len = 0
        self._chunk_count = 0
        self._buffer = bytearray()
        self._received = []
