"""
Cross-platform accessibility module for reading text from applications.

This module provides a unified interface for extracting text from the active
application on macOS, Windows, and Linux. It automatically detects the platform
and uses the appropriate accessibility APIs.

## Installation

Install base dependencies:
```bash
pip install pyautogui pyperclip
```

### macOS
```bash
pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz
```

### Windows
```bash
pip install pywinauto pywin32 psutil
```

## Quick Start

```python
from host_pc.accessibility import AccessibilityManager

# Create manager (auto-detects platform)
manager = AccessibilityManager()

# Check if ready
if not manager.is_available():
    print("Accessibility not available")
    exit(1)

# Check permissions (especially important on macOS)
if not manager.check_permissions():
    print("Need to grant permissions")
    manager.request_permissions()
    exit(1)

# Get text from active app
context = manager.get_context(method='auto')
if context:
    print(f"App: {context.window_info.app_name}")
    print(f"Source: {context.source.value}")
    print(f"Text: {context.text}")
```

## Usage Methods

**Auto mode** (try selected → focused → window):
```python
context = manager.get_context(method='auto')
```

**Selected text only**:
```python
text = manager.get_selected_text()
```

**Focused element only**:
```python
text = manager.get_focused_element_text()
```

**All window text**:
```python
text = manager.get_window_text()
```

**Get active app info**:
```python
app_name = manager.get_active_app()
window_info = manager.get_active_window_info()
```

## Error Handling

All methods return None on failure:

```python
text = manager.get_selected_text()
if text is None:
    print("Could not extract text")
else:
    print(f"Got {len(text)} characters")
```

## Platform-Specific Notes

### macOS
- Requires accessibility permissions (Settings > Security & Privacy > Accessibility)
- Uses NSWorkspace and AXUIElement APIs
- Simulates Cmd+C to capture selected text
- Can extract text from Cocoa applications

### Windows
- No special permissions required
- Uses UI Automation and Win32 APIs
- Simulates Ctrl+C to capture selected text
- Can extract text from most Windows applications

## Logging

Enable debug logging to see what's happening:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

manager = AccessibilityManager()
context = manager.get_context()
```
"""

from .manager import AccessibilityManager
from .base import WindowInfo, TextContext, TextSource, AccessibilityProvider, WindowContextSnapshot
from .tracker import WindowContextTracker

__all__ = [
    'AccessibilityManager',
    'WindowInfo',
    'TextContext',
    'TextSource',
    'AccessibilityProvider',
    'WindowContextSnapshot',
    'WindowContextTracker',
]

__version__ = "1.0.0"
