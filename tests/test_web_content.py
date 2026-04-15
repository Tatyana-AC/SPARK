import unittest
from unittest import mock

from host_pc import web_content


class WebContentExtractorTests(unittest.TestCase):
    def test_google_docs_prefers_export_first_strategy(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(
            extractor,
            "_run_js",
            return_value="exported doc text",
        ) as run_js:
            result = extractor.extract_page(
                "https://docs.google.com/document/d/abc/edit",
                "Google Chrome",
                platform="darwin",
            )

        self.assertEqual(result.text, "exported doc text")
        self.assertEqual(result.source, "google_docs_live")
        self.assertEqual(run_js.call_count, 1)
        self.assertIn("/export?format=txt", run_js.call_args.args[0])

    def test_windows_external_url_uses_http_fallback(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(
            web_content,
            "_extract_http_text",
            return_value=web_content.BrowserExtractionResult(
                text="fetched page text",
                source="http_fallback",
                title=None,
                error=None,
            ),
        ) as extract_http:
            result = extractor.extract_page(
                "https://example.com/article",
                "Google Chrome",
                platform="win32",
            )

        self.assertEqual(result.source, "http_fallback")
        self.assertEqual(result.text, "fetched page text")
        extract_http.assert_called_once_with("https://example.com/article")

    def test_windows_unsupported_browser_returns_structured_failure(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(
            web_content,
            "_extract_http_text",
        ) as extract_http:
            result = extractor.extract_page(
                "https://example.com/article",
                "Not A Browser",
                platform="win32",
            )

        self.assertEqual(result.source, "unsupported")
        self.assertIsNone(result.text)
        self.assertEqual(
            result.error,
            "Windows browser extraction does not support app_name='Not A Browser'",
        )
        extract_http.assert_not_called()

    def test_windows_localhost_url_is_non_fetchable_browser_text_case(self):
        extractor = web_content.WebContentExtractor()

        result = extractor.extract_page(
            "http://localhost:8000/dashboard",
            "Chrome",
            platform="win32",
        )

        self.assertIsNone(result.text)
        self.assertEqual(result.source, "non_fetchable")
        self.assertEqual(
            result.error,
            "Windows browser extraction does not fetch localhost, loopback, or file URLs",
        )

    def test_windows_file_url_is_non_fetchable_browser_text_case(self):
        extractor = web_content.WebContentExtractor()

        result = extractor.extract_page(
            "file:///tmp/index.html",
            "Chrome",
            platform="win32",
        )

        self.assertIsNone(result.text)
        self.assertEqual(result.source, "non_fetchable")
        self.assertEqual(
            result.error,
            "Windows browser extraction does not fetch localhost, loopback, or file URLs",
        )

    def test_http_fallback_handles_missing_requests_module(self):
        real_import = __import__

        def import_without_requests(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "requests":
                raise ModuleNotFoundError("No module named 'requests'")
            if name == "trafilatura":
                return mock.Mock()
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=import_without_requests):
            result = web_content._extract_http_text("https://example.com/article")

        self.assertEqual(result.source, "http_fallback")
        self.assertIsNone(result.text)
        self.assertEqual(result.error, "requests is not installed")

    def test_google_docs_uses_dom_fallback_when_export_is_empty(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(
            extractor,
            "_run_js",
            side_effect=["", "fallback doc text"],
        ) as run_js:
            result = extractor.extract_page(
                "https://docs.google.com/document/d/abc/edit",
                "Google Chrome",
                platform="darwin",
            )

        self.assertEqual(result.text, "fallback doc text")
        self.assertEqual(result.source, "google_docs_live")
        self.assertEqual(run_js.call_count, 2)
        self.assertIn(
            "/export?format=txt",
            run_js.call_args_list[0].args[0],
        )
        self.assertIn(
            ".kix-lineview-text-block",
            run_js.call_args_list[1].args[0],
        )

    def test_get_page_text_still_returns_only_text(self):
        extractor = web_content.WebContentExtractor()

        result = web_content.BrowserExtractionResult(
            text="plain text",
            source="something",
            title=None,
            error=None,
        )

        with mock.patch.object(
            extractor,
            "extract_page",
            return_value=result,
        ):
            self.assertEqual(
                extractor.get_page_text("https://example.com", "Google Chrome"),
                "plain text",
            )


if __name__ == "__main__":
    unittest.main()
