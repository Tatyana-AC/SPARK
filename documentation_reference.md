# SPARK — Documentation Reference

## Core Data Flow

```
Poll tick (every 2s)
  |
  +-- AccessibilityManager --> WindowInfo (app name, title, pid)
  +-- get_browser_tab()    --> BrowserTabInfo (tab title, URL)  [Safari/Chrome only]
  +-- get_focused_element_text() or get_window_text() --> extracted text
  |
  +-- tracker.update(info, text, source, tab)
       |
       +-- Same context_key? --> refresh text in place
       +-- Different context_key? --> save old to DB, push to history, increment counter
                                       +-- Counter hits 50? --> distill_and_flush()
```

---

## Where to Edit What

| You want to... | Edit this file | Look at... |
|---|---|---|
| Change poll speed | `spark_app.py` line 73 | `POLL_INTERVAL = 2000` |
| Change what text gets extracted | `host_pc/accessibility/macos_provider.py` | `get_focused_element_text()` (line 173), `get_window_text()` (line 241) |
| Add another browser (Firefox, Arc, etc) | `host_pc/browser.py` | `BROWSER_APPS` set + add AppleScript in `get_browser_tab()` |
| Change what counts as a "unique switch" | `host_pc/accessibility/base.py` lines 65-74 | `context_key` property on `WindowContextSnapshot` |
| Change flush threshold (currently 50) | `host_pc/accessibility/tracker.py` line 43 | `FLUSH_THRESHOLD = 50` |
| Add real LLM logic on flush | `host_pc/accessibility/tracker.py` line 123 | `distill_and_flush()` — currently just logs |
| Change what gets saved to the DB | `host_pc/db.py` | `save_snapshot()` (line 62), schema in `_create_tables()` (line 29) |
| Change how history shows in the UI | `spark_app.py` line 392 | `_refresh_history_ui()` |
| Change what shows in LIVE CONTEXT | `spark_app.py` line 352 | `_on_poll_tick()` |
| Build an LLM prompt from context | `host_pc/context.py` | `Context.to_dict()` — serialize for prompt building |
| Get context programmatically | `host_pc/accessibility/tracker.py` line 140 | `tracker.get_current_context()` returns a `Context` object |
| Query past window history | `host_pc/db.py` | `db.get_recent(n)` or `db.search("keyword")` |
| Change capture/release behavior | `spark_app.py` line 415 | `_do_capture()` and `_do_release()` |
| Change hotkeys | `host_pc/hotkeys.py` | `GlobalHotkeyManager` |

Windows hotkey note:
- Current Windows defaults are `Win+Alt+C` for capture and `Win+Alt+V` for release.
- Current Windows toggle default is `Win+Alt+Space`.
- Avoid `Alt+Space`-based global hotkeys. Windows uses `Alt+Space` to open the active window's context/system menu, so `Win+Alt+Space` is a poor default for toggle behavior.
- If a local machine still needs `Win+Alt+Space`, the user-verified AutoHotkey workaround is:

```ahk
#!Space::return
```

---

## File-by-File Summary

| File | Purpose |
|---|---|
| `spark_app.py` | Main GUI — poll loop, UI cards, hotkey wiring, capture/release |
| `host_pc/accessibility/base.py` | Data models: `WindowInfo`, `TextSource`, `WindowContextSnapshot`, `context_key` |
| `host_pc/accessibility/manager.py` | Cross-platform wrapper — detects OS, delegates to provider |
| `host_pc/accessibility/macos_provider.py` | macOS AX APIs — text extraction, clipboard, paste |
| `host_pc/accessibility/tracker.py` | Window history (current + 2 previous), unique switch counter, `distill_and_flush()` |
| `host_pc/browser.py` | AppleScript queries for Safari/Chrome active tab + URL |
| `host_pc/context.py` | `Context` class — clean LLM-ready object with `context_key` and `to_dict()` |
| `host_pc/db.py` | SQLite layer — `save_snapshot()`, `get_recent()`, `search()`, auto-migration |
| `host_pc/hotkeys.py` | Global hotkey listener with platform-specific defaults (macOS: Cmd+Ctrl, Windows: Win+Alt) |

