# Pico Runtime Contention Report & Cooperative Scheduler Plan

**Date**: 2026-04-08
**Branch**: `sida`
**Scope**: Architectural analysis of communication/LCD interference in the bridge-mode Pico runtime, with a concrete implementation plan for fixing every identified issue.

## Background

The Pico serves as a bridge between the host PC and the Jetson, running a single-threaded cooperative loop (`BridgeRuntime.run_once`) that handles:

- **USB HID**: Custom vendor HID protocol (32-byte reports, usage page `0xFF60`) for text upload and response retrieval
- **USB CDC**: Serial bridge relay from host to Jetson
- **UART**: Framed packet transport to/from Jetson (`JetsonTransport`)
- **SPI LCD**: ILI9341 320x240 display via direct SPI writes (bridge-mode renderer)
- **Buttons**: 4 GPIO buttons via `keypad.Keys`

The bridge-mode SPI renderer (`lcd_renderer_spi.py`) replaced the earlier `displayio`-based path after hardware investigation proved that `displayio` mutations during the active runtime caused board crashes (see `PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`). The SPI renderer is hardware-verified stable, but the current loop structure has latent contention issues that will degrade reliability under load.

## Current Main Loop Structure

```
BridgeRuntime.run_once(now):
  1. CDC debug heartbeat         (every 2s, writes to usb_cdc.data)
  2. serial_bridge.relay_once()  (reads CDC data → writes UART, max 64B)
  3. jetson_transport.poll()     (reads UART → parses packets, max 64B)
  4. _sync_response_state()      (copies transport state to protocol handler)
  5. _drain_hid_reports()        (reads ALL pending HID reports, replies immediately)
  6. drain ONE button event      (LCD SPI draw + optional UART write)
  7. ui.tick()                   (LCD SPI draw if highlight expired)
  8. time.sleep(0.002)           (2ms)
```

Reference: `pico/bridge_runtime.py:62-94`

---

## Problem 1: LCD SPI Writes Block the Entire Loop

**Severity**: CRITICAL
**Files**: `pico/lcd_renderer_spi.py:334-350`, `pico/lcd_renderer_spi.py:249-277`

### Description

Every LCD operation goes through `Ili9341SpiTarget._write()`:

```python
def _write(self, *, command=None, data=None):
    while not self._spi.try_lock():
        pass                                    # spin-lock
    self._spi.configure(baudrate=self._baudrate, polarity=0, phase=0)
    try:
        self._cs.value = False
        if command is not None:
            self._dc.value = False
            self._spi.write(bytes((command,)))   # blocking SPI transfer
        if data is not None:
            self._dc.value = True
            self._spi.write(data)                # blocking SPI transfer
    finally:
        self._cs.value = True
        self._spi.unlock()
```

The SPI bus is dedicated to the LCD (no other SPI peripherals), so the spin-lock itself acquires immediately. The real cost is the **time spent inside `self._spi.write(data)`** — this is a synchronous, blocking transfer.

### Quantified Impact

A single cell redraw (`draw_pressed_cell` or `draw_idle_cell`) calls `blit_pixels()` which transfers a pre-rendered pixel buffer for one cell:

- Cell size: `CELL_W × CELL_H = 150 × 96 = 14,400 pixels = 28,800 bytes`
- Chunk size: 256 pixels = 512 bytes per SPI transaction
- Transactions per cell: `28,800 / 512 = ~57 SPI writes`
- Each SPI write also requires a `_write_window()` call (3 command writes) at the start

At 24 MHz SPI with overhead, each cell blit takes roughly **10-20ms**. During this time, **nothing else runs**: no UART polling, no HID processing, no button events.

The initial `draw_idle_layout()` is worse — it fills the entire 320×240 screen + header + 4 cells — but this only runs once at startup.

### Failure Scenario

1. Jetson sends a large summarize response (4KB = ~20 UART packets)
2. User presses button → `handle_press()` → `draw_pressed_cell()` → **10-20ms blocked**
3. 0.4s later, `tick()` → `draw_idle_cell()` → **10-20ms blocked again**
4. During those ~30ms total, UART data arrives but is not polled
5. At 115200 baud, ~1.3KB arrives in 30ms but the UART buffer is only 256 bytes
6. **UART buffer overflows → response data is silently lost**

---

## Problem 2: UART Shared Without Arbitration

**Severity**: HIGH
**Files**: `pico/serial_bridge.py:6-16`, `pico/jetson_transport.py:108-113`, `pico/bridge_runtime.py:68-71`

### Description

