"""
Multi-window context tracker.

Tracks the current window and the last 2 previously focused windows,
storing text snapshots so actions can reference context across windows.

Includes unique switch counting — after FLUSH_THRESHOLD unique context
changes, distill_and_flush() is called (placeholder for LLM integration).
"""

import logging
import time
from collections import deque
from typing import Optional, List, TYPE_CHECKING

from .base import WindowInfo, WindowContextSnapshot, TextSource

if TYPE_CHECKING:
    from ..browser import BrowserTabInfo
    from ..context import Context
    from ..db import SparkDB

logger = logging.getLogger(__name__)


class WindowContextTracker:
    """
    Tracks window context history across window switches.

    Maintains the current window snapshot plus the 2 most recent
    previous windows. Each poll tick should call update() with
    the latest window info and extracted text.

    If a SparkDB instance is provided, snapshots are persisted
    to the database whenever the user switches away from a window.

    Unique switch counting: a switch is only counted when the
    context_key (app+url for browsers, app+title for others) changes.
    After FLUSH_THRESHOLD unique switches, distill_and_flush() fires.
    """

    MAX_PREVIOUS = 2
    FLUSH_THRESHOLD = 20

    def __init__(self, db: Optional["SparkDB"] = None):
        self._current: Optional[WindowContextSnapshot] = None
        self._previous: deque[WindowContextSnapshot] = deque(maxlen=self.MAX_PREVIOUS)
        self._db = db

        # Unique switch tracking
        self._unique_switch_count: int = 0
        self._last_context_key: Optional[str] = None

    def update(
        self,
        window_info: WindowInfo,
        text: str,
        source: TextSource,
        tab: Optional["BrowserTabInfo"] = None,
    ) -> None:
        """
        Update tracker with the latest poll data.

        If the context_key changed, the old snapshot is pushed into history
        (and persisted to DB if available), and a new snapshot becomes current.
        If the context_key is the same, the current snapshot's text is refreshed.

        Args:
            window_info: Active window metadata.
            text: Extracted text content.
            source: How the text was extracted.
            tab: Browser tab info (title + URL), or None for non-browsers.
        """
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
            # First ever update
            self._current = new_snapshot
            self._last_context_key = new_snapshot.context_key
            self._unique_switch_count = 1
            logger.info(f"Context tracking started — key: {new_snapshot.context_key}")
            return

        same_context = new_snapshot.context_key == self._current.context_key

        if same_context:
            # Same context — refresh text in place
            self._current.text = text
            self._current.source = source
            self._current.tab_title = tab_title
            self._current.url = url
            self._current.timestamp = time.time()
        else:
            # Context changed — persist old snapshot then push into history
            if self._db:
                try:
                    self._db.save_snapshot(self._current)
                except Exception as e:
                    logger.error(f"Failed to save snapshot to DB: {e}")
            self._previous.appendleft(self._current)
            self._current = new_snapshot

            # Count unique switch
            self._last_context_key = new_snapshot.context_key
            self._unique_switch_count += 1
            logger.info(
                f"Unique switch #{self._unique_switch_count}: "
                f"{new_snapshot.context_key}"
            )
            cursor = self._db._conn.execute("SELECT COUNT(*) FROM window_snapshots")
            total_rows = cursor.fetchone()[0]

            if total_rows > self.FLUSH_THRESHOLD:
                self.distill_and_flush(total_rows)

    def distill_and_flush(self, total_rows:int ) -> None:
        """
        Placeholder — called after FLUSH_THRESHOLD unique switches.

        Override or extend this method to send accumulated context
        to a local LLM for distillation / summarization.
        """
        if self._db:
            to_delete = total_rows - self.FLUSH_THRESHOLD 
            if to_delete > 0:
                self._db.delete_n_oldest_snapshots(to_delete)
                logger.info(f"Database Maintenance: Pruned {to_delete} records. Total size is now {self.FLUSH_THRESHOLD}.")

        # Reset the session counter since maintenance just ran
        self._unique_switch_count = 0

    def get_current(self) -> Optional[WindowContextSnapshot]:
        """Return the current window snapshot, or None if never updated."""
        return self._current

    def get_current_context(self) -> Optional["Context"]:
        """Build an LLM-ready Context from the current snapshot."""
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
        """
        Return the nth previous window snapshot (1-indexed).

        n=1 is the most recently left window, n=2 the one before that.
        Returns None if that many previous windows haven't been tracked yet.
        """
        idx = n - 1
        if idx < 0 or idx >= len(self._previous):
            return None
        return self._previous[idx]

    def get_all_previous(self) -> List[WindowContextSnapshot]:
        """Return all previous window snapshots, newest first."""
        return list(self._previous)

    @property
    def unique_switch_count(self) -> int:
        """Current unique switch count (resets after flush)."""
        return self._unique_switch_count

    def clear(self) -> None:
        """Reset all tracked context."""
        self._current = None
        self._previous.clear()
        self._unique_switch_count = 0
        self._last_context_key = None