---

## Key Data Models

### WindowInfo (`host_pc/accessibility/base.py`)

```python
@dataclass
class WindowInfo:
    title: str          # Window title
    app_name: str       # e.g. "Safari", "VS Code"
    process_name: str   # Process identifier
    pid: int            # Process ID
    bounds: Optional[Dict[str, int]] = None
```

### WindowContextSnapshot (`host_pc/accessibility/base.py`)

```python
@dataclass
class WindowContextSnapshot:
    window_info: WindowInfo
    text: str                        # Full extracted text content
    source: TextSource               # FOCUSED_ELEMENT or FULL_WINDOW
    tab_title: Optional[str] = None  # Browser tab title (None for non-browsers)
    url: Optional[str] = None        # Browser tab URL (None for non-browsers)
    timestamp: float                 # Unix timestamp

    context_key: str  # property — "app_name|url" for browsers, "app_name|title" for others
```

### BrowserTabInfo (`host_pc/browser.py`)

```python
@dataclass
class BrowserTabInfo:
    tab_title: str  # Active tab's title
    url: str        # Active tab's URL
```

### Context (`host_pc/context.py`)

```python
@dataclass
class Context:
    app_name: str
    window_title: str
    tab_title: Optional[str]   # None for non-browsers
    url: Optional[str]         # None for non-browsers
    text: str                  # Extracted text content
    source: str                # "focused_element" / "full_window"
    timestamp: float
    pid: int

    context_key: str   # property — unique identity for switch detection
    to_dict() -> dict  # Serialize for LLM prompt building
```

---

## Database Schema (`spark.db`)

Table: `window_snapshots`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key, autoincrement |
| app_name | TEXT | e.g. "Safari", "VS Code" |
| window_title | TEXT | Window title at time of capture |
| process_name | TEXT | Process name |
| pid | INTEGER | Process ID |
| text | TEXT | Full extracted text content |
| source | TEXT | TextSource value (focused_element, full_window) |
| tab_title | TEXT | Browser tab title (NULL for non-browsers) |
| url | TEXT | Browser tab URL (NULL for non-browsers) |
| timestamp | REAL | Unix timestamp |

### Querying the Database

```python
from host_pc.db import SparkDB

db = SparkDB("spark.db")

# Get the 20 most recent snapshots
for snap in db.get_recent(20):
    print(snap.window_info.app_name, snap.url, len(snap.text))

# Search by keyword in text, title, or URL
for snap in db.search("github"):
    print(snap.window_info.app_name, snap.url)

db.close()
```

Or from the terminal:

```bash
sqlite3 spark.db "SELECT app_name, window_title, url, length(text), datetime(timestamp, 'unixepoch', 'localtime') FROM window_snapshots ORDER BY timestamp DESC;"
```

---

## LLM Integration Extension Point

When ready to wire in a local LLM, the main touchpoint is `distill_and_flush()` in `host_pc/accessibility/tracker.py` (line 123). At that point you can:

1. Call `self._db.get_recent(50)` to grab the last 50 snapshots
2. Build `Context` objects via `tracker.get_current_context()`
3. Use `Context.to_dict()` to serialize for prompt construction
4. Send to your LLM

```python
def distill_and_flush(self) -> None:
    recent = self._db.get_recent(self.FLUSH_THRESHOLD)
    contexts = [snap_to_context(s) for s in recent]
    # Build prompt, send to LLM, etc.
    self._unique_switch_count = 0
```

---

## Unique Switch Logic

A switch is **unique** when the `context_key` changes:

- **Browsers**: `"Safari|https://example.com"` — switching tabs counts as unique even if the pid/window didn't change
- **Non-browsers**: `"VS Code|main.py — SPARK"` — switching windows/files counts
- **Same tab / same window re-focus**: NOT unique (same key, counter doesn't increment)

The counter resets to 0 after `distill_and_flush()` fires at 50 unique switches.
