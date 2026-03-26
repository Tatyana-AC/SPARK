# SPARK

SPARK is a desktop context-capture app with hardware integration. On the current branch it spans:

- Host app: PyQt desktop UI on macOS/Windows
- Pico Hub: CircuitPython device exposing custom Raw HID and USB CDC serial relay
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

Or run it without activating the shell first:

```bash
.venv/bin/python spark_app_v2.py
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

Or run it without activating the shell first:

```powershell
.\.venv\Scripts\python.exe .\spark_app_v2.py
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
- `diagram.md`: high-level three-node system diagram for the current architecture
- `docs/BRANCH_HANDOFF_2026-03-24.md`: summary of branch changes since Tatyana's last handoff
- `pico/README.md`: Pico firmware notes and bring-up
- `pico/HARDWARE_SMOKE_TEST.md`: post-deploy Pico verification checklist
- `ACCESSIBILITY_PERMISSIONS.md`: macOS accessibility setup
- `documentation_reference.md`: current developer lookup for host behavior and extension points

## Notes

- `spark_app_v2.py` is the active app path.
- `spark_app.py` is an older UI path and should be treated as secondary.
- The current Pico firmware target is CircuitPython.
- `pico/main.py` is a readable behavioral reference for the Pico role, not the literal deployed `boot.py` / `code.py` pair.
- `python pico/deploy_to_pico.py` is the cross-platform helper to push the Pico firmware and `adafruit_hid` onto a mounted `CIRCUITPY` board.
- `Release Text` uploads text to the Pico, waits for an acknowledgment, and updates the local `RELEASE OUTPUT` panel. It does not type text back into the currently focused external app.
- `Summarize Window` now sends a structured active-window request to the Pico over Raw HID. The Pico forwards that request to Jetson over UART, and the host streams the Jetson response into `RELEASE OUTPUT`.
- Jetson now owns the summarize prompt wrapping and system-prompt behavior for `Summarize Window`.
- `Test Context` and `Custom Context` are visible in the SPARK panel for summarize-loop debugging without depending on live accessibility extraction.
- During manual debugging, make sure older `spark_app_v2.py` processes are closed before launching another copy. Duplicate host app processes can contend for the Pico HID session and surface as `BUSY`, `read error`, or device-response timeouts.
- If the Pico still enumerates on USB but `Test Context` or other summarize requests hit a Raw HID timeout, do a physical Pico reset before trying software recovery steps. A soft reload may help, but it should not be the first-line recovery path.
- The top-level `spark.db` file is local runtime state, not project source.