Both `SerialBridge` and `JetsonTransport` write to the **same UART object**, created once in `code.py:84`:

```python
uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0, receiver_buffer_size=256)
```

In each loop iteration, both are called sequentially with no mutual exclusion:

```python
self._serial_bridge.relay_once(max_chunk_size=self._relay_chunk_size)    # line 68 — writes to UART
self._jetson_transport.poll(max_chunk_size=self._relay_chunk_size)        # line 71 — reads from UART
```

Additionally, button presses trigger `jetson_transport.start_request()` which also writes to UART (line 84-85).

### Failure Scenario

1. Host sends 200 bytes via CDC data channel (arbitrary relay data)
2. `relay_once()` writes first 64 bytes to UART
3. Next iteration: `relay_once()` writes next 64 bytes to UART
4. User presses button → `button_press_handler()` → `start_request()` → writes structured `SP`-framed packet to UART
5. Next iteration: `relay_once()` writes remaining 72 bytes to UART
6. Jetson receives interleaved stream: `[64B relay][64B relay][~60B request packet][72B relay]`
7. The `PacketParser` on the Jetson side can resync on `SP` magic bytes, but the relay data may contain `0x53 0x50` by coincidence, causing parser desync

### Current Risk Level

If CDC relay and Jetson transport are never used simultaneously in practice, this is latent. But the code has **no guard** preventing it — any host CDC data while a button-triggered request is in flight will interleave.

---

## Problem 3: HID Report Drain is Unbounded

**Severity**: MEDIUM-HIGH
**Files**: `pico/bridge_runtime.py:126-133`

### Description

```python
def _drain_hid_reports(self):
    while True:
        report = self._custom_hid.get_last_received_report(self._raw_report_id)
        if report is None:
            return
        reply = self._protocol_handler.handle_report(report)
        if reply is not None:
            self._custom_hid.send_report(reply, self._raw_report_id)
```

This loop processes **all** pending HID reports before returning control to the main loop. During a multi-chunk upload:

- 4KB upload = `ceil(4096 / 27) = 152` UPLOAD_CHUNK reports + 1 BEGIN + 1 COMMIT = **154 reports**
- The host sends these with a 10ms inter-report gap (`INTER_REPORT_GAP_S = 0.01` in `host_pc/raw_hid.py:34`)
- If the Pico falls behind (e.g., after an LCD draw), multiple reports queue up
- The drain loop processes all of them before UART polling resumes

### Impact

At 154 reports × ~0.1ms processing each = ~15ms with no UART poll. Combined with an LCD draw that preceded it, total UART starvation could reach 25-35ms.

The UART receive buffer is 256 bytes. At 115200 baud (~11.5KB/s), 256 bytes fills in ~22ms. So HID drain alone can cause buffer overflow if a Jetson response is actively streaming.

---

## Problem 4: UART Receive Buffer Too Small

**Severity**: MEDIUM
**Files**: `pico/code.py:84`

### Description

```python
uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0, receiver_buffer_size=256)
```

The 256-byte buffer provides only ~22ms of tolerance at 115200 baud before data is silently dropped. Given that LCD draws can block for 10-20ms and HID drains can add another 15ms, the margin is dangerously thin.

CircuitPython on RP2040 supports `receiver_buffer_size` up to at least 4096. Increasing this is a one-line fix with no behavioral change.

---

## Problem 5: No Visual Feedback During Active Requests

**Severity**: MEDIUM
**Files**: `pico/lcd_state.py`, `pico/lcd_ui.py:259-283`

### Description

`LcdState` tracks exactly two visual states:

- **Active** (highlighted): from button press until `highlight_sec` (0.4s) expires
- **Idle**: default surface color

There is no representation for:

| Missing State | When It Applies | Duration |
|---|---|---|
| WAITING | Request sent, no response yet | 0-30s |
| RECEIVING | Response chunks arriving | Variable |
| DONE | Response complete | Brief flash |
| ERROR | Timeout or Jetson error | Brief flash |
| BUSY | Duplicate press rejected | Brief flash |

After the 0.4s highlight expires, the button appears idle even if a 30-second Jetson request is in flight. If the user presses again, the request is rejected silently (the `BridgeApp` returns `StatusCode.BUSY` but nothing is drawn).

---

## Problem 6: Button Press Triggers Both LCD Draw and UART Write in Same Iteration

**Severity**: MEDIUM
**Files**: `pico/bridge_runtime.py:80-86`

### Description

