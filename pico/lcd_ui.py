try:
    from pico.pin_config import LCD_PIN_NUMBERS
except ImportError:
    from pin_config import LCD_PIN_NUMBERS


BG = 0x1A1B26
SURFACE = 0x24283B
ACCENT = 0x7AA2F7
WHITE = 0xFFFFFF
ACTIVE = 0x3D4263

WIDTH = 320
HEIGHT = 240
BAR_HEIGHT = 24
PADDING = 8
GAP = 8
CELL_WIDTH = (WIDTH - 2 * PADDING - GAP) // 2
CELL_HEIGHT = (HEIGHT - BAR_HEIGHT - 2 * PADDING - GAP) // 2
HIGHLIGHT_SEC = 0.4
DISPLAY_ROTATION = 180
HIGHLIGHT_HIDDEN_X = WIDTH
HIGHLIGHT_HIDDEN_Y = HEIGHT

ACTIONS = ("SYNTHESIS", "REFORMAT", "SEARCH", "RESPOND")


def solid_rect(displayio_module, x, y, width, height, color):
    bitmap = displayio_module.Bitmap(width, height, 1)
    palette = displayio_module.Palette(1)
    palette[0] = color
    return displayio_module.TileGrid(bitmap, pixel_shader=palette, x=x, y=y)


def cell_origin(index):
    column = index % 2
    row = index // 2
    x = PADDING + column * (CELL_WIDTH + GAP)
    y = BAR_HEIGHT + PADDING + row * (CELL_HEIGHT + GAP)
    return x, y


def build_display_bus(spi, dc, cs, rst, *, fourwire_class):
    return fourwire_class(
        spi,
        command=dc,
        chip_select=cs,
        reset=rst,
        baudrate=24_000_000,
    )


def build_display(bus, *, display_driver_class):
    return display_driver_class(
        bus,
        width=WIDTH,
        height=HEIGHT,
        rotation=DISPLAY_ROTATION,
    )


