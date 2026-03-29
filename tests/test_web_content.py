import unittest
from unittest import mock

from host_pc import web_content


class WebContentExtractorTests(unittest.TestCase):
    def test_get_page_text_returns_none_for_unsupported_browser(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(extractor, "_run_js") as run_js:
            result = extractor.get_page_text("https://example.com", "Firefox")

        self.assertIsNone(result)
        run_js.assert_not_called()

    def test_google_docs_uses_docs_extractor(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(extractor, "_run_js", return_value="doc text") as run_js:
            result = extractor.get_page_text(
                "https://docs.google.com/document/d/123/edit",
                "Google Chrome",
            )

        self.assertEqual(result, "doc text")
        run_js.assert_called_once()
        self.assertIn(".kix-lineview-text-block", run_js.call_args.args[0])

    def test_general_site_uses_body_text_fallback(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(extractor, "_run_js", return_value="site text") as run_js:
            result = extractor.get_page_text("https://example.com", "Safari")

        self.assertEqual(result, "site text")
        self.assertIn("document.body", run_js.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
