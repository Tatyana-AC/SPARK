"""
Cross-platform accessibility manager.

Auto-detects platform and provides unified interface for reading text
from the active application.
"""

import logging
import sys
from typing import Optional

from .base import AccessibilityProvider, WindowInfo, TextContext, TextSource

logger = logging.getLogger(__name__)


class AccessibilityManager:
    """
    Cross-platform accessibility manager.
    
    Automatically detects the platform (macOS, Windows, Linux) and creates
    the appropriate accessibility provider. All methods return None on failure
    to ensure graceful degradation.
    """
    
    def __init__(self):
        """Initialize accessibility manager for current platform."""
        self.provider: Optional[AccessibilityProvider] = None
        self.platform = sys.platform
        self._init_provider()
    
    def _init_provider(self) -> None:
        """Initialize the platform-specific provider."""
        try:
            if self.platform == "darwin":
                # macOS
                from .macos_provider import MacOSAccessibilityProvider
                self.provider = MacOSAccessibilityProvider()
                logger.info("macOS accessibility provider initialized")
            
            elif self.platform == "win32":
                # Windows
                from .windows_provider import WindowsAccessibilityProvider
                self.provider = WindowsAccessibilityProvider()
                logger.info("Windows accessibility provider initialized")
            
            else:
                # Unsupported platform
                logger.warning(f"Unsupported platform: {self.platform}")
                self.provider = None
        
        except Exception as e:
            logger.error(f"Failed to initialize accessibility provider: {e}")
            self.provider = None
    
    def get_context(self, method: str = 'auto') -> Optional[TextContext]:
        """
        Get text context from active application.
        
        Extracts text based on the specified method and returns both the text
        and metadata about its source.
        
        Args:
            method: How to extract text:
                - 'auto': Try selected text first, then focused element, then window
                - 'selected': Only try to get selected text
                - 'focused': Only try to get focused element text
                - 'window': Only try to get all window text
        
        Returns:
            TextContext with extracted text and metadata, or None on failure
        """
        if not self.provider:
            logger.warning("Accessibility provider not available")
            return None
        
        try:
            # Get window info
            window_info = self.provider.get_active_window_info()
            if not window_info:
                logger.warning("Could not get active window info")
                return None
            
            text = None
            source = None
            
            if method == 'auto':
                # Auto mode: try methods in order
                text = self.provider.get_selected_text()
                if text:
                    source = TextSource.SELECTED
                    logger.debug(f"Extracted selected text ({len(text)} chars)")
                else:
                    text = self.provider.get_focused_element_text()
                    if text:
                        source = TextSource.FOCUSED_ELEMENT
                        logger.debug(f"Extracted focused text ({len(text)} chars)")
                    else:
                        text = self.provider.get_window_text()
                        if text:
                            source = TextSource.FULL_WINDOW
                            logger.debug(f"Extracted window text ({len(text)} chars)")
            
            elif method == 'selected':
                text = self.provider.get_selected_text()
                source = TextSource.SELECTED
            
            elif method == 'focused':
                text = self.provider.get_focused_element_text()
                source = TextSource.FOCUSED_ELEMENT
            
            elif method == 'window':
                text = self.provider.get_window_text()
                source = TextSource.FULL_WINDOW
            
            else:
                logger.warning(f"Unknown extraction method: {method}")
                return None
            
            if text:
                return TextContext(
                    text=text,
                    source=source,
                    window_info=window_info,
                    metadata={
                        'method': method,
                        'platform': self.platform,
                        'text_length': len(text),
                        'word_count': len(text.split())
                    }
                )
            else:
                logger.info(f"No text extracted using method: {method}")
                return None
        
        except Exception as e:
            logger.error(f"Failed to get text context: {e}")
            return None
    
    def get_active_app(self) -> Optional[str]:
        """
        Get the name of the active application.
        
        Returns:
            Application name (e.g., 'Safari', 'Google Chrome'), or None
        """
        if not self.provider:
            return None
        
        try:
            window_info = self.provider.get_active_window_info()
            if window_info:
                return window_info.app_name
            return None
        except Exception as e:
            logger.error(f"Failed to get active app: {e}")
            return None
    
    def get_active_window_info(self) -> Optional[WindowInfo]:
        """
        Get detailed information about the active window.
        
        Returns:
            WindowInfo object with title, app name, PID, and bounds, or None
        """
        if not self.provider:
            return None
        
        try:
            return self.provider.get_active_window_info()
        except Exception as e:
            logger.error(f"Failed to get active window info: {e}")
            return None
    
    def is_available(self) -> bool:
        """
        Check if accessibility system is ready and available.
        
        This checks if the provider was successfully initialized for the platform.
        
        Returns:
            True if accessibility system is ready, False otherwise
        """
        return self.provider is not None
    
    def check_permissions(self) -> bool:
        """
        Check if the application has necessary accessibility permissions.
        
        On macOS, this requires the app to be added to System Preferences.
        On Windows, no special permissions are typically needed.
        
        Returns:
            True if permissions are granted, False otherwise
        """
        if not self.provider:
            logger.warning("Accessibility provider not available")
            return False
        
        try:
            result = self.provider.check_permissions()
            if not result:
                logger.warning("Accessibility permissions not granted")
            return result
        except Exception as e:
            logger.error(f"Failed to check permissions: {e}")
            return False
    
    def request_permissions(self) -> bool:
        """
        Request necessary accessibility permissions from the user.
        
        On macOS, this opens System Settings to the Accessibility pane.
        On Windows, this typically does nothing (no special permissions needed).
        
        Returns:
            True if permissions were granted, False if user declined or error occurred
        """
        if not self.provider:
            logger.warning("Accessibility provider not available")
            return False
        
        try:
            return self.provider.request_permissions()
        except Exception as e:
            logger.error(f"Failed to request permissions: {e}")
            return False
    
    def get_selected_text(self) -> Optional[str]:
        """
        Get only the selected text from active window.
        
        Returns:
            Selected text, or None if nothing selected or operation failed
        """
        if not self.provider:
            return None
        
        try:
            return self.provider.get_selected_text()
        except Exception as e:
            logger.error(f"Failed to get selected text: {e}")
            return None
    
    def get_focused_element_text(self) -> Optional[str]:
        """
        Get only text from the currently focused element.
        
        Returns:
            Focused element text, or None if unavailable
        """
        if not self.provider:
            return None
        
        try:
            return self.provider.get_focused_element_text()
        except Exception as e:
            logger.error(f"Failed to get focused element text: {e}")
            return None
    
    def get_window_text(self) -> Optional[str]:
        """
        Get all text from the active window.

        Returns:
            All window text, or None on failure
        """
        if not self.provider:
            return None

        try:
            return self.provider.get_window_text()
        except Exception as e:
            logger.error(f"Failed to get window text: {e}")
            return None

    def paste_text(self, text: str) -> bool:
        """
        Paste text into the active application.

        Args:
            text: The text to paste

        Returns:
            True if paste succeeded, False otherwise
        """
        if not self.provider:
            logger.warning("Accessibility provider not available")
            return False

        try:
            return self.provider.paste_text(text)
        except Exception as e:
            logger.error(f"Failed to paste text: {e}")
            return False
