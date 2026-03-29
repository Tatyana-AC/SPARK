# SPARK LCD Screen UI

React UI kit for the 2.4" ILI9341 320×240px LCD display driven by the NVIDIA Jetson.
Exported from Figma and customized for the SPARK hardware target.

## Hardware target

| Property | Value |
|---|---|
| Display | 2.4" ILI9341 |
| Resolution | 320 × 240 px |
| PPI | 167 |
| Driver | NVIDIA Jetson (full GPU, 60fps capable) |
| Font | JetBrains Mono |

## Running locally (browser preview)

```bash
npm install
npm run dev
```

Open `http://localhost:5173` in Chrome. To preview at exact screen dimensions:

1. Open DevTools (`Cmd+Opt+I`) → toggle device toolbar
2. Add a custom device: **320 × 240, DPR 1, name ILI9341**
3. Select it from the dropdown

## Project structure

```
src/
  app/
    App.tsx                     # State machine: idle → confirmation → processing → success
    components/
      IdleScreen.tsx            # 2×2 action grid (SYNTHESIS, REFORMAT, SEARCH, RESPOND)
      ConfirmationScreen.tsx    # Confirm / cancel split
      ProcessingScreen.tsx      # Spinner state
      SuccessScreen.tsx         # Success state with auto-return
  styles/
    theme.css                   # CSS custom properties (colours, radius, etc.)
    fonts.css                   # JetBrains Mono import
```

## Screen constraints

- Every screen must be exactly **320 × 240 px** (`w-[320px] h-[240px]`)
- Status bar is always **24 px** tall, leaving **216 px** for content
- Minimum touch target: **44 px** (current 2×2 grid cells are 148 × 96 px ✓)
- Minimum readable font size: **14 px CSS** (≈ 10 px physical at 167 PPI)

## Colour palette

| Name | Hex |
|---|---|
| Background | `#1a1b26` |
| Surface | `#24283b` |
| Accent | `#7aa2f7` |
| Success | `#10b981` |
| Danger | `#dc2626` |
| Active/press | `#3d4263` |

## IdleScreen layout

Each action button cell (148 × 96 px) contains, top to bottom:

1. 40 × 40 px thumbnail image (swap `placehold.co` URLs for real PNGs)
2. Lucide icon at 32 px, stroke-width 2.5, colour `#7aa2f7`
3. Label in JetBrains Mono 14 px / 700 / tracking-wider
4. Four corner-bracket decorations (8 × 8 px L-shapes, 1 px border, 60% opacity)

## Hardware smoke test

A separate CircuitPython script for validating the physical display is at
`pico/lcd_smoke_test.py`. See `pico/HARDWARE_SMOKE_TEST.md` for wiring and
library setup.
