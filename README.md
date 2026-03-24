# SPARK

SPARK is a desktop context-capture app with hardware integration. On the current branch it spans:

- Host app: PyQt desktop UI on macOS/Windows
- Pico Hub: CircuitPython device exposing custom Raw HID, standard keyboard HID, and USB CDC serial relay
- Jetson receiver: session-aware serial ingest and storage

The main app entrypoint is `spark_app_v2.py`.

## Quickstart

### macOS

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Grant Accessibility permissions:

- Open System Settings → Privacy & Security → Accessibility
- Add the Python executable from your virtual environment if needed
- See `ACCESSIBILITY_PERMISSIONS.md` for the detailed walkthrough

4. Run the app:

```bash
python spark_app_v2.py
```

### Windows

1. Create and activate a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Run the app:

```powershell
python .\spark_app_v2.py
```

4. Current Windows hotkeys on this branch:

- `Win+Alt+C`: capture selected text
- `Win+Alt+V`: release text
- `Win+Alt+Space`: toggle the SPARK window

Avoid `Alt+Space`-based shortcuts on Windows. By default, `Alt+Space` opens the active window's system/context menu, so `Win+Alt+Space` can still trigger that visible menu behavior. `Win+Alt+Space` may also conflict with PowerToys Command Palette if you use it.

If you explicitly want to suppress that behavior on your machine, a simple AutoHotkey workaround is:

```ahk
#!Space::return
```

## Hardware-related dependencies

The current app expects these packages for hardware communication:

- `hidapi`
- `pyserial`

They are already listed in `requirements.txt`.

Important: install `hidapi`, not the separate `hid` package.

## Key docs

- `ENGINEERING_SPEC.md`: current architecture and protocol reference
- `REPO_STRUCTURE.md`: codebase map and ownership notes
- `pico/README.md`: Pico firmware notes and bring-up
- `ACCESSIBILITY_PERMISSIONS.md`: macOS accessibility setup
- `documentation_reference.md`: older host-app notes, useful but partially outdated

## Notes

- `spark_app_v2.py` is the active app path.
- `spark_app.py` is an older UI path and should be treated as secondary.
- The current Pico firmware target is CircuitPython.
- `pico/main.py` is a readable behavioral reference for the Pico role, not the literal deployed `boot.py` / `code.py` pair.
- The top-level `spark.db` file is local runtime state, not project source.
