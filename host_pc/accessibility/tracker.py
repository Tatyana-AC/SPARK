"""
Multi-window context tracker.

Tracks the current window and the last 2 previously focused windows,
storing text snapshots so actions can reference context across windows.

Includes unique switch counting: after FLUSH_THRESHOLD unique context
changes, distill_and_flush() is called (placeholder for LLM integration).
"""

import logging
import time
from collections import deque
from typing import TYPE_CHECKING, List, Optional

from .base import TextSource, WindowContextSnapshot, WindowInfo
from ..snapshot_policy import is_relevant_snapshot

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

    If a SparkDB instance is provided, the current snapshot is persisted
    immediately and then updated in place while the same context stays active.
    A new row is inserted only when the context key changes.

    Unique switch counting: a switch is only counted when the
    context_key (app+url for browsers, app+title for others) changes.
    After FLUSH_THRESHOLD unique switches, distill_and_flush() fires.
    """

    MAX_PREVIOUS = 2
    FLUSH_THRESHOLD = 20

    def __init__(self, db: Optional["SparkDB"] = None):
        self._current: Optional[WindowContextSnapshot] = None
        self._current_snapshot_id: Optional[int] = None
        self._previous: deque[WindowContextSnapshot] = deque(maxlen=self.MAX_PREVIOUS)
        self._db = db

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
        and a new persisted snapshot becomes current. If the context_key is
        the same, the current snapshot's text is refreshed in place.
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
            self._current = new_snapshot
            self._current_snapshot_id = self._activate_current_snapshot()
            self._last_context_key = new_snapshot.context_key
            self._unique_switch_count = 1 if self._current_snapshot_id is not None else 0
            logger.info("Context tracking started: key=%s", new_snapshot.context_key)
            return

        same_context = new_snapshot.context_key == self._current.context_key

        if same_context:
            self._current.text = text
            self._current.source = source
            self._current.tab_title = tab_title
            self._current.url = url
            self._current.timestamp = time.time()
            self._current_snapshot_id = self._sync_current_snapshot()
            return

        previous_snapshot = self._current
        if is_relevant_snapshot(previous_snapshot):
            self._previous.appendleft(previous_snapshot)
        self._current = new_snapshot
        self._current_snapshot_id = self._activate_current_snapshot()

        self._last_context_key = new_snapshot.context_key
        if self._current_snapshot_id is not None:
            self._unique_switch_count += 1
            logger.info(
                "Unique switch #%s: %s",
                self._unique_switch_count,
                new_snapshot.context_key,
            )

            total_rows = self._snapshot_count()
            if total_rows > self.FLUSH_THRESHOLD:
                self.distill_and_flush(total_rows)

    def _activate_current_snapshot(self) -> Optional[int]:
        if not self._db or not self._current or not is_relevant_snapshot(self._current):
            return None
        try:
            existing_id = self._db.find_snapshot_id_by_fingerprint(self._current)
            if existing_id is not None:
                self._db.update_snapshot(existing_id, self._current)
                return existing_id
            return self._db.save_snapshot(self._current)
        except Exception as exc:
            logger.error("Failed to activate snapshot in DB: %s", exc)
            return None

    def _sync_current_snapshot(self) -> Optional[int]:
        if not self._db or not self._current:
            return None
        if not is_relevant_snapshot(self._current):
            return None

        try:
            if self._current_snapshot_id is None:
                existing_id = self._db.find_snapshot_id_by_fingerprint(self._current)
                if existing_id is not None:
                    self._db.update_snapshot(existing_id, self._current)
                    return existing_id
                return self._db.save_snapshot(self._current)

            matching_id = self._db.find_snapshot_id_by_fingerprint(
                self._current,
                exclude_id=self._current_snapshot_id,
            )
            if matching_id is not None:
                self._db.update_snapshot(matching_id, self._current)
                return matching_id

            self._db.update_snapshot(self._current_snapshot_id, self._current)
            return self._current_snapshot_id
        except Exception as exc:
            logger.error("Failed to persist current snapshot to DB: %s", exc)
            return self._current_snapshot_id

    def _snapshot_count(self) -> int:
        if not self._db:
            return 0
        cursor = self._db._conn.execute("SELECT COUNT(*) FROM window_snapshots")
        return int(cursor.fetchone()[0])

    def distill_and_flush(self, total_rows: int) -> None:
        """
        Placeholder called after FLUSH_THRESHOLD unique switches.

        Override or extend this method to send accumulated context
        to a local LLM for distillation / summarization.
        """
        if self._db:
            to_delete = total_rows - self.FLUSH_THRESHOLD
            if to_delete > 0:
                self._db.delete_n_oldest_snapshots(to_delete)
                logger.info(
                    "Database maintenance pruned %s records. Total size is now %s.",
                    to_delete,
                    self.FLUSH_THRESHOLD,
                )

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
        self._current_snapshot_id = None
        self._previous.clear()
        self._unique_switch_count = 0
        self._last_context_key = None
