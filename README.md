# SPARK

SPARK is a desktop context-capture app with hardware integration. On the current branch it spans:

- Host app: PyQt desktop UI on macOS/Windows
- Pico Hub: CircuitPython device exposing custom Raw HID and USB CDC serial relay
- Jetson bridge: durable context storage plus summarize broker for the Pico UART path

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

## Windows setup helper

`setup_spark.ps1` now brings up the normal Windows debugging session by launching:

- `spark_app_v2.py`
- `watch_full_stack.py`

The watcher is monitor-only. It does not start additional app instances.

## Key docs

- `ENGINEERING_SPEC.md`: current architecture and protocol reference
- `REPO_STRUCTURE.md`: codebase map and ownership notes
- `diagram.md`: high-level three-node system diagram for the current architecture
- `docs/BRANCH_HANDOFF_2026-03-24.md`: summary of branch changes since Tatyana's last handoff
- `docs/BRANCH_HANDOFF_2026-03-29.md`: follow-up handoff covering the LCD UI kit, browser extraction, and smoke-test additions
- `docs/pico/README.md`: Pico firmware notes and bring-up
- `docs/pico/HARDWARE_SMOKE_TEST.md`: post-deploy Pico verification checklist
- `ACCESSIBILITY_PERMISSIONS.md`: macOS accessibility setup
- `documentation_reference.md`: current developer lookup for host behavior and extension points
- `jetson/`: deployable Jetson bridge bundle intended to be copied into the Jetson-side `demo/pico_bridge` folder

## Notes

- `spark_app_v2.py` is the active app path.
- `spark_app.py` is an older UI path and should be treated as secondary.
- `lcd_screen_ui/` is a standalone React/Vite UI kit for the 320x240 LCD workflow screens.
- The current Pico firmware target is CircuitPython.
- `pico_reference/main.py` is a readable behavioral reference for the Pico role, not the literal deployed `boot.py` / `code.py` pair.
- Current auxiliary input wiring: EC11 encoder A/B/button/common -> GP10/GP11/GP9/GND, and three-position slide switch positions 1/2/3/common -> GP6/GP7/GP8/GND.
- `python tools/pico/deploy_to_pico.py` is the cross-platform helper to push the Pico firmware and `adafruit_hid` onto a mounted `CIRCUITPY` board.
- Deploy now exact-syncs the default Pico runtime and removes stale non-preserved files from `CIRCUITPY`; use `--dry-run` to inspect planned deletions first.
- `Release Text` uploads text to the Pico, waits for an acknowledgment, and updates the local `RELEASE OUTPUT` panel. It does not type text back into the currently focused external app.
- `Summarize Window` now sends a structured active-window request to the Pico over Raw HID. The Pico forwards that request to Jetson over UART, and the host streams the Jetson response into `RELEASE OUTPUT`.
- Browser polling can now use `host_pc/web_content.py` to extract visible text from supported Chrome/Safari tabs when the accessibility tree is sparse.
- Jetson now owns the summarize prompt wrapping and system-prompt behavior for `Summarize Window`.
- `spark_app_v2.py` no longer uses a host-local SQLite database in the active runtime. Context persistence now lives on Jetson, while host UI position is stored through `QSettings`.
- The `jetson/` folder in this repo is meant to be copy-pasted into the Jetson bridge directory. The active Jetson-side deployment target is `Z:\demo\pico_bridge`.
- `Test Context` and `Custom Context` are visible in the SPARK panel for summarize-loop debugging without depending on live accessibility extraction.
- The panel header `✕` now fully quits the app. Use the tray menu or `Win+Alt+Space` when you want to hide/show the panel without exiting.
- During manual debugging, make sure older `spark_app_v2.py` processes are closed before launching another copy. Duplicate host app processes can contend for the Pico HID session and surface as `BUSY`, `read error`, or device-response timeouts.
- If the Pico still enumerates on USB but `Test Context` or other summarize requests hit a Raw HID timeout, do a physical Pico reset before trying software recovery steps. A soft reload may help, but it should not be the first-line recovery path.
- On March 28, 2026, the real physical Host HID/CDC -> Pico -> Jetson `/dev/ttyTHS0` path was verified end-to-end with live summarize responses from the Jetson llama.cpp server.
- The top-level `spark.db` file can still exist from older runs, but it is not part of the active `spark_app_v2.py` runtime anymore.