```python
for button_event in self._button_input.drain_pressed_events():
    self._emit_debug(f"button:{button_event.index}")
    if self._ui is not None:
        self._ui.handle_press(button_event.index, now=now)     # SPI draw (~15ms)
    if button_event.index == 0 and self._button_press_handler is not None:
        self._button_press_handler(button_event.index)          # UART write (immediate)
    break
```

A single button event causes:
1. `handle_press()` → `draw_pressed_cell()` → 10-20ms of SPI blocking
2. `button_press_handler()` → `start_request()` → UART write

The UART write happens immediately after the LCD draw, but during the LCD draw, any incoming UART data was not polled. This is a localized instance of Problem 1.

---

## Problem 7: Response State Not Atomic Across HID Queries

**Severity**: LOW-MEDIUM
**Files**: `pico/bridge_runtime.py:109-124`, `pico/upload_protocol.py:173-199`

### Description

The host retrieves response data in two separate HID round-trips:
1. `GET_RESPONSE_INFO` → returns `(length, flags)` where flags encode `complete` and `active`
2. `GET_RESPONSE_CHUNK` → returns 27-byte chunk at a given index

Between these two queries, the main loop continues running. `_sync_response_state()` may update `_response_bytes`, `_response_complete`, and `_response_active` between the two HID reads. The host can therefore see:

- A length from before the latest chunk arrived, but chunk data that includes it
- A `complete=false` flag followed by a chunk read that finds the response is now shorter (if a new request reset the buffer)

In practice, the host polls with a timer and retries, so this is unlikely to cause data corruption, but it means the host can see inconsistent snapshots.

---

## Implementation Plan: Cooperative Time-Sliced Scheduler

### Design Principles

1. **UART poll is highest priority** — always runs first, prevents buffer overflow
2. **LCD draws are deferred and chunked** — one cell per iteration, not immediate
3. **HID drain is bounded** — max N reports per iteration
4. **CDC relay is gated** — disabled while a Jetson request is active
5. **All changes stay within CircuitPython** — no platform migration

### New Loop Structure

```
run_once(now):
  1. jetson_transport.poll()           # UART first — highest priority
  2. _sync_response_state()            # state copy
  3. _drain_hid_reports(max=4)         # bounded HID processing
  4. if not transport.request_active:
       serial_bridge.relay_once()      # CDC relay only when UART is idle
  5. drain ONE button event            # enqueue dirty cell, trigger request
  6. ui.tick(now)                       # check highlight expiry, enqueue dirty cell
  7. _flush_one_lcd_update()           # render ONE queued cell
  8. time.sleep(0.002)
```

### Change 1: Increase UART Buffer

**File**: `pico/code.py:84`
**Effort**: Trivial (1 line)
**Risk**: None

Change:
```python
# Before
uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0, receiver_buffer_size=256)

# After
uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0, receiver_buffer_size=1024)
```

This gives ~89ms of buffer tolerance at 115200 baud instead of ~22ms. Even if an LCD draw blocks for 20ms and HID drain adds 15ms, there's ample margin.

**Validation**: Existing tests pass unchanged. Hardware smoke test confirms UART still works.

### Change 2: Gate CDC Relay on Transport State

**File**: `pico/bridge_runtime.py:68`
**Effort**: Trivial (3 lines)
**Risk**: Low — CDC relay is paused during Jetson requests, which is correct behavior since the host shouldn't be sending relay data while a structured request is in flight

Change:
```python
# Before
self._serial_bridge.relay_once(max_chunk_size=self._relay_chunk_size)

# After
if not self._jetson_transport.request_active:
    self._serial_bridge.relay_once(max_chunk_size=self._relay_chunk_size)
```

**Validation**: Add test that relay is skipped when `request_active=True`. Existing relay tests pass unchanged.

### Change 3: Move UART Poll to Top of Loop

**File**: `pico/bridge_runtime.py:62-94`
**Effort**: Trivial (reorder 2 lines)
**Risk**: None — UART poll has no dependency on prior steps

Change: Move `jetson_transport.poll()` and `_sync_response_state()` to execute before `serial_bridge.relay_once()` and the heartbeat.

```python
def run_once(self, *, now):
    # UART poll first — highest priority, prevents buffer overflow
    self._jetson_transport.poll(max_chunk_size=self._relay_chunk_size)
    self._sync_response_state()

    if (now - self._last_debug_heartbeat) >= self._heartbeat_interval_s:
        self._emit_debug("heartbeat")
        self._last_debug_heartbeat = now

    if not self._jetson_transport.request_active:
        self._serial_bridge.relay_once(max_chunk_size=self._relay_chunk_size)

    self._drain_hid_reports()
    # ... buttons, UI, sleep
```

