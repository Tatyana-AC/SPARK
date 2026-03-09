"""
Context class for packaging window + browser state for LLM consumption.

Provides a clean, serializable representation of the user's current
application context that can be passed directly to a local LLM.
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Context:
    """
    A single snapshot of the user's application context.

    For browsers, tab_title and url are populated.
    For non-browser apps, they are None.

    The context_key property gives a stable identity for detecting
    unique switches: app_name + url for browsers, app_name + window_title
    for everything else.
    """
    app_name: str
    window_title: str
    tab_title: Optional[str]
    url: Optional[str]
    text: str
    source: str
    timestamp: float
    pid: int

    @property
    def context_key(self) -> str:
        """Unique identity for switch detection.

        Browsers:     app_name|url
        Non-browsers: app_name|window_title
        """
        if self.url:
            return f"{self.app_name}|{self.url}"
        return f"{self.app_name}|{self.window_title}"

    def to_dict(self) -> dict:
        """Serialize to a plain dict for LLM prompt building or JSON export."""
        return asdict(self)
