# SPARK Branch Handoff — 2026-03-29

Branch: `dev/integrate-spark-components`
Branched from: `main` (after merge commit `47fe1ec`)

This document covers everything added or changed on this branch since the last
handoff (`docs/BRANCH_HANDOFF_2026-03-24.md`).

---

## What Changed

### 1. LCD Screen UI — new React kit (`lcd_screen_ui/`)

A complete React + Vite + TypeScript UI kit was added for the 2.4" ILI9341
320×240 LCD display. It is a Figma export, reworked for the SPARK hardware target.

**Key files:**

| File | Purpose |
|---|---|
| `lcd_screen_ui/src/app/App.tsx` | State machine: idle → confirmation → processing → success |
| `lcd_screen_ui/src/app/components/IdleScreen.tsx` | 2×2 action grid |
| `lcd_screen_ui/src/app/components/ConfirmationScreen.tsx` | Confirm / cancel |
| `lcd_screen_ui/src/app/components/ProcessingScreen.tsx` | Spinner state |
| `lcd_screen_ui/src/app/components/SuccessScreen.tsx` | Success + auto-return |
| `lcd_screen_ui/src/styles/theme.css` | CSS custom properties |
| `lcd_screen_ui/README.md` | Hardware specs, layout rules, dev instructions |

**IdleScreen design:**
- 2×2 grid of action buttons (SYNTHESIS / REFORMAT / SEARCH / RESPOND)
- Each cell (148 × 96 px) contains: 40×40 thumbnail → 32px Lucide icon → 14px label
- Lucide icons: `Brain`, `Wand2`, `Search`, `MessageSquareReply` at stroke-width 2.5
- Corner bracket decorations: four 8×8px L-shapes in `#7aa2f7` at 60% opacity
- Hover: `#2f3449` / Active: `#3d4263` / Idle: `#24283b`
- Thumbnail `src` values use `placehold.co` — swap for real PNGs before hardware deploy

**To run locally:**
```bash
cd lcd_screen_ui && npm install && npm run dev
# Chrome DevTools → custom device 320×240 DPR=1 for pixel-accurate preview
```

**Constraints enforced:**
- All screens are exactly `w-[320px] h-[240px]`
- Status bar: 24 px fixed, content area: 216 px
- No Tailwind classes outside the CDN base; custom styles use inline `style` or `theme.css`

---

### 2. Pico LCD smoke test — new file (`pico/lcd_smoke_test.py`)

A standalone CircuitPython script for validating the physical ILI9341 + buttons
before integrating with the full firmware.

**Wiring used:**

| Signal | GPIO |
|---|---|
| DIN (MOSI) | GP19 |
| CLK (SCK) | GP18 |
| CS | GP17 |
| DC | GP16 |
| RST | GP20 |
| BL | 3V3 (always on) |
| PB1 | GP2 |
| PB2 | GP3 |
| PB3 | GP4 |
| PB4 | GP5 |
| EC11 A | GP10 |
| EC11 B | GP11 |
| EC11 Push Button | GP9 |
| EC11 Common | GND |
| Slide Switch Position 1 | GP6 |
| Slide Switch Position 2 | GP7 |
| Slide Switch Common | GP8, driven low by firmware |
| Slide Switch Position 3 | GND |

**What the test does:**
- Initializes display via SPI0, `rotation=90` for landscape 320×240
- Draws the idle screen: background fill, status bar, 2×2 cell grid with labels
- On button press: highlights the corresponding cell in `#3d4263` for 0.4 s
- Prints `PB1–PB4 → ACTION` to the serial console

**Required libraries on CIRCUITPY/lib/:**
```
adafruit_ili9341.mpy
adafruit_display_text/
adafruit_bus_device/
```

**Deploy (copy manually — not part of the main deploy script yet):**
```bash
cp pico/lcd_smoke_test.py /Volumes/CIRCUITPY/code.py
```

---

### 3. Raw HID client — response-fetch path added (`host_pc/raw_hid.py`)

The HID client now supports a full upload + response round-trip, wiring the
host to a Jetson LLM response flowing back through the Pico.

**New commands:**
- `GET_RESPONSE_INFO` (`0x20`) — query response buffer state
- `GET_RESPONSE_CHUNK` (`0x21`) — fetch a chunk of the response by index

**New types and methods:**

| Symbol | Description |
|---|---|
| `ResponseInfo` | Dataclass: `total_len`, `chunk_count`, `complete`, `active` |
| `get_response_info()` | Poll the device for current response state |
| `fetch_response()` | Download the full response text (chunked) |
| `round_trip_text(cmd, text)` | Upload + fetch response in one call |
| `stream_round_trip_text(...)` | Upload + poll with `on_update` callback for streaming UI |

**Reliability improvements:**
- `_read_until(predicate)` — all status waits now use a predicate loop instead of
  a raw `_read()`, fixing dropped reports when non-matching reports arrive first
- `_ensure_idle()` — called before every upload; aborts a stale session on the
  device if one exists, preventing stuck-`BUSY` errors after host timeouts

---

### 4. Serial sender — bidirectional CDC bridge (`host_pc/serial_sender.py`)

`SerialSender` was expanded from a one-way framed packet writer to a full
bidirectional CDC bridge to support the summarize streaming flow.

**New capabilities:**
- VID/PID-based Pico detection (`0xC4C4 / 0x5350`) via `list_ports` — more
  reliable than glob patterns on macOS and Windows
