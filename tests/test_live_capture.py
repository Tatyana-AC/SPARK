import unittest

from host_pc.live_capture import LiveCaptureFeed, append_capture_line


class AppendCaptureLineTests(unittest.TestCase):
    def test_dedupes_identical_poll_line_when_requested(self):
        lines = ["[Chrome] hello world"]

        updated = append_capture_line(
            lines,
            "[Chrome] hello world",
            max_lines=6,
            dedupe=True,
        )

        self.assertEqual(updated, ["[Chrome] hello world"])

    def test_capture_entry_is_appended_even_when_text_matches_previous_poll(self):
        lines = ["[Chrome] hello world"]

        updated = append_capture_line(
            lines,
            "[CAPTURED] hello world",
            max_lines=6,
            dedupe=False,
        )

        self.assertEqual(
            updated,
            ["[Chrome] hello world", "[CAPTURED] hello world"],
        )

    def test_keeps_only_the_most_recent_lines(self):
        lines = [f"line {i}" for i in range(6)]

        updated = append_capture_line(
            lines,
            "line 6",
            max_lines=6,
            dedupe=False,
        )

        self.assertEqual(
            updated,
            ["line 1", "line 2", "line 3", "line 4", "line 5", "line 6"],
        )


class LiveCaptureFeedTests(unittest.TestCase):
    def test_same_poll_line_is_not_readded_after_a_capture_event(self):
        feed = LiveCaptureFeed(max_lines=6)

        feed.push_poll_line("[Chrome] hello world")
        feed.push_event_line("[CAPTURED] hello world")
        feed.push_poll_line("[Chrome] hello world")

        self.assertEqual(
            feed.lines,
            ["[Chrome] hello world", "[CAPTURED] hello world"],
        )


if __name__ == "__main__":
    unittest.main()
