import unittest
from unittest import mock

from host_pc import web_content_windows


class FakeControl:
    def __init__(self, text: str, control_type: str = "Text"):
        self._text = text
        self._control_type = control_type

    def control_type(self):
        return self._control_type


class FakeWindow:
    def __init__(self, title: str = "Chrome Window"):
        self._title = title

    def window_text(self):
        return self._title


class WebContentWindowsTests(unittest.TestCase):
    def test_useful_live_candidate_selected_over_browser_shell_candidate(self):
        noise = FakeControl(
            text=(
                "Back Forward Reload Address Search Bookmarks Extensions Apps Settings Profile "
                "Bookmarks Extensions Apps Profile" * 3
            ),
            control_type="Pane",
        )
        content = FakeControl(
            text=(
                "This is a real page transcript with enough distinct words "
                "to be considered useful document content for scoring."
            ),
            control_type="Document",
        )

        with (
            mock.patch.object(
                web_content_windows.browser_windows,
                "_connect_to_active_window",
                return_value=object(),
            ),
            mock.patch.object(
                web_content_windows,
                "_collect_candidate_controls",
                return_value=[noise, content],
            ),
            mock.patch.object(
                web_content_windows.browser_windows,
                "_control_text",
                side_effect=[noise._text, content._text],
            ),
        ):
            result = web_content_windows.extract_windows_live_tab_text(
                "https://example.com/article",
                "Chrome",
                window_target=123,
            )

        self.assertTrue(result.is_useful)
        self.assertEqual(result.source, "uia_document")
        self.assertEqual(result.error, None)
        self.assertGreater(result.quality_score, 0.0)

    def test_dependency_failure_in_live_extraction_fails_soft(self):
        with mock.patch.object(
            web_content_windows.browser_windows,
            "_connect_to_active_window",
            side_effect=RuntimeError("missing dependency"),
        ):
            result = web_content_windows.extract_windows_live_tab_text(
                "https://example.com/article",
                "Chrome",
                window_target=456,
            )

        self.assertFalse(result.is_useful)
        self.assertEqual(result.source, "live_tab")
        self.assertEqual(result.text, None)

    def test_focused_fallback_rejects_browser_shell_noise(self):
        result = web_content_windows.evaluate_focused_fallback(
            "Bookmarks Extensions Apps Settings Profile Search Address Bar Reload Back"
            " Forward Home",
        )

        self.assertFalse(result.is_useful)
        self.assertEqual(result.source, "focused_element")
        self.assertEqual(result.error, "candidate text rejected by heuristics")

    def test_focused_fallback_rejects_short_text(self):
        result = web_content_windows.evaluate_focused_fallback("Home Settings")

        self.assertFalse(result.is_useful)
        self.assertIsNone(result.text)
        self.assertEqual(result.error, "candidate text is too short")

    def test_window_fallback_accepts_useful_text(self):
        result = web_content_windows.evaluate_window_fallback(
            "This is a longer sentence with a variety of words that reads like normal page content."
            " It should pass the usefulness checks with enough length and token variety."
        )

        self.assertTrue(result.is_useful)
        self.assertEqual(result.source, "full_window")
        self.assertIsNotNone(result.text)

    def test_window_fallback_rejects_mixed_browser_shell_noise_even_with_page_words(self):
        result = web_content_windows.evaluate_window_fallback(
            "Bookmarks Boston Tea Party article Search Wikipedia Extensions Grammarly uBlock Origin "
            "The Boston Tea Party was a political protest by the Sons of Liberty in Boston. "
            "Profile Settings Menu"
        )

        self.assertFalse(result.is_useful)
        self.assertEqual(result.source, "full_window")
        self.assertEqual(result.error, "candidate text rejected by heuristics")

    def test_tokenize_supports_non_ascii_text(self):
        tokens = web_content_windows._tokenize("这是一个非ASCII中文示例文本用于检验。")
        self.assertGreater(len(tokens), 1)

    def test_unicode_window_fallback_accepts_non_ascii_page_text(self):
        result = web_content_windows.evaluate_window_fallback(
            "这是一个较长的中文页面文本示例，用于验证页面内容提取器在没有空格时仍能判定为高质量文本。"
        )

        self.assertTrue(result.is_useful)
        self.assertEqual(result.source, "full_window")
        self.assertIsNotNone(result.text)

    def test_timeout_failure_in_live_extraction_is_non_fatal(self):
        fake_window = object()

        with (
            mock.patch.object(
                web_content_windows,
                "WINDOWS_LIVE_EXTRACTION_BUDGET_SECONDS",
                0.9,
            ),
            mock.patch("host_pc.web_content_windows.time.monotonic", side_effect=[0.0, 0.95]),
            mock.patch.object(
                web_content_windows.browser_windows,
                "_connect_to_active_window",
                return_value=fake_window,
            ),
            mock.patch.object(
                web_content_windows,
                "_collect_candidate_controls",
                return_value=[object()],
            ),
        ):
            result = web_content_windows.extract_windows_live_tab_text(
                "https://example.com/article",
                "Chrome",
                window_target=789,
            )

        self.assertFalse(result.is_useful)
        self.assertEqual(result.source, "live_tab")
        self.assertEqual(result.error, "Windows live extraction timed out")

    def test_live_extraction_preserves_useful_candidate_after_slow_collection(self):
        content = FakeControl(
            text=(
                "The Boston Tea Party was a political protest by the Sons of Liberty "
                "in Boston, Massachusetts, on December 16, 1773."
            ),
            control_type="Document",
        )

        def slow_collect(_window):
            import time as real_time

            real_time.sleep(0.02)
            return [content]

        with (
            mock.patch.object(
                web_content_windows.browser_windows,
                "_connect_to_active_window",
                return_value=FakeWindow("Boston Tea Party - Wikipedia - Google Chrome"),
            ),
            mock.patch.object(
                web_content_windows,
                "_collect_candidate_controls",
                side_effect=slow_collect,
            ),
            mock.patch.object(
                web_content_windows.browser_windows,
                "_control_text",
                return_value=content._text,
            ),
            mock.patch(
                "host_pc.web_content_windows.time.monotonic",
                side_effect=[0.0, 0.01],
            ),
            mock.patch.object(
                web_content_windows,
                "WINDOWS_LIVE_EXTRACTION_BUDGET_SECONDS",
                0.01,
            ),
        ):
            result = web_content_windows.extract_windows_live_tab_text(
                "https://en.wikipedia.org/wiki/Boston_Tea_Party",
                "Chrome",
                window_target=123,
            )

        self.assertTrue(result.is_useful)
        self.assertIn("Boston Tea Party", result.text)

    def test_live_extraction_rejects_browser_title_candidate_and_prefers_page_text(self):
        title = FakeControl(
            text="Boston Tea Party - Wikipedia - Google Chrome",
            control_type="Text",
        )
        content = FakeControl(
            text=(
                "The Boston Tea Party was a political protest that occurred on December 16, 1773, "
                "at Griffin's Wharf in Boston, Massachusetts."
            ),
            control_type="Document",
        )

        with (
            mock.patch.object(
                web_content_windows.browser_windows,
                "_connect_to_active_window",
                return_value=FakeWindow("Boston Tea Party - Wikipedia - Google Chrome"),
            ),
            mock.patch.object(
                web_content_windows,
                "_collect_candidate_controls",
                return_value=[title, content],
            ),
            mock.patch.object(
                web_content_windows.browser_windows,
                "_control_text",
                side_effect=[title._text, content._text],
            ),
        ):
            result = web_content_windows.extract_windows_live_tab_text(
                "https://en.wikipedia.org/wiki/Boston_Tea_Party",
                "Chrome",
                window_target=123,
            )

        self.assertTrue(result.is_useful)
        self.assertEqual(result.source, "uia_document")
        self.assertIn("political protest", result.text)

    def test_live_extraction_aggregates_useful_document_fragments(self):
        title = FakeControl(
            text="Boston Tea Party - Wikipedia - Google Chrome",
            control_type="Text",
        )
        frag1 = FakeControl(
            text="From Wikipedia, the free encyclopedia",
            control_type="Text",
        )
        frag2 = FakeControl(
            text="The Boston Tea Party was a political protest that occurred on December 16, 1773,",
            control_type="Document",
        )
        frag3 = FakeControl(
            text="at Griffin's Wharf in Boston, Massachusetts, carried out by the Sons of Liberty.",
            control_type="Document",
        )
        frag4 = FakeControl(
            text="The demonstrators objected to the Tea Act and dumped tea into Boston Harbor.",
            control_type="Document",
        )

        with (
            mock.patch.object(
                web_content_windows.browser_windows,
                "_connect_to_active_window",
                return_value=FakeWindow("Boston Tea Party - Wikipedia - Google Chrome"),
            ),
            mock.patch.object(
                web_content_windows,
                "_collect_candidate_controls",
                return_value=[title, frag1, frag2, frag3, frag4],
            ),
            mock.patch.object(
                web_content_windows.browser_windows,
                "_control_text",
                side_effect=[title._text, frag1._text, frag2._text, frag3._text, frag4._text],
            ),
        ):
            result = web_content_windows.extract_windows_live_tab_text(
                "https://en.wikipedia.org/wiki/Boston_Tea_Party",
                "Chrome",
                window_target=123,
            )

        self.assertTrue(result.is_useful)
        self.assertIn("free encyclopedia", result.text)
        self.assertIn("political protest", result.text)
        self.assertIn("Boston Harbor", result.text)
        self.assertGreater(len(result.text), len(frag2._text))


if __name__ == "__main__":
    unittest.main()
