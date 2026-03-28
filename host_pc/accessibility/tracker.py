"""
Multi-window context tracker.

Tracks the current window and the last 2 previously focused windows in memory.
The host no longer persists snapshots locally; Jetson owns durable storage.
"""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, List, Optional

from .base import TextSource, WindowContextSnapshot, WindowInfo
from ..snapshot_policy import is_relevant_snapshot

if TYPE_CHECKING:
    from ..browser import BrowserTabInfo
    from ..context import Context


class WindowContextTracker:
    """Tracks current and previous window context in memory."""

    MAX_PREVIOUS = 2

    def __init__(self):
        self._current: Optional[WindowContextSnapshot] = None
        self._previous: deque[WindowContextSnapshot] = deque(maxlen=self.MAX_PREVIOUS)
        self._last_context_key: Optional[str] = None

    def update(
        self,
        window_info: WindowInfo,
        text: str,
        source: TextSource,
        tab: Optional["BrowserTabInfo"] = None,
    ) -> None:
        tab_title = tab.tab_title if tab else None
        url = tab.url if tab else None

        new_snapshot = WindowContextSnapshot(
            window_info=window_info,
            text=text,
            source=source,
            tab_title=tab_title,
            url=url,
        )

        if self._current is None:
            self._current = new_snapshot
            self._last_context_key = new_snapshot.context_key
            return

        if new_snapshot.context_key == self._current.context_key:
            self._current.text = text
            self._current.source = source
            self._current.tab_title = tab_title
            self._current.url = url
            self._current.timestamp = time.time()
            return

        previous_snapshot = self._current
        if is_relevant_snapshot(previous_snapshot):
            self._previous.appendleft(previous_snapshot)
        self._current = new_snapshot
        self._last_context_key = new_snapshot.context_key

    def get_current(self) -> Optional[WindowContextSnapshot]:
        return self._current

    def get_current_context(self) -> Optional["Context"]:
        from ..context import Context

        snap = self._current
        if snap is None:
            return None
        return Context(
            app_name=snap.window_info.app_name,
            window_title=snap.window_info.title,
            tab_title=snap.tab_title,
            url=snap.url,
            text=snap.text,
            source=snap.source.value,
            timestamp=snap.timestamp,
            pid=snap.window_info.pid,
        )

    def get_previous(self, n: int = 1) -> Optional[WindowContextSnapshot]:
        idx = n - 1
        if idx < 0 or idx >= len(self._previous):
            return None
        return self._previous[idx]

    def get_all_previous(self) -> List[WindowContextSnapshot]:
        return list(self._previous)

    @property
    def last_context_key(self) -> Optional[str]:
        return self._last_context_key

    def clear(self) -> None:
        self._current = None
        self._previous.clear()
        self._last_context_key = None
