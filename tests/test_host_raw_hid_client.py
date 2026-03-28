import unittest
from unittest import mock

from host_pc.raw_hid import AppCommand, RAW_REPORT_ID, REPORT_SIZE, SparkHIDClient, StatusCode, UploadStatus


class FakeHidDevice:
    def __init__(self, reads=None):
        self.reads = list(reads or [])
        self.writes = []

    def write(self, payload):
        self.writes.append(payload)
        return len(payload)

    def read(self, size, timeout_ms):
        if self.reads:
            return self.reads.pop(0)
        return []


class HostRawHidClientTests(unittest.TestCase):
    def test_write_prefixes_report_id(self):
        client = SparkHIDClient()
        fake = FakeHidDevice()
        client._device = fake

        client._write(bytes([0x01]) + bytes(REPORT_SIZE - 1))

        self.assertEqual(fake.writes[0][0], RAW_REPORT_ID)
        self.assertEqual(len(fake.writes[0]), REPORT_SIZE + 1)

    def test_read_strips_matching_report_id_prefix(self):
        client = SparkHIDClient()
        report = bytes([0x7F]) + bytes(REPORT_SIZE - 1)
        fake = FakeHidDevice(reads=[[RAW_REPORT_ID, *report]])
        client._device = fake

        received = client._read()

        self.assertEqual(received, report)

    def test_get_info_skips_unrelated_status_before_info_reply(self):
        client = SparkHIDClient()

        status = bytearray(REPORT_SIZE)
        status[0] = 0x7F

        info = bytearray(REPORT_SIZE)
        info[0] = 0x01
        info[1] = 0x02
        info[3] = 27
        info[4] = 0x00
        info[5] = 0x10
        info[8] = 0x98

        reads = iter([bytes(status), bytes(info)])
        writes = []
        client._write = lambda payload: writes.append(payload)
        client._read = lambda timeout_ms=2000: next(reads)

        result = client.get_info()

        self.assertEqual(result.protocol_version, 0x0002)
        self.assertEqual(result.chunk_payload_size, 27)
        self.assertEqual(result.max_upload_bytes, 4096)
        self.assertEqual(result.max_chunk_count, 152)
        self.assertEqual(writes[0][0], 0x01)

    def test_upload_inserts_report_gap_after_each_chunk_write(self):
        client = SparkHIDClient()
        writes = []
        gap_calls = []
        statuses = iter(
            [
                UploadStatus(message_id=1, code=StatusCode.OK, value0=0, value1=0, detail=""),
                UploadStatus(message_id=1, code=StatusCode.OK, value0=0, value1=0, detail=""),
            ]
        )

        client._write = lambda payload: writes.append(payload)
        client._read_status = lambda expected_cmd, message_id, timeout_ms=2000: next(statuses)
        client._report_gap = lambda: gap_calls.append("gap")

        result = client.upload(AppCommand.SUBMIT_TEXT, "a" * 28)

        self.assertTrue(result.ok)
        self.assertEqual(len(writes), 4)
        self.assertEqual(len(gap_calls), 2)

    def test_fetch_response_reads_info_then_chunks(self):
        client = SparkHIDClient()

        def fake_read():
            info = bytearray(REPORT_SIZE)
            info[0] = 0x20
            info[1] = 10
            info[5] = 1
            chunk = bytearray(REPORT_SIZE)
            chunk[0] = 0x21
            chunk[1] = 0
            chunk[2:12] = b"hello pico"
            yield bytes(info)
            yield bytes(chunk)

        reads = fake_read()
        writes = []
        client._write = lambda payload: writes.append(payload)
        client._read = lambda timeout_ms=2000: next(reads)

        response = client.fetch_response()

        self.assertEqual(response, "hello pico")
        self.assertEqual(writes[0][0], 0x20)
        self.assertEqual(writes[1][0], 0x21)

    def test_round_trip_text_uploads_then_fetches_response(self):
        client = SparkHIDClient()
        status = UploadStatus(message_id=7, code=StatusCode.OK, value0=3, value1=0, detail="ok")

        with (
            mock.patch.object(client, "upload", return_value=status) as upload,
            mock.patch.object(client, "fetch_response", return_value="PICO ECHO: hi") as fetch_response,
        ):
            result = client.round_trip_text(AppCommand.SUBMIT_TEXT, "hi")

        self.assertEqual(result, "PICO ECHO: hi")
        upload.assert_called_once_with(AppCommand.SUBMIT_TEXT, "hi")
        fetch_response.assert_called_once_with()

    def test_read_status_skips_unrelated_status_before_expected_status(self):
        client = SparkHIDClient()

        first = bytearray(REPORT_SIZE)
        first[0] = 0x7F
        first[1] = 0x10
        first[2] = 7

        second = bytearray(REPORT_SIZE)
        second[0] = 0x7F
        second[1] = 0x12
        second[2] = 7

        reads = iter([bytes(first), bytes(second)])
        client._read = lambda timeout_ms=2000: next(reads)

        status = client._read_status(0x12, 7)

        self.assertEqual(status.code, StatusCode.OK)

    def test_fetch_response_skips_repeated_info_report_before_chunk(self):
        client = SparkHIDClient()

        info = bytearray(REPORT_SIZE)
        info[0] = 0x20
        info[1] = 10
        info[5] = 1

        chunk = bytearray(REPORT_SIZE)
        chunk[0] = 0x21
        chunk[1] = 0
        chunk[2:12] = b"hello pico"

        reads = iter([bytes(info), bytes(info), bytes(chunk)])
        client._write = lambda payload: None
        client._read = lambda timeout_ms=2000: next(reads)

        response = client.fetch_response()

        self.assertEqual(response, "hello pico")

    def test_get_response_info_parses_flags(self):
        client = SparkHIDClient()
        writes = []

        info = bytearray(REPORT_SIZE)
        info[0] = 0x20
        info[1] = 11
        info[5] = 1
        info[7] = 0b11

        client._write = lambda payload: writes.append(payload)
        client._read = lambda timeout_ms=2000: bytes(info)

        result = client.get_response_info()

        self.assertEqual(result.total_len, 11)
        self.assertEqual(result.chunk_count, 1)
        self.assertTrue(result.complete)
        self.assertTrue(result.active)
        self.assertEqual(writes[0][0], 0x20)

    def test_stream_round_trip_text_emits_partial_updates_until_complete(self):
        client = SparkHIDClient()
        updates = []

        info_sequence = iter(
            [
                mock.Mock(total_len=0, chunk_count=0, complete=False, active=True),
                mock.Mock(total_len=7, chunk_count=1, complete=False, active=True),
                mock.Mock(total_len=14, chunk_count=1, complete=False, active=True),
                mock.Mock(total_len=14, chunk_count=1, complete=True, active=False),
            ]
        )

        with (
            mock.patch.object(client, "upload", return_value=UploadStatus(message_id=1, code=StatusCode.OK, value0=0, value1=0, detail="")),
            mock.patch.object(client, "get_response_info", side_effect=lambda: next(info_sequence)),
            mock.patch.object(client, "fetch_response", side_effect=["Partial", "Partial output"]),
            mock.patch("host_pc.raw_hid.time.sleep", return_value=None),
        ):
            result = client.stream_round_trip_text(
                AppCommand.FEATURE_1,
                "request",
                on_update=updates.append,
                timeout_ms=100,
                poll_interval_s=0,
            )

        self.assertEqual(result, "Partial output")
        self.assertEqual(updates, ["Partial", "Partial output"])


if __name__ == "__main__":
    unittest.main()
