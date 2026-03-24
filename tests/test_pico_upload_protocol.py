import unittest
import zlib


class UploadProtocolTests(unittest.TestCase):
    def setUp(self):
        from pico.upload_protocol import (
            AppCommand,
            Command,
            StatusCode,
            UploadProtocolHandler,
        )

        self.AppCommand = AppCommand
        self.Command = Command
        self.StatusCode = StatusCode
        self.prepared = []

        def prepare_text(app_command, text):
            self.prepared.append((app_command, text))
            return {
                "accepted_text": text,
                "accepted_count": len(text),
                "skipped_count": 0,
                "detail": "accepted",
            }

        self.handler = UploadProtocolHandler(text_preparer=prepare_text)

    def _begin_report(self, *, message_id=7, app_command=None, payload=b"", total_len=None, crc32=None):
        app_command = app_command if app_command is not None else int(self.AppCommand.SUBMIT_TEXT)
        total_len = len(payload) if total_len is None else total_len
        crc32 = zlib.crc32(payload) & 0xFFFFFFFF if crc32 is None else crc32

        report = bytearray(32)
        report[0] = self.Command.BEGIN_UPLOAD
        report[1] = message_id & 0xFF
        report[2] = (message_id >> 8) & 0xFF
        report[3] = app_command & 0xFF
        report[4] = (app_command >> 8) & 0xFF
        report[5] = 0x01
        report[7] = total_len & 0xFF
        report[8] = (total_len >> 8) & 0xFF
        report[9] = (total_len >> 16) & 0xFF
        report[10] = (total_len >> 24) & 0xFF
        report[11] = crc32 & 0xFF
        report[12] = (crc32 >> 8) & 0xFF
        report[13] = (crc32 >> 16) & 0xFF
        report[14] = (crc32 >> 24) & 0xFF
        return bytes(report)

    def _chunk_report(self, *, message_id=7, index=0, chunk=b""):
        report = bytearray(32)
        report[0] = self.Command.UPLOAD_CHUNK
        report[1] = message_id & 0xFF
        report[2] = (message_id >> 8) & 0xFF
        report[3] = index & 0xFF
        report[4] = (index >> 8) & 0xFF
        report[5 : 5 + len(chunk)] = chunk
        return bytes(report)

    def _commit_report(self, *, message_id=7):
        report = bytearray(32)
        report[0] = self.Command.COMMIT_UPLOAD
        report[1] = message_id & 0xFF
        report[2] = (message_id >> 8) & 0xFF
        return bytes(report)

    def _abort_report(self, *, message_id=7):
        report = bytearray(32)
        report[0] = self.Command.ABORT_UPLOAD
        report[1] = message_id & 0xFF
        report[2] = (message_id >> 8) & 0xFF
        return bytes(report)

    def _u16(self, data, offset):
        return data[offset] | (data[offset + 1] << 8)

    def _u32(self, data, offset):
        return (
            data[offset]
            | (data[offset + 1] << 8)
            | (data[offset + 2] << 16)
            | (data[offset + 3] << 24)
        )

    def _detail(self, data):
        return data[14:32].split(b"\x00", 1)[0].decode("utf-8")

    def test_get_info_report_is_stable(self):
        report = bytes([self.Command.GET_INFO]) + bytes(31)

        reply = self.handler.handle_report(report)

        self.assertEqual(reply[0], self.Command.GET_INFO)
        self.assertEqual(self._u16(reply, 1), 0x0002)
        self.assertEqual(reply[3], 27)
        self.assertEqual(self._u32(reply, 4), 4096)
        self.assertEqual(self._u16(reply, 8), 152)
        self.assertEqual(reply[10], 0)
        self.assertEqual(reply[11], 0)
        self.assertEqual(self._u16(reply, 12), 0)

    def test_begin_rejects_oversized_payload(self):
        reply = self.handler.handle_report(self._begin_report(total_len=4097))

        self.assertEqual(reply[0], self.Command.STATUS)
        self.assertEqual(reply[1], self.Command.BEGIN_UPLOAD)
        self.assertEqual(reply[4], self.StatusCode.TOO_LARGE)

    def test_begin_rejects_concurrent_upload(self):
        first = self.handler.handle_report(self._begin_report(message_id=1, payload=b"abc"))
        second = self.handler.handle_report(self._begin_report(message_id=2, payload=b"xyz"))

        self.assertEqual(first[4], self.StatusCode.OK)
        self.assertEqual(second[4], self.StatusCode.BUSY)

    def test_upload_chunk_accepts_out_of_order_chunks_and_commit_succeeds(self):
        payload = b"a" * 27 + b"b" * 27 + b"hello"

        self.handler.handle_report(self._begin_report(message_id=9, payload=payload))
        self.assertIsNone(self.handler.handle_report(self._chunk_report(message_id=9, index=2, chunk=payload[54:])))
        self.assertIsNone(self.handler.handle_report(self._chunk_report(message_id=9, index=0, chunk=payload[:27])))
        self.assertIsNone(self.handler.handle_report(self._chunk_report(message_id=9, index=1, chunk=payload[27:54])))

        reply = self.handler.handle_report(self._commit_report(message_id=9))

        self.assertEqual(reply[4], self.StatusCode.OK)
        self.assertEqual(self._u32(reply, 6), len(payload))
        self.assertEqual(self._u32(reply, 10), 0)
        self.assertEqual(self.prepared, [(self.AppCommand.SUBMIT_TEXT, payload.decode("utf-8"))])
        self.assertFalse(self.handler.has_pending_typeback())

    def test_upload_chunk_rejects_invalid_index(self):
        self.handler.handle_report(self._begin_report(message_id=4, payload=b"abc"))

        reply = self.handler.handle_report(self._chunk_report(message_id=4, index=99, chunk=b"abc"))

        self.assertEqual(reply[4], self.StatusCode.INVALID_INDEX)

    def test_commit_rejects_missing_chunks(self):
        payload = b"a" * 40

        self.handler.handle_report(self._begin_report(message_id=6, payload=payload))
        self.handler.handle_report(self._chunk_report(message_id=6, index=0, chunk=payload[:27]))

        reply = self.handler.handle_report(self._commit_report(message_id=6))

        self.assertEqual(reply[4], self.StatusCode.INCOMPLETE_UPLOAD)

    def test_incomplete_commit_resets_upload_state(self):
        payload = b"a" * 40

        self.handler.handle_report(self._begin_report(message_id=26, payload=payload))
        self.handler.handle_report(self._chunk_report(message_id=26, index=0, chunk=payload[:27]))

        reply = self.handler.handle_report(self._commit_report(message_id=26))
        info = self.handler.handle_report(bytes([self.Command.GET_INFO]) + bytes(31))
        next_begin = self.handler.handle_report(self._begin_report(message_id=27, payload=b"ok"))

        self.assertEqual(reply[4], self.StatusCode.INCOMPLETE_UPLOAD)
        self.assertEqual(info[11], 0)
        self.assertEqual(self._u16(info, 12), 0)
        self.assertEqual(next_begin[4], self.StatusCode.OK)

    def test_commit_rejects_crc_mismatch(self):
        payload = b"hello world"

        self.handler.handle_report(self._begin_report(message_id=11, payload=payload, crc32=0x12345678))
        self.handler.handle_report(self._chunk_report(message_id=11, index=0, chunk=payload))

        reply = self.handler.handle_report(self._commit_report(message_id=11))

        self.assertEqual(reply[4], self.StatusCode.CRC_MISMATCH)

    def test_commit_rejects_invalid_utf8(self):
        payload = b"\xff\xfe\xfd"

        self.handler.handle_report(self._begin_report(message_id=12, payload=payload))
        self.handler.handle_report(self._chunk_report(message_id=12, index=0, chunk=payload))

        reply = self.handler.handle_report(self._commit_report(message_id=12))

        self.assertEqual(reply[4], self.StatusCode.INVALID_LENGTH)

    def test_abort_clears_active_upload(self):
        self.handler.handle_report(self._begin_report(message_id=13, payload=b"abc"))

        reply = self.handler.handle_report(self._abort_report(message_id=13))
        info = self.handler.handle_report(bytes([self.Command.GET_INFO]) + bytes(31))

        self.assertEqual(reply[4], self.StatusCode.OK)
        self.assertEqual(info[11], 0)
        self.assertEqual(self._u16(info, 12), 0)

    def test_submit_text_accepts_unicode_without_skipping(self):
        payload = "hello ✓ 世界".encode("utf-8")

        self.handler.handle_report(self._begin_report(message_id=20, payload=payload))
        self.handler.handle_report(self._chunk_report(message_id=20, index=0, chunk=payload[:27]))
        if len(payload) > 27:
            self.handler.handle_report(self._chunk_report(message_id=20, index=1, chunk=payload[27:54]))

        reply = self.handler.handle_report(self._commit_report(message_id=20))

        self.assertEqual(reply[4], self.StatusCode.OK)
        self.assertEqual(self._u32(reply, 6), len("hello ✓ 世界"))
        self.assertEqual(self._u32(reply, 10), 0)
        self.assertEqual(self._detail(reply), "accepted")

    def test_ping_returns_ready_detail_without_queueing_typeback(self):
        self.handler.handle_report(self._begin_report(message_id=21, app_command=int(self.AppCommand.PING), payload=b"ping"))
        self.handler.handle_report(self._chunk_report(message_id=21, index=0, chunk=b"ping"))

        reply = self.handler.handle_report(self._commit_report(message_id=21))

        self.assertEqual(reply[4], self.StatusCode.OK)
        self.assertEqual(self._detail(reply), "spark ready")
        self.assertEqual(self.prepared, [])

    def test_handle_report_accepts_optional_leading_report_id_byte(self):
        reply = self.handler.handle_report(bytes([0x04, self.Command.GET_INFO]) + bytes(31))

        self.assertEqual(reply[0], self.Command.GET_INFO)


if __name__ == "__main__":
    unittest.main()
