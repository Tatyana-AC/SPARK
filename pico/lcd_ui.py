try:
    from pico.pin_config import BUTTON_PIN_NUMBERS, LCD_PIN_NUMBERS
except ImportError:
    from pin_config import BUTTON_PIN_NUMBERS, LCD_PIN_NUMBERS

try:
    from pico.lcd_state import LcdState
except ImportError:
    from lcd_state import LcdState


BG = 0x1A1B26
SURFACE = 0x24283B
ACCENT = 0x7AA2F7
WHITE = 0xFFFFFF
ACTIVE = 0x3D4263

W = 320
H = 240
BAR_H = 24
PAD = 8
GAP = 8
CELL_W = (W - 2 * PAD - GAP) // 2
CELL_H = (H - BAR_H - 2 * PAD - GAP) // 2

DISPLAY_BAUDRATE = 24_000_000
DISPLAY_ROTATION = 180
HIGHLIGHT_SEC = 0.4

ACTIONS = ("SYNTHESIS", "REFORMAT", "SEARCH", "RESPOND")


def _debug_stage(message):
    try:
        from pico.pico_debug import dbg
    except Exception:
        try:
            from pico_debug import dbg
        except Exception:
            return

    try:
        dbg(f"lcd_ui:{message}")
    except Exception:
        return


def solid_rect(displayio_module, x, y, width, height, color, *, hidden=False):
    bitmap = displayio_module.Bitmap(width, height, 1)
    palette = displayio_module.Palette(1)
    palette[0] = color
    grid = displayio_module.TileGrid(bitmap, pixel_shader=palette, x=x, y=y)
    grid.hidden = hidden
    return grid


def cell_origin(index):
    column = index % 2
    row = index // 2
    x = PAD + column * (CELL_W + GAP)
    y = BAR_H + PAD + row * (CELL_H + GAP)
    return x, y


def build_display_bus(spi, dc, cs, rst, *, fourwire_class):
    return fourwire_class(
        spi,
        command=dc,
        chip_select=cs,
        reset=rst,
        baudrate=DISPLAY_BAUDRATE,
    )


def build_display(bus, *, display_driver_class, rotation=DISPLAY_ROTATION):
    return display_driver_class(bus, width=W, height=H, rotation=rotation)


def initialize_lcd_ui(mode="standalone"):
    if mode == "standalone":
        return _initialize_standalone_lcd_ui()
    if mode == "bridge":
        return _initialize_bridge_lcd_ui()
    raise ValueError(f"unsupported lcd ui mode: {mode}")


def _initialize_standalone_lcd_ui():
    import board
    import busio
    import displayio
    import terminalio
    from adafruit_display_text import label
    import adafruit_ili9341
    from digitalio import DigitalInOut
    from fourwire import FourWire

    def board_pin(number):
        return getattr(board, f"GP{number}")

    displayio.release_displays()
    spi = busio.SPI(clock=board_pin(LCD_PIN_NUMBERS["clk"]), MOSI=board_pin(LCD_PIN_NUMBERS["mosi"]))
    dc = DigitalInOut(board_pin(LCD_PIN_NUMBERS["dc"]))
    cs = DigitalInOut(board_pin(LCD_PIN_NUMBERS["cs"]))
    rst = DigitalInOut(board_pin(LCD_PIN_NUMBERS["rst"]))
    bus = build_display_bus(spi, dc, cs, rst, fourwire_class=FourWire)
    display = build_display(bus, display_driver_class=adafruit_ili9341.ILI9341)
    ui = SparkLcdUi(displayio_module=displayio, label_module=label, font=terminalio.FONT)
    display.root_group = ui.root_group
    return ui


def _initialize_bridge_lcd_ui():
    _debug_stage("bridge:init:start")
    _pulse_stage_led(3)
    try:
        from pico.lcd_renderer_spi import initialize_bridge_renderer
    except ImportError:
        from lcd_renderer_spi import initialize_bridge_renderer

    _debug_stage("bridge:init:renderer-imported")
    _pulse_stage_led(5)

    renderer = initialize_bridge_renderer()
    _debug_stage("bridge:init:renderer-ready")
    _pulse_stage_led(7)

    return _BridgeSparkLcdUi(renderer=renderer)


def _pulse_stage_led(count):
    try:
        import board
        import digitalio
    except ImportError:
        return

    led_pin = getattr(board, "LED", None)
    if led_pin is None:
        led_pin = getattr(board, "GP25", None)
    if led_pin is None:
        return

    try:
        led = digitalio.DigitalInOut(led_pin)
        led.switch_to_output(value=False)
    except Exception:
        return

    try:
        import time

        for _ in range(count):
            led.value = True
            time.sleep(0.05)
            led.value = False
            time.sleep(0.05)
        time.sleep(0.15)
    finally:
        led.deinit()


