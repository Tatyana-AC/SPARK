import unittest

from host_pc.accessibility.base import TextSource, WindowInfo
from host_pc.accessibility.tracker import WindowContextTracker


def make_window_info(
    title: str = "Inbox",
    app_name: str = "slack",
    process_name: str = "slack.exe",
    pid: int = 101,
) -> WindowInfo:
    return WindowInfo(
        title=title,
        app_name=app_name,
        process_name=process_name,
        pid=pid,
    )


class WindowContextTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = WindowContextTracker()

    def test_first_update_sets_current_snapshot(self):
        self.tracker.update(
            make_window_info(),
            "hello from slack",
            TextSource.FULL_WINDOW,
        )

        current = self.tracker.get_current()

        self.assertIsNotNone(current)
        self.assertEqual(current.window_info.app_name, "slack")
        self.assertEqual(current.window_info.title, "Inbox")
        self.assertEqual(current.text, "hello from slack")

    def test_same_context_updates_in_place(self):
        self.tracker.update(make_window_info(), "first text", TextSource.FULL_WINDOW)
        first = self.tracker.get_current()

        self.tracker.update(make_window_info(), "updated text", TextSource.FOCUSED_ELEMENT)
        second = self.tracker.get_current()

        self.assertIs(first, second)
        self.assertEqual(second.text, "updated text")
        self.assertEqual(second.source, TextSource.FOCUSED_ELEMENT)

    def test_context_switch_pushes_previous_snapshot(self):
        self.tracker.update(
            make_window_info(title="Inbox", app_name="slack"),
            "slack message body",
            TextSource.FULL_WINDOW,
        )
        self.tracker.update(
            make_window_info(
                title="Project Plan",
                app_name="Codex",
                process_name="codex.exe",
                pid=202,
            ),
            "implementation checklist and notes",
            TextSource.FULL_WINDOW,
        )

        current = self.tracker.get_current()
        previous = self.tracker.get_previous()

        self.assertEqual(current.window_info.app_name, "Codex")
        self.assertIsNotNone(previous)
        self.assertEqual(previous.window_info.app_name, "slack")

    def test_irrelevant_window_is_not_added_to_previous_history(self):
        self.tracker.update(make_window_info(title="Inbox", app_name="slack"), "hello", TextSource.FULL_WINDOW)
        self.tracker.update(
            make_window_info(
                title="Search",
                app_name="SearchHost",
                process_name="SearchHost.exe",
                pid=303,
            ),
            "Search",
            TextSource.FULL_WINDOW,
        )
        self.tracker.update(
            make_window_info(title="Plan", app_name="Codex", process_name="Codex.exe", pid=404),
            "Debug notes",
            TextSource.FULL_WINDOW,
        )

        previous = self.tracker.get_all_previous()

        self.assertEqual(len(previous), 1)
        self.assertEqual(previous[0].window_info.app_name, "slack")


if __name__ == "__main__":
    unittest.main()
