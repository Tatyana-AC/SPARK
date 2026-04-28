import struct
import time

STAGE_LOG_PATH = "bridge_renderer_stage.txt"

try:
    from pico.pin_config import LCD_PIN_NUMBERS
except ImportError:
    from pin_config import LCD_PIN_NUMBERS

try:
    from pico.button_layout import ACTIONS as UI_ACTIONS, debug_label
except ImportError:
    from button_layout import ACTIONS as UI_ACTIONS, debug_label


BG = 0x1A1B26
SURFACE = 0x24283B
ACCENT = 0x7AA2F7
WHITE = 0xFFFFFF
ACTIVE = 0x3D4263

W = 320
H = 240
PAD = 8
GAP = 8
LAYOUT_H = 96
LAYOUT_TOP = H - LAYOUT_H
TOP_SPACER_W = 58
BOTTOM_SPACER_W = 58
SYNTHESIS_W = 121
SEARCH_W = 109
TOP_CELL_W = (W - 2 * PAD - TOP_SPACER_W - 2 * GAP) // 2
CELL_H = (LAYOUT_H - GAP) // 2
TOP_ROW_Y = LAYOUT_TOP
BOTTOM_ROW_Y = LAYOUT_TOP + CELL_H + GAP
_SPACER_ORIGINS = (
    (PAD, TOP_ROW_Y),
    (W - PAD - BOTTOM_SPACER_W, BOTTOM_ROW_Y),
)
_CELL_ORIGINS = (
    (PAD, BOTTOM_ROW_Y),
    (PAD + TOP_SPACER_W + GAP, TOP_ROW_Y),
    (PAD + SYNTHESIS_W + GAP, BOTTOM_ROW_Y),
    (PAD + TOP_SPACER_W + GAP + TOP_CELL_W + GAP, TOP_ROW_Y),
)
_CELL_WIDTHS = (
    SYNTHESIS_W,
    TOP_CELL_W,
    SEARCH_W,
    TOP_CELL_W,
)
_SPACER_WIDTHS = (
    TOP_SPACER_W,
    BOTTOM_SPACER_W,
)

DISPLAY_BAUDRATE = 24_000_000
DISPLAY_ROTATION = 180
FONT_SCALE = 2
CELL_LABEL_FONT_SCALE = 2
LOGO_TEXT = "SPARK"
LOGO_TITLE_SCALE = 4
LOGO_Y = 42
UPPER_MODE_TITLE = 3
UPPER_MODE_RELEASE = 2
UPPER_MODE_HISTORY = 1
UPPER_TEXT_SCALE = 2
UPPER_TEXT_X = 10
UPPER_HEADER_Y = 10
UPPER_BODY_Y = 34
FONT_WIDTH = 5
FONT_HEIGHT = 7
FONT_SPACING = 1
ACTIONS = UI_ACTIONS

_ILI9341_COLUMN_SET = 0x2A
_ILI9341_PAGE_SET = 0x2B
_ILI9341_RAM_WRITE = 0x2C
_ILI9341_MEMORY_ACCESS_CONTROL = 0x36

_INIT_SEQUENCE = (
    (0x01, None, 0.150),
    (0xEF, b"\x03\x80\x02", 0.0),
    (0xCF, b"\x00\xC1\x30", 0.0),
    (0xED, b"\x64\x03\x12\x81", 0.0),
    (0xE8, b"\x85\x00\x78", 0.0),
    (0xCB, b"\x39\x2C\x00\x34\x02", 0.0),
    (0xF7, b"\x20", 0.0),
    (0xEA, b"\x00\x00", 0.0),
    (0xC0, b"\x23", 0.0),
    (0xC1, b"\x10", 0.0),
    (0xC5, b"\x3E\x28", 0.0),
    (0xC7, b"\x86", 0.0),
    (0x3A, b"\x55", 0.0),
    (0xB1, b"\x00\x18", 0.0),
    (0xB6, b"\x08\x82\x27", 0.0),
    (0xF2, b"\x00", 0.0),
    (0x26, b"\x01", 0.0),
    (0xE0, b"\x0F\x31\x2B\x0C\x0E\x08\x4E\xF1\x37\x07\x10\x03\x0E\x09\x00", 0.0),
    (0xE1, b"\x00\x0E\x14\x03\x11\x07\x31\xC1\x48\x08\x0F\x0C\x31\x36\x0F", 0.0),
    (0x11, None, 0.120),
    (0x29, None, 0.120),
)

