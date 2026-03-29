"""
Base classes and data models for cross-platform accessibility.

Provides abstract interface for platform-specific accessibility implementations
and data structures for text context extraction.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict
from enum import Enum
import time

TEXTLEN = 25
URLLEN = 25
class TextSource(Enum):
    """Source of extracted text."""
    SELECTED = "selected"
    FOCUSED_ELEMENT = "focused_element"
    FULL_WINDOW = "full_window"
    WEB_CONTENT = "web_content"


@dataclass
class WindowInfo:
    """Information about an application window."""
    title: str
    app_name: str
    process_name: str
    pid: int
    bundle_id: Optional[str] = None
    bounds: Optional[Dict[str, int]] = None
    
    def __repr__(self) -> str:
        """String representation of window info."""
        return f"WindowInfo(app={self.app_name}, title={self.title}, pid={self.pid})"


@dataclass
class TextContext:
    """
    Extracted text with metadata.
    
    Contains the actual text and metadata about where it came from
    and what application it was extracted from.
    """
    text: str
    source: TextSource
    window_info: WindowInfo
    metadata: Optional[Dict] = field(default_factory=dict)
    
    def __repr__(self) -> str:
        """String representation of text context."""
        text_preview = self.text[:TEXTLEN] + "..." if len(self.text) > TEXTLEN else self.text
        return f"TextContext(source={self.source.value}, app={self.window_info.app_name}, text={text_preview})"


@dataclass
class WindowContextSnapshot:
    """A snapshot of a window's context at a point in time."""
    window_info: WindowInfo
    text: str
    source: TextSource
    tab_title: Optional[str] = None
    url: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def context_key(self) -> str:
        """Unique identity for switch detection.

        Browsers (url present): app_name|url
        Non-browsers:           app_name|window_title
        """
        if self.url:
            return f"{self.window_info.app_name}|{self.url}"
        return f"{self.window_info.app_name}|{self.window_info.title}"

    def __repr__(self) -> str:
        text_preview = self.text[:TEXTLEN] + "..." if len(self.text) > TEXTLEN else self.text
        return f"WindowContextSnapshot(app={self.window_info.app_name}, text={text_preview})"


class AccessibilityProvider(ABC):
    """
    Abstract base class for platform-specific accessibility providers.
    
    Implementations should handle platform-specific APIs to read text from
    active applications. All methods return None on failure or unavailability.
    """
    
    @abstractmethod
    def get_active_window_info(self) -> Optional[WindowInfo]:
        """
        Get information about the currently active window.
        
        Returns:
            WindowInfo about active window, or None if unavailable
        """
        pass
    
    @abstractmethod
    def get_selected_text(self) -> Optional[str]:
        """
        Get currently selected text in the active window.
        
        Typically simulates Cmd+C (macOS) or Ctrl+C (Windows) to capture selection.
        
        Returns:
            Selected text, or None if nothing is selected or operation failed
        """
        pass
    
    @abstractmethod
    def get_focused_element_text(self) -> Optional[str]:
        """
        Get text from the currently focused element.
        
        Uses accessibility APIs to read from focused input fields, text boxes, etc.
        
        Returns:
            Text from focused element, or None if not available
        """
        pass
    
    @abstractmethod
    def get_window_text(self) -> Optional[str]:
        """
        Get all text content from the active window.
        
        Walks the window tree and extracts all visible text.
        
        Returns:
            Combined text from window, or None if operation failed
        """
        pass
    
    @abstractmethod
    def check_permissions(self) -> bool:
        """
        Check if application has necessary accessibility permissions.
        
        Returns:
            True if permissions are granted, False otherwise
        """
        pass
    
    @abstractmethod
    def request_permissions(self) -> bool:
        """
        Request necessary accessibility permissions from user.

        Returns:
            True if permissions were granted, False otherwise
        """
        pass

    @abstractmethod
    def paste_text(self, text: str) -> bool:
        """
        Paste text into the active application.

        Copies text to clipboard and simulates a paste keystroke.

        Args:
            text: The text to paste

        Returns:
            True if paste succeeded, False otherwise
        """
        pass
