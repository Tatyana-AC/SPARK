import unittest


class JetsonProtocolTests(unittest.TestCase):
    def test_parser_reports_crc_mismatch(self):
        from core.protocol import build_summarize_request
        from jetson.protocol import PacketParser

        events = []
        parser = PacketParser(diagnostic_hook=events.append)
        packet = bytearray(build_summarize_request("hello"))
        packet[-1] ^= 0xFF

        parser.feed(bytes(packet))

        self.assertEqual(events[0]["event"], "crc_mismatch")

    def test_parser_reports_invalid_json_version(self):
        from core.protocol import PKT_SUMMARIZE_REQUEST, build_packet
        from jetson.protocol import PacketParser

        events = []
        parser = PacketParser(diagnostic_hook=events.append)
        packet = build_packet(PKT_SUMMARIZE_REQUEST, bytes([0x00]) + b'{"request":"hello"}')

        parser.feed(packet)

        self.assertEqual(events[0]["event"], "invalid_payload")
        self.assertEqual(events[0]["reason"], "version_mismatch")