- `send_raw(payload, append_eot=False)` — send arbitrary bytes
- Background reader thread with `set_stream_callback(cb)` — fires callback on
  incoming bytes without blocking the Qt main thread
- `read_once()` — synchronous single-chunk read for callers that poll manually
- `ACK` (`0x06`) and `EOT` (`0x04`) byte constants

**Backward compatibility:** `send_window_new()` and `send_window_update()` are
unchanged; existing callers require no modification.

---

### 5. Web content extractor — new file (`host_pc/web_content.py`)

`WebContentExtractor` uses AppleScript to inject JavaScript into the active
browser tab and pull visible text. This bypasses the AX accessibility tree,
which returns almost nothing for browser-rendered content.

**Supported targets:**
| Target | JS strategy |
|---|---|
| Google Docs | `.kix-lineview-text-block` text nodes joined with `\n` |
| Google Sheets | `.waffle td` cell values joined with ` \| ` |
| General website | `document.body.innerText` truncated to 8 000 chars |

**Integration:**
- `TextSource.WEB_CONTENT` was added to `host_pc/accessibility/base.py`
- `spark_app_v2.py` now instantiates `WebContentExtractor` alongside `AccessibilityManager`
- Supported browsers are exposed as `SUPPORTED_BROWSERS` constant

---

### 6. Pico firmware — JetsonTransport integration (`pico/code.py`)

The Pico runtime loop now wires `JetsonTransport` into the upload handler so
that `AppCommand.FEATURE_1` uploads are forwarded to the Jetson over UART
instead of echoed back.

**Changes:**
- `JetsonTransport` imported and initialized on startup
- Upload loop: CDC relay and button injection are gated on
  `not jetson_transport.request_active`
- `jetson_transport.poll()` runs every tick; response bytes are passed to
  `protocol_handler.update_response_state()`
- `supervisor.runtime.autoreload` set to `True` (was `False`) — CIRCUITPY
  file saves now restart the runtime automatically
- UART timeout set to `0` (non-blocking) for the relay loop

---

### 7. Hardware wiring diagram added (`docs/pico/assets/pin_layout.png`)

Physical wiring diagram for the Pico ↔ ILI9341 LCD and PB1–PB4 buttons.
Reference for the smoke test pin constants in `pico/lcd_smoke_test.py`.

---

## Current Expected Behavior (branch head)

1. `spark_app_v2.py` captures host context via `AccessibilityManager` and
   `WebContentExtractor` (browser tabs).
2. Window context is sent over CDC serial to the Pico → Jetson path.
3. `Release Text` uploads `processed_text` to the Pico over Raw HID.
4. **New:** if the Pico forwards the upload to the Jetson and a response comes
   back, the host can fetch it via `GET_RESPONSE_INFO` / `GET_RESPONSE_CHUNK`.
5. The LCD UI kit (`lcd_screen_ui/`) mirrors the four action buttons on the
   physical ILI9341 display — the React screens are the design source of truth
   for what should be rendered by the Jetson GPU.

---

## Files Added This Branch

| File | Type |
|---|---|
| `lcd_screen_ui/` | New — React LCD UI kit |
| `host_pc/web_content.py` | New — browser text extractor |
| `pico/lcd_smoke_test.py` | New — CircuitPython ILI9341 smoke test |
| `docs/pico/assets/pin_layout.png` | New — hardware wiring diagram |
| `docs/BRANCH_HANDOFF_2026-03-29.md` | New — this file |

## Files Modified This Branch

| File | Summary of change |
|---|---|
| `host_pc/raw_hid.py` | Response-fetch commands, `_ensure_idle`, `_read_until`, streaming helpers |
| `host_pc/serial_sender.py` | VID/PID detection, bidirectional streaming, background reader thread |
| `host_pc/accessibility/base.py` | Added `TextSource.WEB_CONTENT` |
| `pico/code.py` | JetsonTransport integration, autoreload enabled, non-blocking UART |
| `spark_app_v2.py` | `WebContentExtractor` instantiation added |
| `REPO_STRUCTURE.md` | Updated to reflect all new files |
| `lcd_screen_ui/README.md` | Replaced generic Figma README with SPARK-specific docs |

---

## Known Notes / Open Items

- **Confirmed LCD/button pinout:** DIN/MOSI → GP19, CLK/SCK → GP18, CS → GP17,
  DC → GP16, RST → GP20, BL → 3V3, and PB1/PB2/PB3/PB4 → GP2/GP3/GP4/GP5.
- **Confirmed encoder/switch pinout:** EC11 A → GP10, EC11 B → GP11, EC11 push
  button → GP9, EC11 common → GND. The slide switch uses position 1 → GP6,
  position 2 → GP7, common → GP8 driven low by firmware, and position 3 → GND.
- **Thumbnail placeholders:** `IdleScreen.tsx` uses `placehold.co` URLs for the
  40×40 cell thumbnails. Replace with real PNGs before deploying to the Jetson.
- **Smoke test not in deploy script:** `lcd_smoke_test.py` must be manually
  copied to CIRCUITPY. It is intentionally separate from the production firmware.
- **`adafruit_ili9341` / `adafruit_display_text` not yet vendored:** these
  libraries must be present in `CIRCUITPY/lib/` before the smoke test runs.
  They are not yet bundled by `deploy_to_pico.py`.
- **Response-fetch Pico side not yet implemented:** `GET_RESPONSE_INFO` /
  `GET_RESPONSE_CHUNK` commands are implemented on the host in `raw_hid.py` but
  the Pico-side handler in `upload_protocol.py` is not yet written. The host
  calls will time out until that is added.
