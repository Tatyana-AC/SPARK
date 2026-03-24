import unittest

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


if __name__ == "__main__":
    unittest.main()
