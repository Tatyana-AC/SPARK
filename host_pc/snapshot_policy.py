"""
Rules for deciding which snapshots are worth persisting and how to identify them.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .accessibility.base import WindowContextSnapshot

_WHITESPACE_RE = re.compile(r"\s+")
_IGNORED_APP_NAMES = {"searchhost", "explorer", "soundswitch"}
_IGNORED_PROCESS_NAMES = {"searchhost.exe", "explorer.exe", "soundswitch.exe"}
_IGNORED_TITLES = {"task switching", "search"}


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip().lower()

def is_relevant_snapshot(snapshot: WindowContextSnapshot) -> bool:
    """Return True when the snapshot contains user-meaningful context."""
    app_name = _normalize(snapshot.window_info.app_name)
    process_name = _normalize(snapshot.window_info.process_name)
    title = _normalize(snapshot.window_info.title)
    text = _normalize(snapshot.text)

    if not text:
        return False
    if app_name in _IGNORED_APP_NAMES or process_name in _IGNORED_PROCESS_NAMES:
        return False
    if not title:
        return False
    if title in _IGNORED_TITLES:
        return False
    return True


def snapshot_fingerprint(snapshot: WindowContextSnapshot) -> str:
    """Build a stable fingerprint for deduping revisits to the same context."""
    payload = "|".join(
        (
            _normalize(snapshot.window_info.app_name),
            _normalize(snapshot.url) or _normalize(snapshot.window_info.title),
            _normalize(snapshot.text),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
