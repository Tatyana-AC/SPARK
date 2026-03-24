# SPARK Repo Structure Notes

## What This Repo Is

SPARK is a Python desktop assistant focused on context capture. The app watches the active window, extracts selected or visible text through platform accessibility APIs, enriches browser context when possible, stores recent snapshots in SQLite, and can paste processed text back into the focused app.

At a high level, the repo is a small desktop application with one main package (`host_pc`) and two root-level Qt entrypoints.

## Top-Level Layout

```text
SPARK/
|- spark_app_v2.py                   # Current floating panel UI
|- spark_app.py                      # Older full-window UI
|- host_pc/                          # Core runtime package
|  |- accessibility/                 # Cross-platform accessibility layer
|  |- browser.py                     # Browser tab/title lookup
|  |- context.py                     # LLM-friendly context model
|  |- db.py                          # SQLite persistence
|  `- hotkeys.py                     # Global hotkey bridge
|- documentation_reference.md        # Best existing architecture reference
|- diagram.md                        # Mermaid system diagram
|- ACCESSIBILITY_PERMISSIONS.md      # macOS setup guide
|- setup_accessibility_macos.py      # Interactive macOS permissions helper
|- requirements.txt                  # Runtime dependencies
|- spark.db                          # Local runtime data, ignored in git
|- spark_desktop.egg-info/           # Generated packaging metadata
|- .venv/                            # Local virtual environment
`- __pycache__/                      # Local Python cache
```

## Core Runtime Structure

### 1. UI Layer

- `spark_app_v2.py`
  - Main panel-style application.
  - Builds the floating frameless UI, tray icon, polling loop, history cards, capture/release actions, and a privacy guard.
  - This is the active GUI entrypoint according to `spark_desktop.egg-info/entry_points.txt`.
- `spark_app.py`
  - Older `QMainWindow` implementation of the same capture/process/release idea.
  - Still contains a full standalone UI instead of a thin compatibility shim.

### 2. Accessibility Layer

Everything under `host_pc/accessibility/` is the abstraction boundary between SPARK and OS-specific APIs.

- `base.py`
  - Shared dataclasses and interfaces:
    - `WindowInfo`
    - `TextContext`
    - `WindowContextSnapshot`
    - `TextSource`
    - `AccessibilityProvider`
- `manager.py`
  - Chooses the provider based on `sys.platform`.
  - Exposes unified methods like:
    - `get_context()`
    - `get_active_window_info()`
    - `get_selected_text()`
    - `get_focused_element_text()`
    - `get_window_text()`
    - `paste_text()`
- `macos_provider.py`
  - Uses PyObjC/ApplicationServices accessibility APIs.
  - Handles active app lookup, focused element text, window-wide text extraction, clipboard-based capture, paste, and permission checks.
- `windows_provider.py`
  - Uses Win32/UI Automation style integrations.
  - Handles active window detection, clipboard capture, focused/window text extraction, paste, and capability checks.
- `tracker.py`
  - Maintains current context plus the previous two window snapshots.
  - Persists snapshots on context change.
  - Prunes old database rows after the configured threshold.

### 3. Context Enrichment

- `browser.py`
  - Adds browser-aware metadata.
  - Supports Safari and Chromium-family names through AppleScript calls.
  - Returns `BrowserTabInfo` with tab title and URL when available.
- `context.py`
  - Defines a clean `Context` object for LLM or downstream prompt construction.
  - Mirrors the live snapshot data in a serialization-friendly form.

### 4. Persistence

- `db.py`
  - Owns the SQLite schema and all DB access.
  - Creates:
    - `window_snapshots`
    - `preferences`
  - Supports:
    - snapshot insert
    - recent-history queries
    - text/title/URL search
    - simple preference storage
    - oldest-row pruning

## How The App Fits Together

The runtime flow is:

1. The Qt app starts in `spark_app_v2.py`.
2. It creates:
   - `AccessibilityManager`
   - `GlobalHotkeyManager`
   - `SparkDB`
   - `WindowContextTracker`
3. Polling asks the accessibility manager for the active window.
4. If the active app is a supported browser, `browser.py` adds tab metadata.
5. The app tries text extraction in this order:
   - focused element
   - full window
6. `tracker.py` updates live/previous context and persists snapshots.
7. `db.py` stores history in `spark.db`.
8. Capture/release actions use clipboard + simulated paste to round-trip text back into the host application.

## Source Of Truth By Concern

- Best current architecture note: `documentation_reference.md`
- Visual system diagram: `diagram.md`
- Live desktop panel behavior: `spark_app_v2.py`
- Legacy UI behavior: `spark_app.py`
- Platform abstraction: `host_pc/accessibility/manager.py`
- OS-specific implementation details:
  - `host_pc/accessibility/macos_provider.py`
  - `host_pc/accessibility/windows_provider.py`
- History and retention logic: `host_pc/accessibility/tracker.py`
- DB schema and query surface: `host_pc/db.py`
- Hotkeys: `host_pc/hotkeys.py`

## Repo Characteristics

- Small codebase: most logic is concentrated in a handful of Python files.
- Thin package structure: `host_pc` is the only real module hierarchy.
- Root-heavy app design: the two largest application files live at repo root instead of under a package.
- Minimal formal project scaffolding in the tracked files:
  - no tests
  - no CI config
  - no tracked `pyproject.toml` or `setup.py`
- Generated metadata exists in `spark_desktop.egg-info/`, which means packaging happened outside the currently tracked source manifest.

## Important Observations

- `README.md` is currently just a title, so most usable documentation lives elsewhere.
- `documentation_reference.md` is the most practical onboarding document in the repo today.
- `spark.db` is intentionally ignored and should be treated as local runtime state, not source.
- Both app entrypoints still contain a hard-coded macOS `sys.path.insert(...)` to a developer machine path. That is a portability smell and a sign the repo still has local-dev assumptions baked in.
- `spark_desktop.egg-info/PKG-INFO` describes `spark_app.py` as forwarding to v2, but the tracked `spark_app.py` still contains a full older implementation. That suggests the generated egg-info may be stale relative to the checked-in source.

## Practical Mental Model

If you need to understand SPARK quickly, think of it as:

- a PyQt desktop shell at the top,
- a cross-platform accessibility adapter in the middle,
- a small SQLite memory layer underneath,
- and a browser/LLM-friendly context layer beside it.

Most future work will likely fall into one of these buckets:

- UI and interaction changes in `spark_app_v2.py`
- capture correctness in `host_pc/accessibility/`
- retention/search behavior in `host_pc/db.py` and `host_pc/accessibility/tracker.py`
- smarter downstream reasoning or prompt-building in `host_pc/context.py`