class SparkLcdUi:
    def __init__(
        self,
        *,
        displayio_module,
        label_module,
        font,
        debug_hook=None,
        debug_checkpoint=None,
        skip_palette_write=False,
        skip_highlight_update=False,
        skip_highlight_clear=False,
    ):
        self._displayio = displayio_module
        self._label = label_module
        self._font = font
        self._debug_hook = debug_hook
        self._debug_checkpoint = debug_checkpoint
        self._skip_palette_write = skip_palette_write
        self._skip_highlight_update = skip_highlight_update
        self._skip_highlight_clear = skip_highlight_clear
        self.root_group = displayio_module.Group()
        self.cell_palettes = []
        self.active_cell = None
        self.press_time = 0.0
        self._highlight_grid = None
        self._build_idle_screen()

    def _debug(self, message):
        if self._debug_hook is None:
            return
        try:
            self._debug_hook(message)
        except Exception:
            return

    def _debug_checkpoint_message(self, checkpoint, index):
        if self._debug_checkpoint != checkpoint:
            return
        self._debug(f"lcd:handle_press:{checkpoint} index={index}")

    def _build_idle_screen(self):
        root = self.root_group
        root.append(solid_rect(self._displayio, 0, 0, WIDTH, HEIGHT, BG))
        root.append(solid_rect(self._displayio, 0, 0, WIDTH, BAR_HEIGHT, SURFACE))
        root.append(solid_rect(self._displayio, 0, BAR_HEIGHT - 2, WIDTH, 2, ACCENT))
        root.append(
            self._label.Label(
                self._font,
                text="SPARK READY",
                color=ACCENT,
                x=8,
                y=BAR_HEIGHT // 2,
                anchor_point=(0, 0.5),
                anchored_position=(8, BAR_HEIGHT // 2),
            )
        )

        for index, name in enumerate(ACTIONS):
            x, y = cell_origin(index)
            palette = self._displayio.Palette(1)
            palette[0] = SURFACE
            self.cell_palettes.append(palette)

            bitmap = self._displayio.Bitmap(CELL_WIDTH, CELL_HEIGHT, 1)
            root.append(self._displayio.TileGrid(bitmap, pixel_shader=palette, x=x, y=y))
            root.append(solid_rect(self._displayio, x, y, CELL_WIDTH, 2, ACCENT))
            root.append(solid_rect(self._displayio, x, y + CELL_HEIGHT - 2, CELL_WIDTH, 2, ACCENT))
            root.append(solid_rect(self._displayio, x, y, 2, CELL_HEIGHT, ACCENT))
            root.append(solid_rect(self._displayio, x + CELL_WIDTH - 2, y, 2, CELL_HEIGHT, ACCENT))
            root.append(
                self._label.Label(
                    self._font,
                    text=name,
                    color=WHITE,
                    anchor_point=(0.5, 0.5),
                    anchored_position=(x + CELL_WIDTH // 2, y + CELL_HEIGHT // 2),
                )
            )

        bitmap = self._displayio.Bitmap(CELL_WIDTH, CELL_HEIGHT, 1)
        palette = self._displayio.Palette(1)
        palette[0] = ACTIVE
        self._highlight_grid = self._displayio.TileGrid(
            bitmap,
            pixel_shader=palette,
            x=HIGHLIGHT_HIDDEN_X,
            y=HIGHLIGHT_HIDDEN_Y,
        )
        root.append(self._highlight_grid)

    def _set_highlight(self, index):
        if self._highlight_grid is None:
            return
        if self._skip_highlight_update:
            return
        if index is None:
            self._highlight_grid.x = HIGHLIGHT_HIDDEN_X
            self._highlight_grid.y = HIGHLIGHT_HIDDEN_Y
            return
        x, y = cell_origin(index)
        self._highlight_grid.x = x
        self._highlight_grid.y = y

    def handle_press(self, index, *, now):
        self._debug_checkpoint_message("start", index)
        if self.active_cell is not None:
            self._debug_checkpoint_message("clear_prev", self.active_cell)
            if not self._skip_palette_write:
                self.cell_palettes[self.active_cell][0] = SURFACE

        self._debug_checkpoint_message("before_palette_write", index)
        if self._skip_palette_write:
            self._debug_checkpoint_message("palette_write_skipped", index)
        else:
            try:
                self.cell_palettes[index][0] = ACTIVE
                self._debug_checkpoint_message("after_palette_write", index)
            except Exception as exc:
                self._debug(f"lcd:handle_press:palette_error {type(exc).__name__}: {exc}")
                self.active_cell = index
                self.press_time = now
                return
        self._set_highlight(index)
        self.active_cell = index
        self._debug_checkpoint_message("after_active_cell", index)
        self.press_time = now
        self._debug_checkpoint_message("after_press_time", index)
        self._debug_checkpoint_message("done", index)

    def tick(self, *, now):
        if self.active_cell is None:
            return
        if (now - self.press_time) <= HIGHLIGHT_SEC:
            return
        if self._skip_highlight_clear:
            return
        if not self._skip_palette_write:
            self.cell_palettes[self.active_cell][0] = SURFACE
        self._set_highlight(None)
        self.active_cell = None


def initialize_lcd_ui(
    debug_hook=None,
    debug_checkpoint=None,
    skip_palette_write=False,
    skip_highlight_update=False,
    skip_highlight_clear=False,
):
    import board
    import busio
    import displayio
    import terminalio
    from fourwire import FourWire
    from adafruit_display_text import label
    import adafruit_ili9341
    from digitalio import DigitalInOut

    pin_clk = getattr(board, f"GP{LCD_PIN_NUMBERS['clk']}")
    pin_mosi = getattr(board, f"GP{LCD_PIN_NUMBERS['mosi']}")
    pin_cs = getattr(board, f"GP{LCD_PIN_NUMBERS['cs']}")
    pin_dc = getattr(board, f"GP{LCD_PIN_NUMBERS['dc']}")
    pin_rst = getattr(board, f"GP{LCD_PIN_NUMBERS['rst']}")

    displayio.release_displays()
    spi = busio.SPI(clock=pin_clk, MOSI=pin_mosi)
    dc = DigitalInOut(pin_dc)
    cs = DigitalInOut(pin_cs)
    rst = DigitalInOut(pin_rst)
    bus = build_display_bus(spi, dc, cs, rst, fourwire_class=FourWire)
    display = build_display(bus, display_driver_class=adafruit_ili9341.ILI9341)
    ui = SparkLcdUi(
        displayio_module=displayio,
        label_module=label,
        font=terminalio.FONT,
        debug_hook=debug_hook,
        debug_checkpoint=debug_checkpoint,
        skip_palette_write=skip_palette_write,
        skip_highlight_update=skip_highlight_update,
        skip_highlight_clear=skip_highlight_clear,
    )
    display.root_group = ui.root_group
    return ui
