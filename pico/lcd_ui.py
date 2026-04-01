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
    def __init__(self, *, displayio_module, label_module, font):
        self._displayio = displayio_module
        self._label = label_module
        self._font = font
        self.root_group = displayio_module.Group()
        self.cell_palettes = []
        self.active_cell = None
        self.press_time = 0.0
        self._build_idle_screen()

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

    def handle_press(self, index, *, now):
        if self.active_cell is not None:
            self.cell_palettes[self.active_cell][0] = SURFACE

        self.cell_palettes[index][0] = ACTIVE
        self.active_cell = index
        self.press_time = now

    def tick(self, *, now):
        if self.active_cell is None:
            return
        if (now - self.press_time) <= HIGHLIGHT_SEC:
            return
        self.cell_palettes[self.active_cell][0] = SURFACE
        self.active_cell = None


def initialize_lcd_ui():
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
    ui = SparkLcdUi(displayio_module=displayio, label_module=label, font=terminalio.FONT)
    display.root_group = ui.root_group
    return ui
