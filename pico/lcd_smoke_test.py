"""
SPARK LCD + Button Smoke Test — CircuitPython
=============================================
Draws the idle screen on the ILI9341 and lights up a cell when a button is pressed.

Wiring
------
  DIN  (MOSI)  → GP19  (SPI0 TX)
  CLK  (SCK)   → GP18  (SPI0 SCK)
  CS           → GP17
  DC           → GP16  ← YOUR DIAGRAM SAYS GP18, BUT THAT CONFLICTS WITH CLK.
                          Change this constant if your DC wire is on a different pin.
  RST          → GP20
  BL           → 3V3   (backlight always on — no code needed)
  PB1          → GP2
  PB2          → GP3
  PB3          → GP4
  PB4          → GP5

Required libraries (copy to CIRCUITPY/lib/ before running)
-----------------------------------------------------------
  adafruit_ili9341.mpy
  adafruit_display_text/  (folder)
  adafruit_bus_device/    (folder)

Get them from: https://circuitpython.org/libraries  (download the bundle for your CP version)
"""

import time

import board
import busio
import displayio
import keypad
import terminalio
from adafruit_display_text import label
from digitalio import DigitalInOut

import adafruit_ili9341

# ── Pin constants ────────────────────────────────────────────────────────────
PIN_CLK  = board.GP18
PIN_MOSI = board.GP19
PIN_CS   = board.GP17
PIN_DC   = board.GP16   # ← CHANGE THIS if your DC wire is not on GP16
PIN_RST  = board.GP20

BUTTON_PINS = (board.GP2, board.GP3, board.GP4, board.GP5)  # PB1–PB4

# ── Colours ──────────────────────────────────────────────────────────────────
BG      = 0x1A1B26
SURFACE = 0x24283B
ACCENT  = 0x7AA2F7
WHITE   = 0xFFFFFF
ACTIVE  = 0x3D4263   # pressed cell colour

# ── Layout constants (must match the React UI) ───────────────────────────────
W, H    = 320, 240
BAR_H   = 24
PAD     = 8
GAP     = 8
CELL_W  = (W - 2 * PAD - GAP) // 2   # 148 px
CELL_H  = (H - BAR_H - 2 * PAD - GAP) // 2  # 96 px

ACTIONS = ["SYNTHESIS", "REFORMAT", "SEARCH", "RESPOND"]


# ── Helpers ──────────────────────────────────────────────────────────────────
def solid_rect(x, y, w, h, color):
    """Return a TileGrid filled with a single colour."""
    bmp = displayio.Bitmap(w, h, 1)
    pal = displayio.Palette(1)
    pal[0] = color
    return displayio.TileGrid(bmp, pixel_shader=pal, x=x, y=y)


def cell_origin(idx):
    col = idx % 2
    row = idx // 2
    x = PAD + col * (CELL_W + GAP)
    y = BAR_H + PAD + row * (CELL_H + GAP)
    return x, y


# ── Build display ────────────────────────────────────────────────────────────
displayio.release_displays()

spi = busio.SPI(clock=PIN_CLK, MOSI=PIN_MOSI)
dc  = DigitalInOut(PIN_DC)
cs  = DigitalInOut(PIN_CS)
rst = DigitalInOut(PIN_RST)

bus = displayio.FourWire(spi, command=dc, chip_select=cs,
                          reset=rst, baudrate=24_000_000)

# rotation=90 → landscape 320×240 (ILI9341 native is portrait 240×320)
display = adafruit_ili9341.ILI9341(bus, width=320, height=240, rotation=90)


# ── Build the idle-screen group ───────────────────────────────────────────────
root = displayio.Group()

# Background fill
root.append(solid_rect(0, 0, W, H, BG))

# Status bar background
root.append(solid_rect(0, 0, W, BAR_H, SURFACE))
# Status bar bottom border (2 px accent line)
root.append(solid_rect(0, BAR_H - 2, W, 2, ACCENT))
# Status bar label
root.append(label.Label(terminalio.FONT, text="SPARK READY", color=ACCENT,
                         x=8, y=BAR_H // 2, anchor_point=(0, 0.5),
                         anchored_position=(8, BAR_H // 2)))

# Cell background palettes — we mutate these on button press instead of
# rebuilding the whole group, which avoids screen flicker.
cell_palettes = []

for i, name in enumerate(ACTIONS):
    x, y = cell_origin(i)

    # Cell background (mutable palette so we can change colour on press)
    pal = displayio.Palette(1)
    pal[0] = SURFACE
    cell_palettes.append(pal)

    bmp = displayio.Bitmap(CELL_W, CELL_H, 1)
    root.append(displayio.TileGrid(bmp, pixel_shader=pal, x=x, y=y))

    # 2 px accent border — four thin rects
    root.append(solid_rect(x,            y,            CELL_W, 2,      ACCENT))  # top
    root.append(solid_rect(x,            y+CELL_H-2,   CELL_W, 2,      ACCENT))  # bottom
    root.append(solid_rect(x,            y,            2,      CELL_H, ACCENT))  # left
    root.append(solid_rect(x+CELL_W-2,   y,            2,      CELL_H, ACCENT))  # right

    # Action label centred in cell
    # terminalio.FONT glyphs are 6 × 14 px at scale=1
    root.append(label.Label(
        terminalio.FONT,
        text=name,
        color=WHITE,
        anchor_point=(0.5, 0.5),
        anchored_position=(x + CELL_W // 2, y + CELL_H // 2),
    ))

display.root_group = root

# ── Buttons ───────────────────────────────────────────────────────────────────
buttons = keypad.Keys(BUTTON_PINS, value_when_pressed=False, pull=True)

print("SPARK smoke test running — press PB1–PB4")

# ── Main loop ─────────────────────────────────────────────────────────────────
active_cell   = None
press_time    = 0.0
HIGHLIGHT_SEC = 0.4   # how long the cell stays highlighted after a press

while True:
    event = buttons.events.get()

    if event and event.pressed:
        idx = event.key_number          # 0=PB1 … 3=PB4
        print(f"PB{idx+1} → {ACTIONS[idx]}")

        # Clear previous highlight
        if active_cell is not None:
            cell_palettes[active_cell][0] = SURFACE

        # Highlight new cell
        cell_palettes[idx][0] = ACTIVE
        active_cell = idx
        press_time  = time.monotonic()

    # Auto-reset highlight
    if active_cell is not None and (time.monotonic() - press_time) > HIGHLIGHT_SEC:
        cell_palettes[active_cell][0] = SURFACE
        active_cell = None

    time.sleep(0.01)