class SparkLcdUi:
    def __init__(self, *, displayio_module, label_module, font):
        self._displayio = displayio_module
        self._label = label_module
        self._font = font
        self._state = LcdState(highlight_sec=HIGHLIGHT_SEC)
        self.root_group = displayio_module.Group()
        self.cell_views = []
        self.active_cell = None
        self.press_time = 0.0
        self._build_root_group()
        self._sync_public_state()

    def _build_root_group(self):
        self.root_group.append(solid_rect(self._displayio, 0, 0, W, H, BG))
        self.root_group.append(solid_rect(self._displayio, 0, 0, W, BAR_H, SURFACE))
        self.root_group.append(solid_rect(self._displayio, 0, BAR_H - 2, W, 2, ACCENT))
        self.root_group.append(
            self._label.Label(
                self._font,
                text="SPARK READY",
                color=ACCENT,
                x=8,
                y=BAR_H // 2,
                anchor_point=(0, 0.5),
                anchored_position=(8, BAR_H // 2),
            )
        )

        for index, name in enumerate(ACTIONS):
            x, y = cell_origin(index)

            cell_group = self._displayio.Group()
            cell_group.x = x
            cell_group.y = y

            base_fill = solid_rect(self._displayio, 0, 0, CELL_W, CELL_H, SURFACE)
            pressed_overlay = solid_rect(self._displayio, 0, 0, CELL_W, CELL_H, ACTIVE, hidden=True)
            top_border = solid_rect(self._displayio, 0, 0, CELL_W, 2, ACCENT)
            bottom_border = solid_rect(self._displayio, 0, CELL_H - 2, CELL_W, 2, ACCENT)
            left_border = solid_rect(self._displayio, 0, 0, 2, CELL_H, ACCENT)
            right_border = solid_rect(self._displayio, CELL_W - 2, 0, 2, CELL_H, ACCENT)
            label = self._label.Label(
                self._font,
                text=name,
                color=WHITE,
                anchor_point=(0.5, 0.5),
                anchored_position=(CELL_W // 2, CELL_H // 2),
            )

            cell_group.append(base_fill)
            cell_group.append(pressed_overlay)
            cell_group.append(top_border)
            cell_group.append(bottom_border)
            cell_group.append(left_border)
            cell_group.append(right_border)
            cell_group.append(label)

            self.cell_views.append(
                CellView(
                    index=index,
                    name=name,
                    group=cell_group,
                    pressed_overlay=pressed_overlay,
                    label=label,
                )
            )
            self.root_group.append(cell_group)

    def handle_press(self, index, *, now):
        change = self._state.press(index, now=now)
        if change.visible_changed:
            if change.previous_active is not None and change.previous_active != index:
                self.cell_views[change.previous_active].pressed_overlay.hidden = True
            self.cell_views[index].pressed_overlay.hidden = False
        self._sync_public_state()

    def tick(self, *, now):
        change = self._state.tick(now=now)
        if change.visible_changed:
            self.cell_views[change.previous_active].pressed_overlay.hidden = True
        self._sync_public_state()

    def _sync_public_state(self):
        self.active_cell = self._state.active_index
        self.press_time = self._state.press_time


class CellView:
    def __init__(self, *, index, name, group, pressed_overlay, label):
        self.index = index
        self.name = name
        self.group = group
        self.pressed_overlay = pressed_overlay
        self.label = label


class _BridgeSparkLcdUi:
    def __init__(self, *, renderer):
        self._renderer = renderer
        self._state = LcdState(highlight_sec=HIGHLIGHT_SEC)
        self.active_cell = None
        self.press_time = 0.0
        self._sync_public_state()

    def handle_press(self, index, *, now):
        change = self._state.press(index, now=now)
        if change.visible_changed:
            if change.previous_active is not None and change.previous_active != index:
                self._renderer.draw_idle_cell(change.previous_active)
            self._renderer.draw_pressed_cell(index)
        self._sync_public_state()

    def tick(self, *, now):
        change = self._state.tick(now=now)
        if change.visible_changed:
            self._renderer.draw_idle_cell(change.previous_active)
        self._sync_public_state()

    def _sync_public_state(self):
        self.active_cell = self._state.active_index
        self.press_time = self._state.press_time
