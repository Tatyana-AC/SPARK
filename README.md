# SPARK

SPARK is a desktop context-capture app with hardware integration. On the current branch it spans:

- Host app: PyQt desktop UI on macOS/Windows
- Pico Hub: CircuitPython device exposing custom Raw HID and USB CDC serial relay
- Jetson bridge: durable context storage plus session synthesis broker for the Pico UART path

The main app entrypoint is `spark_app_v2.py`, which remains the active runtime path.

## Quickstart

### macOS

#### One-click setup from a fresh clone

If you are starting from a blank folder on macOS, use the branch and launcher below:

```bash
git clone --branch sida https://github.com/Tatyana-AC/SPARK.git /Users/sidac/SPARK
cd /Users/sidac/SPARK
chmod +x setup_spark_macos.sh
./setup_spark_macos.sh
```

`setup_spark_macos.sh` is the preferred macOS bring-up path. On a fresh checkout it will:

- create the repo-local `.venv` automatically when missing
- install or repair `requirements.txt` inside that virtualenv
- verify macOS Accessibility permissions for the repo Python
- verify batch-mode SSH access to the Jetson
- deploy the Pico runtime to the mounted `CIRCUITPY` volume
- sync the Jetson bridge bundle over SSH
- start or restart the Jetson services
- run the Raw HID synthesis smoke test, with one automatic bridge-restart retry on transient response timeouts
- launch both `spark_app_v2.py` and `tools/monitoring/watch_full_stack.py` in Terminal

Important macOS setup notes:

- The repo default branch on GitHub is currently `main`, but the active branch used for the current macOS setup flow is `sida`, so clone that branch explicitly when you want this behavior.
- The first run may trigger macOS permission prompts. If Terminal or the repo Python asks for Accessibility or Input Monitoring, grant access, then rerun `./setup_spark_macos.sh`.
- If you launch `./setup_spark_macos.sh` from a third-party terminal app such as `Cmux`, grant Accessibility to that terminal app as well. Accessibility granted only to the default Terminal app does not carry over to a different terminal host process.
- If `CIRCUITPY` is mounted read-only, the script now stops before deployment and tells you to reconnect or reset the Pico so the volume remounts read-write. Rerun the same command after the board remounts.
- The script expects passwordless SSH to `sidac@192.168.55.1` by default. Override host, user, or remote path with flags when needed:

```bash
./setup_spark_macos.sh --jetson-host 192.168.55.1 --jetson-user sidac --jetson-remote-path /mnt/usb_drive
```

#### Manual setup

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

To launch the debug watcher separately on macOS:

