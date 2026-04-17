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

    def test_build_summarize_command_is_lightweight(self):
        from host_pc.summarize_stream import build_summarize_command

        payload = build_summarize_command()
        request = json.loads(payload)

        self.assertEqual(request["command"], "summarize")
        self.assertEqual(len(request), 1, "should only contain 'command' key")

    def test_build_test_summary_request_uses_lightweight_command(self):
        from host_pc.summarize_stream import build_test_summary_request

        request = json.loads(build_test_summary_request())

        self.assertEqual(request["command"], "summarize")

    def test_build_reformat_request_trims_and_serializes_selected_text(self):
        from host_pc.summarize_stream import build_reformat_request

        payload = build_reformat_request("   selected text with spaces   ")
        request = json.loads(payload)

        self.assertEqual(request["command"], "reformat_selection")
        self.assertEqual(request["selected_text"], "selected text with spaces")
        self.assertEqual(len(request), 2)

    def test_build_reformat_request_truncates_to_upload_budget(self):
        from host_pc.summarize_stream import build_reformat_request, _MAX_WINDOW_TEXT_CHARS

        payload = build_reformat_request("x" * (_MAX_WINDOW_TEXT_CHARS + 1))
        request = json.loads(payload)

        self.assertEqual(len(request["selected_text"]), _MAX_WINDOW_TEXT_CHARS)

    def test_build_respond_request_trims_and_serializes_previous_user_input(self):
        from host_pc.summarize_stream import build_respond_request

        payload = build_respond_request("  drafted reply so far  ")
        request = json.loads(payload)

        self.assertEqual(request["command"], "respond_selection")
        self.assertEqual(request["previous_user_input"], "drafted reply so far")
        self.assertEqual(len(request), 2)

    def test_build_respond_request_truncates_to_upload_budget(self):
        from host_pc.summarize_stream import build_respond_request, _MAX_WINDOW_TEXT_CHARS

        payload = build_respond_request("x" * (_MAX_WINDOW_TEXT_CHARS + 1))
        request = json.loads(payload)

        self.assertEqual(len(request["previous_user_input"]), _MAX_WINDOW_TEXT_CHARS)

    def test_build_keyword_search_request_trims_and_serializes_selected_text(self):
        from host_pc.summarize_stream import build_keyword_search_request

        payload = build_keyword_search_request("  irrational proof  ")
        request = json.loads(payload)

        self.assertEqual(request["command"], "keyword_search")
        self.assertEqual(request["selected_text"], "irrational proof")
        self.assertEqual(len(request), 2)

    def test_build_keyword_search_request_truncates_to_upload_budget(self):
        from host_pc.summarize_stream import build_keyword_search_request, _MAX_WINDOW_TEXT_CHARS

        payload = build_keyword_search_request("x" * (_MAX_WINDOW_TEXT_CHARS + 1))
        request = json.loads(payload)

        self.assertEqual(len(request["selected_text"]), _MAX_WINDOW_TEXT_CHARS)


if __name__ == "__main__":
    unittest.main()