**Validation**: Existing `BridgeRuntime` tests pass with updated checkpoint assertions.

### Change 4: Cap HID Drain Per Iteration

**File**: `pico/bridge_runtime.py:126-133`
**Effort**: Trivial (2 lines)
**Risk**: None — remaining reports are processed in subsequent iterations

Change:
```python
# Before
def _drain_hid_reports(self):
    while True:
        report = self._custom_hid.get_last_received_report(self._raw_report_id)
        if report is None:
            return
        reply = self._protocol_handler.handle_report(report)
        if reply is not None:
            self._custom_hid.send_report(reply, self._raw_report_id)

# After
def _drain_hid_reports(self):
    for _ in range(self._max_hid_reports_per_tick):
        report = self._custom_hid.get_last_received_report(self._raw_report_id)
        if report is None:
            return
        reply = self._protocol_handler.handle_report(report)
        if reply is not None:
            self._custom_hid.send_report(reply, self._raw_report_id)
```

Add `max_hid_reports_per_tick=4` to `__init__`. With the host sending at 10ms gaps, 4 reports per 2ms tick keeps up while bounding the loop to ~0.4ms of HID work.

**Validation**: Add test that only N reports are processed per call. Existing tests pass with the cap set high enough.

### Change 5: Deferred LCD Rendering with Dirty Queue

**New file**: `pico/lcd_update_queue.py`
**Modified files**: `pico/lcd_ui.py`, `pico/bridge_runtime.py`
**Effort**: Medium
**Risk**: Low — rendering still calls the same `SpiLcdRenderer` methods, just deferred by one iteration

New module:

```python
class LcdUpdateQueue:
    """Queues LCD cell updates for one-per-tick flushing."""

    def __init__(self, renderer):
        self._renderer = renderer
        self._pending = {}   # index → "pressed" | "idle"

    def enqueue_pressed(self, index):
        self._pending[index] = "pressed"

    def enqueue_idle(self, index):
        # Don't overwrite a pending pressed with idle if both queued same tick
        if self._pending.get(index) != "pressed":
            self._pending[index] = "idle"

    def flush_one(self):
        """Render one queued cell. Returns True if work was done."""
        if not self._pending:
            return False
        index, state = self._pending.popitem()
        if state == "pressed":
            self._renderer.draw_pressed_cell(index)
        else:
            self._renderer.draw_idle_cell(index)
        return True

    @property
    def has_pending(self):
        return bool(self._pending)
```

Modify `_BridgeSparkLcdUi` to enqueue instead of drawing:

```python
class _BridgeSparkLcdUi:
    def __init__(self, *, renderer):
        self._renderer = renderer
        self._state = LcdState(highlight_sec=HIGHLIGHT_SEC)
        self._queue = LcdUpdateQueue(renderer)
        # ...

    def handle_press(self, index, *, now):
        change = self._state.press(index, now=now)
        if change.visible_changed:
            if change.previous_active is not None and change.previous_active != index:
                self._queue.enqueue_idle(change.previous_active)
            self._queue.enqueue_pressed(index)
        self._sync_public_state()

    def tick(self, *, now):
        change = self._state.tick(now=now)
        if change.visible_changed:
            self._queue.enqueue_idle(change.previous_active)
        self._sync_public_state()

    def flush_one(self):
        return self._queue.flush_one()
```

Update `BridgeRuntime.run_once`:

```python
# After buttons and ui.tick:
if self._ui is not None:
    self._ui.flush_one()
```

**Effect**: A button press enqueues the highlight. The cell is rendered on the **next** loop iteration (2ms later — imperceptible to the user). But critically, UART is polled **before** the SPI draw on that next iteration, so incoming data is drained first.

**Validation**: Existing LCD UI tests adapted to check queue state instead of immediate draw calls. New tests for `LcdUpdateQueue` cover enqueue/flush/priority logic.

### Change 6: State-Aware UI Feedback (Optional Enhancement)

**Modified files**: `pico/lcd_state.py`, `pico/lcd_ui.py`, `pico/lcd_renderer_spi.py`
**Effort**: Medium
**Risk**: Low — additive, no changes to existing color/layout logic

Extend `LcdState` with a `mode` field:

```python
class CellMode:
    IDLE = 0
    PRESSED = 1
    WAITING = 2       # request sent, no response yet
    DONE = 3          # response complete

class LcdState:
    def __init__(self, *, highlight_sec=DEFAULT_HIGHLIGHT_SEC):
        self.highlight_sec = highlight_sec
        self.active_index = None
        self.press_time = 0.0
        self.highlight_expires_at = None
        self.cell_modes = [CellMode.IDLE] * 4

    def set_cell_mode(self, index, mode):
        """Called by runtime when transport state changes."""
        previous = self.cell_modes[index]
        self.cell_modes[index] = mode
        return previous != mode   # returns True if visual update needed
```

Add colors to the renderer:

```python
WAITING_COLOR = 0x2D3A6A    # dimmer blue tint
DONE_COLOR    = 0x1A3A26    # brief green tint
```

The runtime sets `cell_modes[0] = WAITING` when `button_press_handler` starts a request, and `cell_modes[0] = DONE` when `_sync_response_state` sees `response_complete=True`. After a brief display period, the cell returns to `IDLE`.

**This change is optional for the first pass.** The first five changes fix all contention issues. This one improves UX.

### Implementation Order

| Step | Change | Lines Changed | Test Impact |
|------|--------|---------------|-------------|
| 1 | Increase UART buffer to 1024 | 1 | None |
| 2 | Gate CDC relay on `request_active` | 3 | 1 new test |
| 3 | Move UART poll to top of loop | ~10 (reorder) | Checkpoint assertion updates |
| 4 | Cap HID drain at 4 per tick | 5 | 1 new test, existing pass |
| 5 | Deferred LCD dirty queue | ~80 new, ~20 modified | New queue tests, adapted UI tests |
| 6 | State-aware UI feedback | ~60 new, ~30 modified | New state/mode tests |

Steps 1-4 can be done together as a single commit — they're independent, trivial changes that collectively eliminate the most dangerous interference. Step 5 is the structural change. Step 6 is optional polish.

### Worst-Case Timing After All Changes

```
UART poll:           ~0.5ms  (64 bytes at 115200 + parse)
Response sync:       ~0.1ms  (tuple compare + state copy)
HID drain (4 max):   ~0.4ms  (4 × report parse + reply)
CDC relay:           ~0.3ms  (64 bytes read + write)
Button drain:        ~0.1ms  (queue read + enqueue, no draw)
UI tick:             ~0.1ms  (timestamp compare + enqueue, no draw)
LCD flush one cell:  ~15ms   (one cell blit — unavoidable SPI time)
Sleep:                2ms

Total per tick:      ~18ms worst case (with LCD flush)
                     ~3.5ms typical (no LCD flush needed)
```

UART is polled first every iteration. Even in the worst case (LCD flush active), the UART buffer now holds 1024 bytes = ~89ms of data. The 18ms worst-case tick uses only 20% of the buffer capacity. **Buffer overflow is no longer possible under normal conditions.**

### Files to Create

- `pico/lcd_update_queue.py` — dirty queue class
- `tests/test_lcd_update_queue.py` — queue unit tests

### Files to Modify

- `pico/code.py` — UART buffer size
- `pico/bridge_runtime.py` — loop reorder, relay gate, HID cap, flush call
- `pico/lcd_ui.py` — `_BridgeSparkLcdUi` enqueues instead of drawing
- `tests/test_pico_code.py` — updated integration tests
- `tests/test_pico_lcd_ui.py` — adapted for deferred rendering
- `tests/test_bridge_runtime.py` or equivalent — new contention tests

### Files Unchanged

- `pico/lcd_renderer_spi.py` — no changes needed, rendering API stays the same
- `pico/lcd_state.py` — no changes for steps 1-5 (step 6 extends it)
- `pico/jetson_transport.py` — no changes
- `pico/upload_protocol.py` — no changes
- `pico/serial_bridge.py` — no changes
- `pico/boot.py` — no changes
- `pico/button_input.py` — no changes
- `pico/bridge_app.py` — no changes
- `pico/usb_config.py` — no changes

### Hardware Validation Plan

Each step should be hardware-verified in the same rung-by-rung approach used during the original LCD investigation:

1. **After steps 1-4**: Deploy, reset, confirm heartbeats continue. Run host-side `ping()` + `upload()`. Press buttons during an active Jetson request. Verify no UART data loss by checking response completeness.

2. **After step 5**: Deploy, reset, press buttons rapidly. Verify highlight appears within one visible frame (~20ms). Verify Jetson response still arrives complete during button spam. Check that highlight clears properly after 0.4s.

3. **After step 6** (if implemented): Verify WAITING color appears after button press, transitions to DONE on response, returns to IDLE.