```bash
.venv/bin/python tools/monitoring/watch_full_stack.py
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

- Windows setup expects the optional UI Automation dependencies (`pywinauto`, `pywin32`) from this root `requirements.txt`.

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
- `Ctrl+F1`: toggle the SPARK window

macOS defaults on this branch:

- `Cmd+Ctrl+C`: capture selected text
- `Cmd+Ctrl+R`: release text
- `Ctrl+F1`: toggle the SPARK window

If `F1` changes screen brightness instead of behaving like a standard function key, enable Apple's standard function-key mode:

- macOS Ventura / Sonoma / Sequoia: `System Settings` -> `Keyboard` -> turn on `Use F1, F2, etc. keys as standard function keys`
- If you prefer the media keys by default, you can keep that setting off and press `Fn+Ctrl+F1` when using the SPARK toggle hotkey

### Browser extraction behavior

- `spark_app_v2.py` polls every 125 ms and keeps the same fallback order:
  - browser extraction first for supported browser tabs
  - focused-element fallback
  - full-window text fallback
- macOS browsers: `host_pc/web_content.py` uses live-tab extraction for supported Safari/Chrome-family tabs and falls back to HTTP extraction for normal web pages when needed.
- Windows browsers: `host_pc/browser_windows.py` provides tab URL/title metadata, `host_pc/web_content_windows.py` attempts live UIA document extraction, and `host_pc/web_content.py` falls back to HTTP extraction for fetchable external pages when live extraction is weak or noisy.
- If browser text is not directly fetchable on Windows, the app still evaluates focused-element/full-window accessibility text, but only accepts those fallbacks after the browser-noise heuristics in `host_pc/web_content_windows.py` say they look like real page content.

The default toggle hotkey was moved away from `Alt+Space`-based bindings on Windows so it no longer trips the active window's system menu.

## Hardware-related dependencies

The current app expects these packages for hardware communication:

- `hidapi`
- `pyserial`

They are already listed in `requirements.txt`.

Important: install `hidapi`, not the separate `hid` package.

## Windows setup helper

Use `run_spark_setup_and_launch.ps1` for the current one-command Windows bring-up flow, or `run_spark_setup_and_launch.bat` when you want a double-clickable wrapper. Both scripts delegate to `setup_spark.ps1`.

On current `setup_spark.ps1`, the launcher now bootstraps the repo Python environment before bring-up:

- creates the repo `.venv` automatically when missing
- installs or repairs `requirements.txt` into that virtualenv when the recorded dependency fingerprint is stale or core imports fail
- validates `SSHFS-Win`, `ssh`, and batch-mode SSH auth before device detection or deployment starts

That means a fresh Windows host no longer needs a pre-created `.venv` before using the launcher, but it still needs:

- a base Python 3 install available through `py` or `python`
- `SSHFS-Win` installed at `C:\Program Files\SSHFS-Win\bin\sshfs-win.exe`
- working passwordless SSH access to the Jetson for the configured user/host

That flow brings up the normal Windows debugging session by launching:

- `spark_app_v2.py`
- `tools/monitoring/watch_full_stack.py`

The watcher is monitor-only. It does not start additional app instances.

## Blank-folder recovery

If `/Users/sidac/SPARK` was deleted or emptied, the fastest way back to a working macOS setup is:

```bash
git clone --branch sida https://github.com/Tatyana-AC/SPARK.git /Users/sidac/SPARK
cd /Users/sidac/SPARK
./setup_spark_macos.sh
```

Expected outcome:

- the repo-local virtualenv is recreated
- the Pico runtime is redeployed when `CIRCUITPY` is writable
- the Jetson bridge bundle is resynced
- Jetson services are verified
- `spark_app_v2.py` and `tools/monitoring/watch_full_stack.py` are relaunched

If recovery stops on a Pico message about a read-only `CIRCUITPY` mount, reconnect or reset the Pico first, confirm it remounts read-write in Finder or `diskutil info /Volumes/CIRCUITPY`, then rerun `./setup_spark_macos.sh`.

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
- `docs/specs/2026-04-15-jetson-db-viewer-design.md`: design notes for the Jetson DB snapshot viewer
- `docs/specs/2026-04-16-windows-browser-extraction-design.md`: design notes for Windows browser extraction and heuristics
- `docs/specs/2026-04-16-pytest-cleanup-and-background-design.md`: design notes for the current UI test harness cleanup
- `jetson/`: deployable Jetson bridge bundle intended to be copied into the Jetson-side `demo/pico_bridge` folder

## Notes

- `spark_app_v2.py` is the active app path.
- `spark_app_v2.py` now refuses duplicate launches through `host_pc/single_instance.py`; on Windows, the parent/child launcher pair from `.venv\Scripts\python.exe` still counts as one app start.
- `lcd_screen_ui/` is a standalone React/Vite UI kit for the 320x240 LCD workflow screens.
- The current Pico firmware target is CircuitPython.
- `tools/monitoring/watch_full_stack.py` is the passive full-stack watcher for host, Pico, and Jetson logs.
- `tools/monitoring/pico_monitor.py` is the direct Pico HID/runtime monitor.
- Current auxiliary input wiring: EC11 encoder A/B/button/common -> GP10/GP11/GP9/GND, and three-position slide switch positions 1/2/3/common -> GP6/GP7/GP8/GND.
- `python tools/pico/deploy_to_pico.py` is the cross-platform helper to push the Pico firmware and `adafruit_hid` onto a mounted `CIRCUITPY` board.
- Deploy now exact-syncs the default Pico runtime and removes stale non-preserved files from `CIRCUITPY`; use `--dry-run` to inspect planned deletions first.
- `Release Text` uploads text to the Pico, waits for an acknowledgment, and updates the local `RELEASE OUTPUT` panel. It does not type text back into the currently focused external app.
- `Synthesis` sends `{"command":"synthesize_session","window_minutes":30}` to the Pico over Raw HID. The Pico forwards that request to Jetson over UART, and the host streams the Jetson response into `RELEASE OUTPUT`.
- `View Jetson DB` opens a read-only snapshot viewer for `Z:\demo\pico_bridge\jetson_spark.db`, including table paging and retry-safe refresh behavior.
- Browser polling now uses `host_pc/web_content.py` plus `host_pc/web_content_windows.py` to reject noisy browser chrome, prefer real live-tab text, and fall back to HTTP article extraction when appropriate.
- Jetson now owns session synthesis prompt wrapping. The active app is the anchor, and related context from the fixed last 30 minutes can be included when it matches the active topic.
- `spark_app_v2.py` no longer uses a host-local SQLite database in the active runtime. Context persistence now lives on Jetson, while host UI position is stored through `QSettings`.
- The `jetson/` folder in this repo is meant to be copy-pasted into the Jetson bridge directory. The active Jetson-side deployment target is `Z:\demo\pico_bridge`.
- `Custom Context` remains available in the SPARK panel for transport debugging without depending on live accessibility extraction. The legacy `summarize` command remains available in code and tests, but it is no longer exposed as a user-facing action.
- `tests/conftest.py` forces Qt into `offscreen` mode during pytest collection so the UI test suite can run headlessly on Windows.
- The panel header `✕` now fully quits the app. Use the tray menu or `Ctrl+F1` when you want to hide/show the panel without exiting.
- During manual debugging, make sure older `spark_app_v2.py` processes are closed before launching another copy. Duplicate host app processes can contend for the Pico HID session and surface as `BUSY`, `read error`, or device-response timeouts.
- If the Pico still enumerates on USB but synthesis or other Jetson-backed requests hit a Raw HID timeout, do a physical Pico reset before trying software recovery steps. A soft reload may help, but it should not be the first-line recovery path.
- On March 28, 2026, the real physical Host HID/CDC -> Pico -> Jetson `/dev/ttyTHS0` path was verified end-to-end with live streamed responses from the Jetson llama.cpp server.
- The top-level `spark.db` file can still exist from older runs, but it is not part of the active `spark_app_v2.py` runtime anymore.
