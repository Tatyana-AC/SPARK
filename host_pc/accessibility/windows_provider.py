"""
Windows accessibility provider using pywinauto and win32 APIs.

Provides text extraction from the active application using Windows
accessibility APIs (UI Automation) and system clipboard.
"""

import logging
import time
from typing import Optional

from .base import AccessibilityProvider, WindowInfo, TextSource

logger = logging.getLogger(__name__)


class WindowsAccessibilityProvider(AccessibilityProvider):
    """
    Windows implementation of accessibility provider.
    
    Uses pywinauto and win32 APIs to interact with:
    - win32gui: Get active window info
    - win32process: Get process information
    - pywinauto: UI Automation for text extraction
    - Clipboard: For capturing selected text via Ctrl+C
    """
    
    def __init__(self):
        """Initialize Windows accessibility provider."""
        self.win32gui = None
        self.win32process = None
        self.psutil = None
        self.pywinauto = None
        self.ctypes = None
        self._init_libraries()
    
    def _init_libraries(self) -> None:
        """Initialize Windows API libraries."""
        try:
            import win32gui
            import win32process
            import psutil
            from pywinauto import Application
            import ctypes
            
            self.win32gui = win32gui
            self.win32process = win32process
            self.psutil = psutil
            self.pywinauto = Application
            self.ctypes = ctypes
            
            logger.info("Windows accessibility libraries initialized")
        except ImportError as e:
            logger.warning(f"Windows accessibility libraries not available: {e}")
            logger.info("Install with: pip install pywinauto pywin32 psutil")
    
    def get_active_window_info(self) -> Optional[WindowInfo]:
        """
        Get information about the active window.
        
        Uses win32gui.GetForegroundWindow and win32process to get details.
        
        Returns:
            WindowInfo about active window, or None on failure
        """
        if not self.win32gui or not self.win32process:
            return None
        
        try:
            # Get foreground window
            hwnd = self.win32gui.GetForegroundWindow()
            if not hwnd:
                logger.warning("No foreground window found")
                return None
            
            # Get window title
            title = self.win32gui.GetWindowText(hwnd)
            
            # Get process ID
            _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
            
            # Get process name
            process_name = "Unknown"
            try:
                if self.psutil:
                    process = self.psutil.Process(pid)
                    process_name = process.name()
                    app_name = process_name.replace(".exe", "")
                else:
                    app_name = "Unknown"
            except Exception:
                app_name = "Unknown"
            
            # Get window bounds
            try:
                rect = self.win32gui.GetWindowRect(hwnd)
                bounds = {
                    "left": rect[0],
                    "top": rect[1],
                    "right": rect[2],
                    "bottom": rect[3],
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1]
                }
            except Exception:
                bounds = {}
            
            return WindowInfo(
                title=title,
                app_name=app_name,
                process_name=process_name,
                pid=pid,
                window_handle=hwnd,
                bounds=bounds
            )
        
        except Exception as e:
            logger.error(f"Failed to get active window info: {e}")
            return None
    
    def get_selected_text(self) -> Optional[str]:
        """
        Get selected text by simulating Ctrl+C and reading clipboard.
        
        Returns:
            Selected text, or None if nothing selected or operation failed
        """
        try:
            import pyperclip
            import pyautogui
            
            # Save current clipboard
            original_clipboard = None
            try:
                original_clipboard = pyperclip.paste()
            except:
                pass
            
            # Simulate Ctrl+C to copy selection
            try:
                pyautogui.hotkey('ctrl', 'c')
                time.sleep(0.2)  # Wait for clipboard to be updated
            except Exception as e:
                logger.debug(f"Failed to simulate Ctrl+C: {e}")
                return None
            
            # Read clipboard
            selected_text = None
            try:
                selected_text = pyperclip.paste()
            except Exception as e:
                logger.error(f"Failed to read clipboard: {e}")
                return None
            
            # Restore original clipboard if different
            if original_clipboard and selected_text != original_clipboard:
                try:
                    pyperclip.copy(original_clipboard)
                except:
                    pass
            
            return selected_text if selected_text else None
        
        except ImportError as e:
            logger.warning(f"Required libraries not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get selected text: {e}")
            return None

    @staticmethod
    def _normalize_text_value(value) -> Optional[str]:
        if not isinstance(value, str):
            return None
        if not value.strip():
            return None
        return value

    def _read_control_text(self, control) -> Optional[str]:
        candidates = []

        if hasattr(control, "get_value"):
            try:
                value = self._normalize_text_value(control.get_value())
                if value:
                    candidates.append(value)
            except Exception:
                pass

        if hasattr(control, "window_text"):
            try:
                value = self._normalize_text_value(control.window_text())
                if value:
                    candidates.append(value)
            except Exception:
                pass

        if hasattr(control, "texts"):
            try:
                texts = control.texts()
                if texts:
                    joined = self._normalize_text_value("\n".join(str(text) for text in texts if str(text).strip()))
                    if joined:
                        candidates.append(joined)
            except Exception:
                pass

        if not candidates:
            return None

        return max(candidates, key=lambda text: len(text.strip()))

    @staticmethod
    def _is_editor_like_control(control) -> bool:
        element_info = getattr(control, "element_info", None)
        control_type = str(getattr(element_info, "control_type", "") or "").strip().lower()
        if control_type in {"edit", "document"}:
            return True

        class_name = str(getattr(element_info, "class_name", "") or "").strip().lower()
        if any(token in class_name for token in ("edit", "richedit", "document")):
            return True

        if hasattr(control, "friendly_class_name"):
            try:
                friendly = str(control.friendly_class_name() or "").strip().lower()
                if any(token in friendly for token in ("edit", "document")):
                    return True
            except Exception:
                pass

        return False

    def _find_editor_like_text(self, control) -> Optional[str]:
        candidates = []

        if self._is_editor_like_control(control):
            direct_text = self._read_control_text(control)
            if direct_text:
                candidates.append(direct_text)

        if hasattr(control, "descendants"):
            try:
                for descendant in control.descendants():
                    if not self._is_editor_like_control(descendant):
                        continue
                    text = self._read_control_text(descendant)
                    if text:
                        candidates.append(text)
            except Exception:
                pass

        if not candidates:
            return None

        return max(candidates, key=lambda text: len(text.strip()))
    
    def get_focused_element_text(self) -> Optional[str]:
        """
        Get text from focused element using UI Automation.
        
        Returns:
            Text from focused element, or None if unavailable
        """
        try:
            window = self._connect_to_active_window()
            if not window:
                return None
            
            # Try to get focused control
            try:
                focused = window.get_focus()
                if focused:
                    direct_text = self._read_control_text(focused)
                    if self._is_editor_like_control(focused) and direct_text:
                        return direct_text

                    editor_text = self._find_editor_like_text(focused)
                    if editor_text:
                        return editor_text

                    window_editor_text = self._find_editor_like_text(window)
                    if window_editor_text:
                        return window_editor_text

                    if direct_text:
                        return direct_text
            except Exception as e:
                logger.debug(f"Failed to get focused control text: {e}")
            
            return None
        
        except Exception as e:
            logger.error(f"Failed to get focused element text: {e}")
            return None
    
    def get_window_text(self) -> Optional[str]:
        """
        Get all text from active window using UI Automation.
        
        Walks the control tree to extract all visible text.
        
        Returns:
            Combined text from window, or None on failure
        """
        if not self.win32gui or not self.pywinauto:
            return None
        
        try:
            window = self._connect_to_active_window()
            if not window:
                return None

            editor_text = self._find_editor_like_text(window)
            if editor_text:
                return editor_text
            
            # Extract text from window hierarchy
            text_parts = []
            self._extract_window_text_recursive(window, text_parts, depth=0)
            
            return "\n".join(text_parts) if text_parts else None
        
        except Exception as e:
            logger.error(f"Failed to get window text: {e}")
            return None

    def _connect_to_active_window(self):
        """Connect pywinauto to the active window and return its wrapper."""
        if not self.win32gui or not self.pywinauto:
            return None

        hwnd = self.win32gui.GetForegroundWindow()
        if not hwnd:
            return None

        app = self.pywinauto(backend="uia")
        app.connect(handle=hwnd)

        window = app.window(handle=hwnd)
        if not window.exists():
            return None

        return window
    
    def _extract_window_text_recursive(self, control, text_parts: list, depth: int = 0, max_depth: int = 8) -> None:
        """
        Recursively extract text from control tree.
        
        Args:
            control: Control to extract from
            text_parts: List to accumulate text
            depth: Current recursion depth
            max_depth: Maximum recursion depth
        """
        if depth > max_depth:
            return
        
        try:
            # Try to get window text
            if hasattr(control, 'window_text'):
                text = control.window_text()
                if text and text.strip() and len(text) < 500:  # Limit text length
                    text_parts.append(text)
            
            # Try to get element value
            if hasattr(control, 'get_value'):
                try:
                    value = control.get_value()
                    if value and isinstance(value, str) and value.strip() and len(value) < 500:
                        text_parts.append(value)
                except:
                    pass
            
            # Recurse into children
            if hasattr(control, 'children'):
                try:
                    children = control.children()
                    for child in children[:15]:  # Limit children to prevent explosion
                        self._extract_window_text_recursive(child, text_parts, depth + 1, max_depth)
                except Exception:
                    pass
        
        except Exception as e:
            logger.debug(f"Error extracting text from control: {e}")
    
    def paste_text(self, text: str) -> bool:
        """
        Paste text into the active application via Ctrl+V.

        Args:
            text: The text to paste

        Returns:
            True if paste succeeded, False otherwise
        """
        try:
            import pyperclip
            import pyautogui

            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            return True
        except ImportError as e:
            logger.warning(f"Required libraries not available for paste: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to paste text: {e}")
            return False

    def check_permissions(self) -> bool:
        """
        Check if accessibility is available.

        Windows doesn't require special permissions like macOS.

        Returns:
            True if libraries are available
        """
        return bool(self.win32gui and self.pywinauto)
    
    def request_permissions(self) -> bool:
        """
        Request accessibility permissions.
        
        Windows doesn't have a special permission system like macOS.
        
        Returns:
            True (no special permissions needed)
        """
        if self.check_permissions():
            logger.info("Accessibility is ready on Windows")
            return True
        
        logger.warning("Required accessibility libraries not installed")
        logger.info("Install with: pip install pywinauto pywin32 psutil pyautogui pyperclip")
        return False
