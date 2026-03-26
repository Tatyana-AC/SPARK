import unittest
import json


class SummarizeStreamTests(unittest.TestCase):
    def test_build_summary_request_includes_window_metadata_and_visible_text(self):
        from host_pc.summarize_stream import build_summary_request

        payload = build_summary_request(
            app_name="Chrome",
            window_title="ChatGPT - OpenAI",
            window_text="The user is reading notes about the SPARK hardware loop.",
        )

        request = json.loads(payload)

        self.assertEqual(request["command"], "summarize_window")
        self.assertEqual(request["app_name"], "Chrome")
        self.assertEqual(request["window_title"], "ChatGPT - OpenAI")
        self.assertIn("The user is reading notes", request["window_text"])

    def test_summary_stream_accumulator_ignores_ack_and_completes_on_eot(self):
        from host_pc.summarize_stream import SummaryStreamAccumulator

        accumulator = SummaryStreamAccumulator()

        first = accumulator.feed(b"\x06The user is reviewing")
        second = accumulator.feed(b" the active app.\x04")

        self.assertEqual(first.text, "The user is reviewing")
        self.assertFalse(first.completed)
        self.assertEqual(second.text, "The user is reviewing the active app.")
        self.assertTrue(second.completed)

    def test_build_test_summary_request_returns_fixed_debug_context(self):
        from host_pc.summarize_stream import build_test_summary_request

        request = json.loads(build_test_summary_request())

        self.assertEqual(request["command"], "summarize_window")
        self.assertEqual(request["app_name"], "Cursor")
        self.assertIn("Weekly planning", request["window_title"])
        self.assertIn("SPARK host to pico to jetson loop", request["window_text"])


if __name__ == "__main__":
    unittest.main()
