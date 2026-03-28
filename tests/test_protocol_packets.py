import unittest

from core.protocol import (
    PacketParser,
    PKT_BUTTON_PRESS,
    PKT_CONTEXT_NEW,
    PKT_CONTEXT_UPDATE,
    PKT_ERROR,
    PKT_SUMMARIZE_CHUNK,
    PKT_SUMMARIZE_DONE,
    PKT_SUMMARIZE_REQUEST,
    build_button_press,
    build_context_new,
    build_context_update,
    build_error,
    build_summarize_chunk,
    build_summarize_done,
    build_summarize_request,
)


class ProtocolPacketTests(unittest.TestCase):
    def test_context_packets_round_trip_through_parser(self):
        seen = []
        parser = PacketParser(on_packet=seen.append)
        payload = {
            "app_name": "Codex",
            "window_title": "Protocol debug",
            "process_name": "Codex.exe",
            "pid": 42,
            "source": "full_window",
            "tab_title": None,
            "url": None,
            "text": "hello world",
            "timestamp": 123.45,
        }

        parser.feed(build_context_new(payload) + build_context_update(payload))

        self.assertEqual([pkt["type"] for pkt in seen], [PKT_CONTEXT_NEW, PKT_CONTEXT_UPDATE])
        self.assertEqual(seen[0]["app_name"], "Codex")
        self.assertEqual(seen[1]["text"], "hello world")

    def test_summarize_packets_round_trip(self):
        seen = []
        parser = PacketParser(on_packet=seen.append)

        parser.feed(
            build_summarize_request("request")
            + build_summarize_chunk("partial")
            + build_summarize_done()
            + build_error("boom")
        )

        self.assertEqual(
            [pkt["type"] for pkt in seen],
            [PKT_SUMMARIZE_REQUEST, PKT_SUMMARIZE_CHUNK, PKT_SUMMARIZE_DONE, PKT_ERROR],
        )
        self.assertEqual(seen[0]["request"], "request")
        self.assertEqual(seen[1]["text"], "partial")
        self.assertTrue(seen[2]["done"])
        self.assertEqual(seen[3]["message"], "boom")

    def test_button_press_packet_round_trip(self):
        seen = []
        parser = PacketParser(on_packet=seen.append)

        parser.feed(build_button_press(3))

        self.assertEqual(seen, [{"type": PKT_BUTTON_PRESS, "button_id": 3}])


if __name__ == "__main__":
    unittest.main()
