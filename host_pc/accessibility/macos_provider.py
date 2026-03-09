"""
macOS accessibility provider using PyObjC and native APIs.

Provides text extraction from the active application using macOS
accessibility APIs (AXUIElement) and system clipboard.
"""

import logging
import subprocess
import time
from typing import Optional

from .base import AccessibilityProvider, WindowInfo, TextSource

logger = logging.getLogger(__name__)


class MacOSAccessibilityProvider(AccessibilityProvider):
    """
    macOS implementation of accessibility provider.
    
    Uses PyObjC framework to interact with:
    - NSWorkspace: Get active application
    - AXUIElement: Accessibility API for text extraction
    - Clipboard: For capturing selected text via Cmd+C
    """
    
    def __init__(self):
        """Initialize macOS accessibility provider."""
        self.nsworkspace = None
        self.ax_module = None
        self.objc_util = None
        self._init_frameworks()
    
    def _init_frameworks(self) -> None:
        """Initialize PyObjC frameworks."""
        try:
            import AppKit
            import objc
            from ApplicationServices import (
                AXIsProcessTrusted,
                AXUIElementCreateApplication,
                AXUIElementCopyAttributeValue,
            )

            self.nsworkspace = AppKit.NSWorkspace
            self.ax_create_app = AXUIElementCreateApplication
            self.ax_copy_attr = AXUIElementCopyAttributeValue
            self.ax_is_trusted = AXIsProcessTrusted
            self.objc_util = objc
            logger.info("macOS accessibility frameworks initialized")
        except ImportError as e:
            logger.warning(f"PyObjC frameworks not available: {e}")
            logger.info("Install with: pip install pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices")
    
    def get_active_window_info(self) -> Optional[WindowInfo]:
        """
        Get information about the active window using NSWorkspace.
        
        Returns:
            WindowInfo about active window, or None on failure
        """
        if not self.nsworkspace:
            return None

        try:
            # Get active application
            workspace = self.nsworkspace.sharedWorkspace()
            active_app = workspace.activeApplication()

            if not active_app:
                logger.warning("No active application found")
                return None

            app_name = active_app.get("NSApplicationName", "Unknown")
            bundle_id = active_app.get("NSApplicationBundleIdentifier", "")
            process_name = active_app.get("NSApplicationProcessIdentifier")
            pid = int(process_name) if process_name else 0

            # Get window title using accessibility API
            ax_app = self.ax_create_app(pid)
            if ax_app:
                err, title = self.ax_copy_attr(ax_app, "AXTitle", None)
                if err != 0 or not title:
                    title = app_name
            else:
                title = app_name
            
            return WindowInfo(
                title=str(title) if title else app_name,
                app_name=app_name,
                process_name=str(process_name),
                pid=pid,
                bundle_id=bundle_id,
                bounds={}
            )
        except Exception as e:
            logger.error(f"Failed to get active window info: {e}")
            return None
    
    def get_selected_text(self) -> Optional[str]:
        """
        Get selected text by simulating Cmd+C and reading clipboard.
        
        Returns:
            Selected text, or None if nothing selected or operation failed
        """
        try:
            import pyperclip
            
            # Save current clipboard
            original_clipboard = None
            try:
                original_clipboard = pyperclip.paste()
            except:
                pass
            
            # Simulate Cmd+C to copy selection
            try:
                subprocess.run(
                    ["osascript", "-e", "tell application \"System Events\" to keystroke \"c\" using command down"],
                    check=True,
                    capture_output=True,
                    timeout=2
                )
            except Exception as e:
                logger.debug(f"Failed to simulate Cmd+C: {e}")
                return None
            
            # Wait for clipboard to be updated
            time.sleep(0.1)
            
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
        
        except ImportError:
            logger.warning("pyperclip not available for clipboard operations")
            return None
        except Exception as e:
            logger.error(f"Failed to get selected text: {e}")
            return None
    
    def _get_selected_text_ax(self, element) -> Optional[str]:
        """
        Try to get selected text from an AX element via AXSelectedText.

        Args:
            element: AXUIElement to query

        Returns:
            Selected text string, or None
        """
        try:
            err, value = self.ax_copy_attr(element, "AXSelectedText", None)
            if err == 0 and value and str(value).strip():
                return str(value)
        except Exception:
            pass
        return None

    def get_focused_element_text(self) -> Optional[str]:
        """
        Get text from focused element using AXUIElement APIs.

        Prioritises selected text (AXSelectedText) over element value,
        so highlighted text in apps like Google Docs is captured correctly.

        Returns:
            Text from focused element, or None if unavailable
        """
        if not self.nsworkspace:
            return None

        try:
            # Get focused application
            workspace = self.nsworkspace.sharedWorkspace()
            active_app = workspace.activeApplication()

            if not active_app:
                return None

            pid = int(active_app.get("NSApplicationProcessIdentifier", 0))
            if not pid:
                return None

            # Get the accessibility element
            ax_app = self.ax_create_app(pid)
            if not ax_app:
                return None

            # Try getting focused element directly from app
            err, focused_elem = self.ax_copy_attr(ax_app, "AXFocusedUIElement", None)

            # If that fails, try via focused window first
            focused_win = None
            if err != 0 or not focused_elem:
                err, focused_win = self.ax_copy_attr(ax_app, "AXFocusedWindow", None)
                if err == 0 and focused_win:
                    err, focused_elem = self.ax_copy_attr(
                        focused_win, "AXFocusedUIElement", None
                    )

            # --- 1. Try AXSelectedText first (highlighted text) ---
            # Check focused element, then focused window, then app
            for elem in (focused_elem, focused_win, ax_app):
                if elem is not None:
                    selected = self._get_selected_text_ax(elem)
                    if selected:
                        return selected

            if err != 0 or not focused_elem:
                return None

            # --- 2. Try AXValue / AXTitle on the focused element ---
            for attr in ("AXValue", "AXTitle", "AXDescription"):
                err, value = self.ax_copy_attr(focused_elem, attr, None)
                if err == 0 and value:
                    text = str(value).strip()
                    # Skip generic short AX labels (e.g. "Document content")
                    if text and len(text) > 20:
                        return text

            return None

        except Exception as e:
            logger.error(f"Failed to get focused element text: {e}")
            return None
    
    def get_window_text(self) -> Optional[str]:
        """
        Get all text from active window by walking accessibility tree.

        Returns:
            Combined text from window, or None on failure
        """
        if not self.nsworkspace:
            return None

        try:
            workspace = self.nsworkspace.sharedWorkspace()
            active_app = workspace.activeApplication()

            if not active_app:
                return None

            pid = int(active_app.get("NSApplicationProcessIdentifier", 0))
            if not pid:
                return None

            ax_app = self.ax_create_app(pid)
            if not ax_app:
                return None

            text_parts = []

            # Try the focused window first (more targeted)
            err, focused_win = self.ax_copy_attr(ax_app, "AXFocusedWindow", None)
            if err == 0 and focused_win:
                self._extract_text_recursive(focused_win, text_parts, depth=0)

            # Fall back to walking from app level
            if not text_parts:
                self._extract_text_recursive(ax_app, text_parts, depth=0)

            return "\n".join(text_parts) if text_parts else None

        except Exception as e:
            logger.error(f"Failed to get window text: {e}")
            return None
    
    def _extract_text_recursive(self, element, text_parts: list, depth: int = 0, max_depth: int = 10) -> None:
        """
        Recursively extract text from accessibility element tree.

        Args:
            element: AXUIElement to extract from
            text_parts: List to accumulate text
            depth: Current recursion depth
            max_depth: Maximum recursion depth to prevent infinite loops
        """
        if depth > max_depth:
            return

        try:
            # Try to get value (text content)
            err, value = self.ax_copy_attr(element, "AXValue", None)
            if err == 0 and value:
                text = str(value).strip()
                if text:
                    text_parts.append(text)

            # Try to get title (only if no value, to avoid duplicates)
            else:
                err, title = self.ax_copy_attr(element, "AXTitle", None)
                if err == 0 and title:
                    text = str(title).strip()
                    if text:
                        text_parts.append(text)

            # Get children and recurse
            err, children = self.ax_copy_attr(element, "AXChildren", None)
            if err == 0 and children:
                try:
                    child_list = list(children)
                except (TypeError, ValueError):
                    child_list = []
                for child in child_list[:50]:
                    self._extract_text_recursive(child, text_parts, depth + 1, max_depth)

        except Exception as e:
            logger.debug(f"Error extracting text from element: {e}")
    
    def paste_text(self, text: str) -> bool:
        """
        Paste text into the active application by setting the clipboard
        and simulating Cmd+V.

        Args:
            text: The text to paste

        Returns:
            True if paste succeeded, False otherwise
        """
        try:
            import pyperclip

            pyperclip.copy(text)
            time.sleep(0.1)

            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke "v" using command down'],
                check=True,
                capture_output=True,
                timeout=2,
            )
            return True

        except ImportError:
            logger.warning("pyperclip not available for paste operation")
            return False
        except Exception as e:
            logger.error(f"Failed to paste text: {e}")
            return False

    def check_permissions(self) -> bool:
        """
        Check if app has accessibility permissions.
        
        Returns:
            True if AXIsProcessTrusted returns True
        """
        try:
            trusted = self.ax_is_trusted()
            return bool(trusted)
        except Exception as e:
            logger.error(f"Failed to check accessibility permissions: {e}")
            return False
    
    def request_permissions(self) -> bool:
        """
        Request accessibility permissions by opening System Settings.
        
        User must manually grant permissions by:
        1. System Settings > Privacy & Security > Accessibility
        2. Click the lock icon to make changes
        3. Add this application to the list
        
        Returns:
            False (user must manually grant permissions)
        """
        try:
            import subprocess
            
            logger.info("")
            logger.info("=" * 70)
            logger.info("ACCESSIBILITY PERMISSIONS REQUIRED")
            logger.info("=" * 70)
            logger.info("")
            logger.info("This application needs accessibility permissions to read text from")
            logger.info("other applications. Please follow these steps:")
            logger.info("")
            logger.info("1. System Settings will open (or open it manually)")
            logger.info("2. Go to: Privacy & Security > Accessibility")
            logger.info("3. Click the lock icon (🔒) at the bottom to make changes")
            logger.info("4. Enter your password if prompted")
            logger.info("5. Click the '+' button and select this application")
            logger.info("")
            logger.info("The application will need to be restarted after granting permissions.")
            logger.info("=" * 70)
            logger.info("")
            
            # Try multiple methods to open System Settings
            try:
                # Method 1: Direct URL scheme (works on Monterey+)
                subprocess.run(
                    ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                    check=True,
                    timeout=5
                )
                logger.info("✓ System Settings > Accessibility opened")
                return False
            except Exception as e1:
                logger.debug(f"URL scheme failed: {e1}")
            
            try:
                # Method 2: Open System Settings app directly
                subprocess.run(
                    ["open", "-a", "System Settings"],
                    check=True,
                    timeout=5
                )
                logger.info("✓ System Settings opened - navigate to Security & Privacy > Accessibility")
                return False
            except Exception as e2:
                logger.debug(f"System Settings app failed: {e2}")
            
            try:
                # Method 3: Open System Preferences (older macOS)
                subprocess.run(
                    ["open", "-a", "System Preferences"],
                    check=True,
                    timeout=5
                )
                logger.info("✓ System Preferences opened - navigate to Security > Accessibility")
                return False
            except Exception as e3:
                logger.debug(f"System Preferences failed: {e3}")
            
            logger.warning("")
            logger.warning("Could not automatically open System Settings")
            logger.warning("Please manually open System Settings and navigate to:")
            logger.warning("  Privacy & Security > Accessibility")
            logger.warning("Then add this application to the allowed list.")
            logger.warning("")
            return False
        
        except Exception as e:
            logger.error(f"Error requesting permissions: {e}")
            return False