_MADCTL_BY_ROTATION = {
    0: 0x48,
    90: 0x28,
    180: 0xE8,
    270: 0x88,
}

_FONT_GLYPHS = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
}


def _debug_stage(message):
    try:
        from pico.pico_debug import dbg
    except Exception:
        try:
            from pico_debug import dbg
        except Exception:
            return

    try:
        dbg(f"lcd_renderer:{message}")
    except Exception:
        return


def cell_origin(index):
    return _CELL_ORIGINS[index]


def spacer_origin(index):
    return _SPACER_ORIGINS[index]


def cell_width(index):
    return _CELL_WIDTHS[index]


def spacer_width(index):
    return _SPACER_WIDTHS[index]


def text_width(text, *, scale=FONT_SCALE):
    if not text:
        return 0
    char_step = (FONT_WIDTH + FONT_SPACING) * scale
    return (len(text) * char_step) - (FONT_SPACING * scale)


def cell_label_position(index, text, *, scale=CELL_LABEL_FONT_SCALE):
    x, y = cell_origin(index)
    width = cell_width(index)
    label_width = text_width(text, scale=scale)
    label_height = FONT_HEIGHT * scale
    return (
        x + max(0, (width - label_width) // 2),
        y + max(0, (CELL_H - label_height) // 2),
    )


def logo_title_position():
    return ((W - text_width(LOGO_TEXT, scale=LOGO_TITLE_SCALE)) // 2, LOGO_Y)


def upper_visible_line_count():
    return max(1, (LAYOUT_TOP - UPPER_BODY_Y - PAD) // ((FONT_HEIGHT + 1) * UPPER_TEXT_SCALE))


def _color565(color):
    red = (color >> 16) & 0xFF
    green = (color >> 8) & 0xFF
    blue = color & 0xFF
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


def _record_stage(stage):
    try:
        import storage

        try:
            storage.remount("/", readonly=False)
        except Exception:
            pass

        with open(STAGE_LOG_PATH, "w") as handle:
            handle.write(f"stage={stage}\n")
    except Exception:
        return


class SpiLcdRenderer:
    def __init__(self, *, target):
        self._target = target
        self._idle_drawn = False
        self._has_blit = hasattr(target, "blit_pixels")
        self._debug_sender = None
        self._upper_mode = UPPER_MODE_TITLE
        self._upper_content = {
            "release": "No released text yet...",
            "history": "No history yet",
        }
        self._upper_scroll_offsets = {"release": 0, "history": 0}

    def set_debug_sender(self, sender):
        self._debug_sender = sender

    def _emit_debug(self, message):
        if self._debug_sender is None:
            return
        self._debug_sender(message)

    def draw_idle_layout(self):
        if self._idle_drawn:
            return

        _record_stage("renderer:draw_idle:start")
        self._target.fill(BG)
        self._draw_upper_panel()
        _record_stage("renderer:draw_idle:after-fill")
        if self._has_blit:
            for index in range(2):
                x, y = spacer_origin(index)
                self._target.blit_pixels(x, y, spacer_width(index), CELL_H, _build_spacer_pixels(index))
                _record_stage(f"renderer:draw_idle:after-spacer:{index}")
            for index in range(4):
                x, y = cell_origin(index)
                self._target.blit_pixels(x, y, cell_width(index), CELL_H, _build_cell_pixels(index, SURFACE))
                _record_stage(f"renderer:draw_idle:after-cell:{index}")
        else:
            for index in range(2):
                self._draw_spacer(index)
            for index in range(4):
                self.draw_idle_cell(index)

        self._idle_drawn = True
        _record_stage("renderer:draw_idle:done")

    def draw_pressed_cell(self, index):
        self._emit_debug(debug_label("render_press", index))
        self._draw_cell(index, ACTIVE)
        self._emit_debug(debug_label("render_press_done", index))

    def draw_idle_cell(self, index):
        self._draw_cell(index, SURFACE)

    def set_upper_mode(self, mode):
        if mode not in (UPPER_MODE_HISTORY, UPPER_MODE_RELEASE, UPPER_MODE_TITLE):
            return
        self._upper_mode = mode
        mode_name = self._upper_mode_name()
        if mode_name is not None:
            self._upper_scroll_offsets[mode_name] = 0
        self._draw_upper_panel()

    def set_upper_content(self, mode, text):
        if mode not in self._upper_content:
            return
        self._upper_content[mode] = str(text or "")
        self._upper_scroll_offsets[mode] = 0
        if self._upper_mode_name() == mode:
            self._draw_upper_panel()

    def scroll_upper_content(self, delta):
        mode_name = self._upper_mode_name()
        if mode_name is None:
            return
        lines = self._wrapped_upper_lines(self._upper_content.get(mode_name, ""))
        max_offset = max(0, len(lines) - upper_visible_line_count())
        next_offset = self._upper_scroll_offsets.get(mode_name, 0) + int(delta)
        self._upper_scroll_offsets[mode_name] = min(max_offset, max(0, next_offset))
        self._draw_upper_panel()

    def _upper_mode_name(self):
        if self._upper_mode == UPPER_MODE_RELEASE:
            return "release"
        if self._upper_mode == UPPER_MODE_HISTORY:
            return "history"
        return None

    def _draw_upper_panel(self):
        self._target.fill_rect(0, 0, W, LAYOUT_TOP, BG)
        if self._upper_mode == UPPER_MODE_TITLE:
            self._draw_static_branding()
            return
        mode_name = self._upper_mode_name()
        if mode_name == "release":
            self._draw_upper_text_panel("RELEASE OUTPUT", self._upper_content.get(mode_name, ""))
        elif mode_name == "history":
            self._draw_upper_text_panel("SESSION HISTORY", self._upper_content.get(mode_name, ""))

    def _draw_upper_text_panel(self, header, text):
        self._target.draw_text(
            UPPER_TEXT_X,
            UPPER_HEADER_Y,
            self._display_text(header),
            ACCENT,
            scale=UPPER_TEXT_SCALE,
            background_color=BG,
        )
        lines = self._wrapped_upper_lines(text)
        mode_name = self._upper_mode_name()
        offset = self._upper_scroll_offsets.get(mode_name, 0) if mode_name else 0
        visible_count = upper_visible_line_count()
        line_step = (FONT_HEIGHT + 1) * UPPER_TEXT_SCALE
        for index, line in enumerate(lines[offset : offset + visible_count]):
            self._target.draw_text(
                UPPER_TEXT_X,
                UPPER_BODY_Y + (index * line_step),
                self._display_text(line),
                WHITE,
                scale=UPPER_TEXT_SCALE,
                background_color=BG,
            )
        if len(lines) > visible_count:
            marker = f"{offset + 1}/{max(1, len(lines) - visible_count + 1)}"
            self._target.draw_text(
                W - text_width(marker, scale=UPPER_TEXT_SCALE) - PAD,
                UPPER_HEADER_Y,
                marker,
                WHITE,
                scale=UPPER_TEXT_SCALE,
                background_color=BG,
            )

    def _wrapped_upper_lines(self, text):
        max_chars = max(1, (W - (2 * UPPER_TEXT_X)) // ((FONT_WIDTH + FONT_SPACING) * UPPER_TEXT_SCALE))
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = []
        for raw_line in normalized.split("\n"):
            words = raw_line.split(" ")
            current = ""
            for word in words:
                if not word:
                    continue
                if len(word) > max_chars:
                    if current:
                        lines.append(current)
                        current = ""
                    for start in range(0, len(word), max_chars):
                        lines.append(word[start : start + max_chars])
                    continue
                candidate = word if not current else f"{current} {word}"
                if len(candidate) <= max_chars:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            if current:
                lines.append(current)
            elif raw_line == "":
                lines.append("")
        return lines or [""]

    def _display_text(self, text):
        return "".join(char if char in _FONT_GLYPHS else " " for char in str(text).upper())

    def _draw_spacer(self, index):
        x, y = spacer_origin(index)
        self._draw_bordered_region(x, y, spacer_width(index), CELL_H, SURFACE)

    def _draw_cell(self, index, fill_color):
        if index < 0 or index > 3:
            raise IndexError(f"invalid cell index: {index}")

        x, y = cell_origin(index)
        self._draw_bordered_region(x, y, cell_width(index), CELL_H, fill_color)
        text_x, text_y = cell_label_position(index, ACTIONS[index])
        self._target.draw_text(
            text_x,
            text_y,
            ACTIONS[index],
            WHITE,
            scale=CELL_LABEL_FONT_SCALE,
            background_color=fill_color,
        )

    def _draw_static_branding(self):
        title_x, title_y = logo_title_position()
        title_width = text_width(LOGO_TEXT, scale=LOGO_TITLE_SCALE)
        title_height = FONT_HEIGHT * LOGO_TITLE_SCALE
        center_x = W // 2
        underline_y = title_y + title_height + 14
        spark_y = title_y - 16

        self._target.fill_rect(center_x - 48, spark_y + 8, 96, 2, ACCENT)
        self._target.fill_rect(center_x - 12, spark_y, 24, 2, WHITE)
        self._target.fill_rect(center_x - 1, spark_y - 7, 2, 14, ACCENT)
        self._target.draw_text(
            title_x,
            title_y,
            LOGO_TEXT,
            WHITE,
            scale=LOGO_TITLE_SCALE,
            background_color=BG,
        )
        self._target.fill_rect(title_x - 6, underline_y, title_width + 12, 2, ACCENT)
        self._target.fill_rect(center_x - 18, underline_y + 7, 36, 2, WHITE)

    def _draw_bordered_region(self, x, y, width, height, fill_color):
        self._target.fill_rect(x, y, width, height, fill_color)
        self._target.fill_rect(x, y, width, 2, ACCENT)
        self._target.fill_rect(x, y + height - 2, width, 2, ACCENT)
        self._target.fill_rect(x, y, 2, height, ACCENT)
        self._target.fill_rect(x + width - 2, y, 2, height, ACCENT)


class Ili9341SpiTarget:
    def __init__(self, spi, dc, cs, rst, *, width=W, height=H, rotation=DISPLAY_ROTATION, baudrate=DISPLAY_BAUDRATE):
        if rotation not in _MADCTL_BY_ROTATION:
            raise ValueError(f"unsupported rotation: {rotation}")

        self.width = width
        self.height = height
        self._spi = spi
        self._dc = dc
        self._cs = cs
        self._rst = rst
        self._baudrate = baudrate
        self._chunk_pixels = 256
        _record_stage("target:init:configure-pins")
        self._configure_pins()
        _record_stage("target:init:reset")
        self._reset()
        _record_stage("target:init:panel")
        self._initialize_panel(rotation=rotation)
        _record_stage("target:init:done")

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def blit_pixels(self, x, y, width, height, pixel_bytes):
        if not pixel_bytes:
            return

        self._write_window(x, y, width, height)
        byte_chunk_size = self._chunk_pixels * 2
        for offset in range(0, len(pixel_bytes), byte_chunk_size):
            self._write(data=pixel_bytes[offset : offset + byte_chunk_size])

    def fill_rect(self, x, y, width, height, color):
        x = min(self.width - 1, max(0, x))
        y = min(self.height - 1, max(0, y))
        width = min(self.width - x, max(1, width))
        height = min(self.height - y, max(1, height))

        pixel_count = width * height
        color_565 = _color565(color)
        pixel_bytes = bytes((color_565 >> 8, color_565 & 0xFF))
        chunk = pixel_bytes * self._chunk_pixels

        self._write_window(x, y, width, height)

        while pixel_count >= self._chunk_pixels:
            self._write(data=chunk)
            pixel_count -= self._chunk_pixels

        if pixel_count:
            self._write(data=pixel_bytes * pixel_count)

    def draw_text(self, x, y, text, color, *, scale, background_color=None):
        if not text:
            return

        width = text_width(text, scale=scale)
        height = FONT_HEIGHT * scale
        foreground = _color565(color)
        background = _color565(background_color if background_color is not None else BG)
        advance = (FONT_WIDTH + FONT_SPACING) * scale
        pixel_bytes = bytearray(width * height * 2)

        for row in range(height):
            row_offset = row * width * 2
            for column in range(width):
                color_565 = background
                char_index = column // advance
                column_in_advance = column % advance
                if char_index < len(text) and column_in_advance < (FONT_WIDTH * scale):
                    glyph = _FONT_GLYPHS.get(text[char_index], _FONT_GLYPHS[" "])
                    glyph_column = column_in_advance // scale
                    glyph_row = row // scale
                    if glyph[glyph_row][glyph_column] == "1":
                        color_565 = foreground
                pixel_index = row_offset + (column * 2)
                pixel_bytes[pixel_index] = (color_565 >> 8) & 0xFF
                pixel_bytes[pixel_index + 1] = color_565 & 0xFF

        self._write_window(x, y, width, height)
        byte_chunk_size = self._chunk_pixels * 2
        for offset in range(0, len(pixel_bytes), byte_chunk_size):
            self._write(data=bytes(pixel_bytes[offset : offset + byte_chunk_size]))

    def _write_window(self, x, y, width, height):
        self._write(command=_ILI9341_COLUMN_SET, data=struct.pack(">HH", x, x + width - 1))
        self._write(command=_ILI9341_PAGE_SET, data=struct.pack(">HH", y, y + height - 1))
        self._write(command=_ILI9341_RAM_WRITE)

    def _configure_pins(self):
        self._dc.switch_to_output(value=False)
        self._cs.switch_to_output(value=True)
        self._rst.switch_to_output(value=True)

    def _reset(self):
        self._rst.value = False
        time.sleep(0.050)
        self._rst.value = True
        time.sleep(0.050)

    def _initialize_panel(self, *, rotation):
        for command, data, delay_s in _INIT_SEQUENCE:
            self._write(command=command, data=data)
            if delay_s:
                time.sleep(delay_s)

        self._write(command=_ILI9341_MEMORY_ACCESS_CONTROL, data=bytes((_MADCTL_BY_ROTATION[rotation],)))

    def _write(self, *, command=None, data=None):
        while not self._spi.try_lock():
            pass

        self._spi.configure(baudrate=self._baudrate, polarity=0, phase=0)

        try:
            self._cs.value = False
            if command is not None:
                self._dc.value = False
                self._spi.write(bytes((command,)))
            if data is not None:
                self._dc.value = True
                self._spi.write(data)
        finally:
            self._cs.value = True
            self._spi.unlock()


def initialize_bridge_renderer():
    import board
    import busio
    from digitalio import DigitalInOut

    def board_pin(number):
        return getattr(board, f"GP{number}")

    _debug_stage("init:start")
    spi = busio.SPI(clock=board_pin(LCD_PIN_NUMBERS["clk"]), MOSI=board_pin(LCD_PIN_NUMBERS["mosi"]))
    _debug_stage("init:spi")
    _record_stage("bridge-renderer:init:spi")
    dc = DigitalInOut(board_pin(LCD_PIN_NUMBERS["dc"]))
    cs = DigitalInOut(board_pin(LCD_PIN_NUMBERS["cs"]))
    rst = DigitalInOut(board_pin(LCD_PIN_NUMBERS["rst"]))
    _debug_stage("init:pins")
    _record_stage("bridge-renderer:init:pins")
    target = Ili9341SpiTarget(spi, dc, cs, rst)
    _debug_stage("init:target")
    _record_stage("bridge-renderer:init:target")
    renderer = SpiLcdRenderer(target=target)
    _debug_stage("init:renderer")
    _record_stage("bridge-renderer:init:renderer")
    renderer.draw_idle_layout()
    _debug_stage("init:idle-layout")
    _record_stage("bridge-renderer:init:idle-layout")
    return renderer


def _build_spacer_pixels(index):
    return _build_region_pixels(
        width=spacer_width(index),
        height=CELL_H,
        background_color=SURFACE,
        border_color=ACCENT,
        border_top=True,
        border_bottom=True,
        border_left=True,
        border_right=True,
        text="",
        text_color=WHITE,
        text_position=(0, 0),
    )


def _build_cell_pixels(index, fill_color):
    width = cell_width(index)
    return _build_region_pixels(
        width=width,
        height=CELL_H,
        background_color=fill_color,
        border_color=ACCENT,
        border_bottom=True,
        border_top=True,
        border_left=True,
        border_right=True,
        text=ACTIONS[index],
        text_color=WHITE,
        text_scale=CELL_LABEL_FONT_SCALE,
        text_position=(
            cell_label_position(index, ACTIONS[index])[0] - cell_origin(index)[0],
            cell_label_position(index, ACTIONS[index])[1] - cell_origin(index)[1],
        ),
    )


def _build_region_pixels(
    *,
    width,
    height,
    background_color,
    border_color,
    text,
    text_color,
    text_scale=FONT_SCALE,
    text_position,
    border_top=False,
    border_bottom=False,
    border_left=False,
    border_right=False,
):
    background = _color565(background_color)
    border = _color565(border_color)
    foreground = _color565(text_color)
    pixels = bytearray(width * height * 2)

    for y in range(height):
        for x in range(width):
            color_565 = background
            if border_top and y < 2:
                color_565 = border
            elif border_bottom and y >= (height - 2):
                color_565 = border
            elif border_left and x < 2:
                color_565 = border
            elif border_right and x >= (width - 2):
                color_565 = border

            pixel_index = ((y * width) + x) * 2
            pixels[pixel_index] = (color_565 >> 8) & 0xFF
            pixels[pixel_index + 1] = color_565 & 0xFF

    _overlay_text(pixels, width, height, text, foreground, text_position, scale=text_scale)
    return bytes(pixels)


def _overlay_text(pixel_bytes, width, height, text, foreground, text_position, *, scale=FONT_SCALE):
    text_x, text_y = text_position
    advance = (FONT_WIDTH + FONT_SPACING) * scale
    for char_index, char in enumerate(text):
        glyph = _FONT_GLYPHS.get(char, _FONT_GLYPHS[" "])
        base_x = text_x + (char_index * advance)
        for row_index, row_bits in enumerate(glyph):
            for column_index, bit in enumerate(row_bits):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        px = base_x + (column_index * scale) + dx
                        py = text_y + (row_index * scale) + dy
                        if px < 0 or py < 0 or px >= width or py >= height:
                            continue
                        pixel_index = ((py * width) + px) * 2
                        pixel_bytes[pixel_index] = (foreground >> 8) & 0xFF
                        pixel_bytes[pixel_index + 1] = foreground & 0xFF
