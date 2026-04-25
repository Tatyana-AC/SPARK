import unittest
import json


class SummarizeStreamTests(unittest.TestCase):
    def test_build_context_key_prefers_url_over_window_title(self):
        from host_pc.summarize_stream import build_context_key

        context_key = build_context_key(
            app_name="Google Chrome",
            window_title="Boston Tea Party - Wikipedia",
            url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
        )

        self.assertEqual(
            context_key,
            "Google Chrome|https://en.wikipedia.org/wiki/Boston_Tea_Party",
        )

    def test_build_context_key_falls_back_to_window_title_when_url_missing(self):
        from host_pc.summarize_stream import build_context_key

        context_key = build_context_key(
            app_name="Notes",
            window_title="History notes",
            url=None,
        )

        self.assertEqual(context_key, "Notes|History notes")

    def test_build_context_key_rejects_missing_anchor_fields(self):
        from host_pc.summarize_stream import build_context_key

        with self.assertRaises(ValueError):
            build_context_key(app_name="Notes", window_title="   ", url=None)

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

    def test_build_synthesize_session_request_uses_fixed_default_window_and_anchor_key(self):
        from host_pc.summarize_stream import build_synthesize_session_request

        request = json.loads(
            build_synthesize_session_request(
                anchor_context_key="Google Chrome|https://en.wikipedia.org/wiki/Boston_Tea_Party"
            )
        )

        self.assertEqual(request["command"], "synthesize_session")
        self.assertEqual(request["window_minutes"], 30)
        self.assertEqual(
            request["anchor_context_key"],
            "Google Chrome|https://en.wikipedia.org/wiki/Boston_Tea_Party",
        )
        self.assertEqual(len(request), 3)

    def test_build_synthesize_session_request_rejects_non_positive_windows(self):
        from host_pc.summarize_stream import build_synthesize_session_request

        with self.assertRaises(ValueError):
            build_synthesize_session_request("Google Chrome|https://example.com", 0)

    def test_build_synthesize_session_request_rejects_missing_anchor_key(self):
        from host_pc.summarize_stream import build_synthesize_session_request

        with self.assertRaises(ValueError):
            build_synthesize_session_request("   ")

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
