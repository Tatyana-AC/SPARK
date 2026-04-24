import importlib
import importlib.util
import sys
import types
import unittest
from unittest import mock


def _load_module(name):
    spec = importlib.util.find_spec(name)
    assert spec is not None, f"missing module: {name}"
    return importlib.import_module(name)


class _FakePalette:
    write_count = 0

    def __init__(self, size):
        self._values = [None] * size

    def __getitem__(self, index):
        return self._values[index]

    def __setitem__(self, index, value):
        type(self).write_count += 1
        self._values[index] = value


class _FakeBitmap:
    def __init__(self, width, height, colors):
        self.width = width
        self.height = height
        self.colors = colors


class _FakeTileGrid:
    def __init__(self, bitmap, *, pixel_shader, x, y):
        self.bitmap = bitmap
        self.pixel_shader = pixel_shader
        self.x = x
        self.y = y
        self.hidden_write_count = 0
        self._hidden = False

    @property
    def hidden(self):
        return self._hidden

    @hidden.setter
    def hidden(self, value):
        self.hidden_write_count += 1
        self._hidden = value


class _FakeGroup(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.hidden = kwargs.get("hidden", False)
        self.x = kwargs.get("x", 0)
        self.y = kwargs.get("y", 0)


class _FakeLabel:
    def __init__(self, font, **kwargs):
        self.font = font
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeDisplayioModule:
    Bitmap = _FakeBitmap
    Palette = _FakePalette
    TileGrid = _FakeTileGrid
    Group = _FakeGroup


class _FakeLabelModule:
    @staticmethod
    def Label(font, **kwargs):
        return _FakeLabel(font, **kwargs)


def _make_ui(lcd_ui):
    _FakePalette.write_count = 0
    return lcd_ui.SparkLcdUi(
        displayio_module=_FakeDisplayioModule,
        label_module=_FakeLabelModule,
        font="font",
    )


def _snapshot_tree(node):
    if isinstance(node, _FakeGroup):
        return (
            id(node),
            node.x,
            node.y,
            node.hidden,
            tuple(_snapshot_tree(child) for child in node),
        )
    return id(node)


def _pressed_overlay_visibility(ui):
    return [not cell.pressed_overlay.hidden for cell in ui.cell_views]


class PicoPinConfigTests(unittest.TestCase):
    def test_pin_config_exposes_expected_button_and_lcd_numbers(self):
        pin_config = _load_module("pico.pin_config")

        self.assertEqual(pin_config.BUTTON_PIN_NUMBERS, (2, 3, 4, 5))
        self.assertEqual(
            pin_config.LCD_PIN_NUMBERS,
            {"clk": 18, "mosi": 19, "cs": 17, "dc": 16, "rst": 20},
        )


class PicoLcdUiTests(unittest.TestCase):
    def test_build_display_helpers_use_standalone_rotation_and_dimensions(self):
        lcd_ui = _load_module("pico.lcd_ui")
        bus_call = {}
        display_call = {}

        def fake_fourwire(spi, *, command, chip_select, reset, baudrate):
            bus_call.update(
                spi=spi,
                command=command,
                chip_select=chip_select,
                reset=reset,
                baudrate=baudrate,
            )
            return "bus"

        def fake_display_driver(bus, *, width, height, rotation):
            display_call.update(bus=bus, width=width, height=height, rotation=rotation)
            return "display"

        bus = lcd_ui.build_display_bus("spi", "dc", "cs", "rst", fourwire_class=fake_fourwire)
        display = lcd_ui.build_display("bus", display_driver_class=fake_display_driver)

        self.assertEqual(bus, "bus")
        self.assertEqual(display, "display")
        self.assertEqual(
            bus_call,
            {
                "spi": "spi",
                "command": "dc",
                "chip_select": "cs",
                "reset": "rst",
                "baudrate": 24_000_000,
            },
        )
        self.assertEqual(
            display_call,
            {"bus": "bus", "width": 320, "height": 240, "rotation": 180},
        )

    def test_ui_builds_staggered_bottom_button_layout_without_header(self):
        lcd_ui = _load_module("pico.lcd_ui")
        ui = _make_ui(lcd_ui)

        self.assertEqual(lcd_ui.ACTIONS, ("SYNTHESIS", "REFORMAT", "SEARCH", "RESPOND"))
        self.assertEqual(lcd_ui.cell_origin(0), (8, 196))
        self.assertEqual(lcd_ui.cell_origin(1), (74, 144))
        self.assertEqual(lcd_ui.cell_origin(2), (137, 196))
        self.assertEqual(lcd_ui.cell_origin(3), (197, 144))
        self.assertEqual(lcd_ui.cell_width(0), 121)
        self.assertEqual(lcd_ui.cell_width(1), 115)
        self.assertEqual(lcd_ui.cell_width(2), 109)
        self.assertEqual(lcd_ui.cell_width(3), 115)
        self.assertEqual(lcd_ui.CELL_H, 44)
        self.assertEqual(lcd_ui.spacer_width(0), 58)
        self.assertEqual(lcd_ui.spacer_width(1), 58)
        self.assertEqual(lcd_ui.LAYOUT_TOP, 144)
        self.assertEqual(len(ui.cell_views), 4)
        self.assertEqual(len(ui.root_group), 7)
        self.assertEqual([cell.name for cell in ui.cell_views], ["PB1", "PB2", "PB3", "PB4"])
        self.assertEqual([cell.label.text for cell in ui.cell_views], list(lcd_ui.ACTIONS))
        self.assertEqual([(cell.group.x, cell.group.y) for cell in ui.cell_views], [lcd_ui.cell_origin(i) for i in range(4)])
        self.assertEqual([len(cell.group) for cell in ui.cell_views], [7, 7, 7, 7])
        self.assertEqual(_pressed_overlay_visibility(ui), [False, False, False, False])

    def test_ui_press_and_tick_match_existing_highlight_timeout_without_tree_or_palette_mutation(self):
        lcd_ui = _load_module("pico.lcd_ui")
        ui = _make_ui(lcd_ui)
        initial_tree = _snapshot_tree(ui.root_group)
        initial_palette_writes = _FakePalette.write_count

        ui.handle_press(1, now=10.0)
        self.assertEqual(ui.active_cell, 1)
        self.assertEqual(ui.press_time, 10.0)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, True, False, False])
        self.assertEqual(_snapshot_tree(ui.root_group), initial_tree)
        self.assertEqual(_FakePalette.write_count, initial_palette_writes)

        ui.tick(now=10.39)
        self.assertEqual(ui.active_cell, 1)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, True, False, False])
        self.assertEqual(_snapshot_tree(ui.root_group), initial_tree)
        self.assertEqual(_FakePalette.write_count, initial_palette_writes)

        ui.handle_press(3, now=10.5)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, False, False, True])
        self.assertEqual(_snapshot_tree(ui.root_group), initial_tree)
        self.assertEqual(_FakePalette.write_count, initial_palette_writes)

        ui.tick(now=10.91)
        self.assertIsNone(ui.active_cell)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, False, False, False])
        self.assertEqual(_snapshot_tree(ui.root_group), initial_tree)
        self.assertEqual(_FakePalette.write_count, initial_palette_writes)

    def test_ui_repress_refreshes_timeout_without_rebuilding_the_tree(self):
        lcd_ui = _load_module("pico.lcd_ui")
        ui = _make_ui(lcd_ui)
        initial_tree = _snapshot_tree(ui.root_group)
        initial_palette_writes = _FakePalette.write_count

        ui.handle_press(2, now=4.0)
        ui.handle_press(2, now=4.2)

        self.assertEqual(ui.active_cell, 2)
        self.assertEqual(ui.press_time, 4.2)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, False, True, False])
        self.assertEqual(_snapshot_tree(ui.root_group), initial_tree)
        self.assertEqual(_FakePalette.write_count, initial_palette_writes)

    def test_ui_same_cell_repress_does_not_rewrite_overlay_visibility(self):
        lcd_ui = _load_module("pico.lcd_ui")
        ui = _make_ui(lcd_ui)
        overlay = ui.cell_views[2].pressed_overlay

        ui.handle_press(2, now=4.0)
        writes_after_first_press = overlay.hidden_write_count

        ui.handle_press(2, now=4.2)

        self.assertEqual(overlay.hidden_write_count, writes_after_first_press)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, False, True, False])
        self.assertEqual(ui.press_time, 4.2)

        ui.tick(now=4.5)
        self.assertEqual(ui.active_cell, 2)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, False, True, False])

        ui.tick(now=4.61)
        self.assertIsNone(ui.active_cell)
        self.assertEqual(_pressed_overlay_visibility(ui), [False, False, False, False])

    def test_initialize_lcd_ui_assigns_root_group_with_shared_rotation_and_pins(self):
        lcd_ui = _load_module("pico.lcd_ui")
        display_instances = []

        class _FakeDisplay:
            def __init__(self, bus, *, width, height, rotation):
                self.bus = bus
                self.width = width
                self.height = height
                self.rotation = rotation
                self.root_group = None
                display_instances.append(self)

        fake_board = types.SimpleNamespace(GP16="GP16", GP17="GP17", GP18="GP18", GP19="GP19", GP20="GP20")
        fake_busio = types.SimpleNamespace(SPI=lambda *, clock, MOSI: (clock, MOSI))
        fake_displayio = types.SimpleNamespace(
            release_displays=lambda: None,
            Bitmap=_FakeBitmap,
            Palette=_FakePalette,
            TileGrid=_FakeTileGrid,
            Group=_FakeGroup,
        )
        fake_terminalio = types.SimpleNamespace(FONT="font")
        fake_label_module = types.SimpleNamespace(Label=lambda *args, **kwargs: {"font": args[0], **kwargs})
        fake_display_text = types.SimpleNamespace(label=fake_label_module)
        fake_digitalio = types.SimpleNamespace(DigitalInOut=lambda pin: f"dio:{pin}")
        fake_ili9341 = types.SimpleNamespace(ILI9341=_FakeDisplay)

        fourwire_calls = []

        def _fake_fourwire(spi, *, command, chip_select, reset, baudrate):
            fourwire_calls.append(
                {
                    "spi": spi,
                    "command": command,
                    "chip_select": chip_select,
                    "reset": reset,
                    "baudrate": baudrate,
                }
            )
            return "bus"

        fake_fourwire = types.SimpleNamespace(FourWire=_fake_fourwire)

        fake_modules = {
            "board": fake_board,
            "busio": fake_busio,
            "displayio": fake_displayio,
            "terminalio": fake_terminalio,
            "adafruit_display_text": fake_display_text,
            "adafruit_display_text.label": fake_label_module,
            "digitalio": fake_digitalio,
            "adafruit_ili9341": fake_ili9341,
            "fourwire": fake_fourwire,
        }

        with mock.patch.dict(sys.modules, fake_modules, clear=False):
            ui = lcd_ui.initialize_lcd_ui()

        self.assertEqual(len(fourwire_calls), 1)
        self.assertEqual(
            fourwire_calls[0],
            {
                "spi": ("GP18", "GP19"),
                "command": "dio:GP16",
                "chip_select": "dio:GP17",
                "reset": "dio:GP20",
                "baudrate": 24_000_000,
            },
        )
        self.assertEqual(len(display_instances), 1)
        self.assertEqual(display_instances[0].rotation, 180)
        self.assertIs(display_instances[0].root_group, ui.root_group)

    def test_initialize_lcd_ui_bridge_mode_routes_to_spi_renderer_backend(self):
        lcd_ui = _load_module("pico.lcd_ui")
        renderer_calls = []

        class _FakeBridgeRenderer:
            def draw_pressed_cell(self, index):
                renderer_calls.append(("pressed", index))

            def draw_idle_cell(self, index):
                renderer_calls.append(("idle", index))

        fake_renderer_module = types.SimpleNamespace(
            initialize_bridge_renderer=lambda: _FakeBridgeRenderer()
        )

        with mock.patch.dict(
            sys.modules,
            {
                "pico.lcd_renderer_spi": fake_renderer_module,
                "lcd_renderer_spi": fake_renderer_module,
            },
            clear=False,
        ):
            ui = lcd_ui.initialize_lcd_ui(mode="bridge")

        ui.handle_press(1, now=10.0)
        ui.handle_press(3, now=10.1)
        ui.tick(now=10.55)

        self.assertEqual(renderer_calls, [("pressed", 1), ("idle", 1), ("pressed", 3), ("idle", 3)])
        self.assertIsNone(ui.active_cell)
        self.assertEqual(ui.press_time, 10.1)

    def test_lcd_ui_bridge_mode_selects_non_displayio_renderer(self):
        lcd_ui = _load_module("pico.lcd_ui")
        renderer_calls = []
        fake_renderer = object()

        fake_renderer_module = types.SimpleNamespace(
            initialize_bridge_renderer=lambda: renderer_calls.append("init") or fake_renderer
        )

        with mock.patch.object(lcd_ui, "build_display_bus", side_effect=AssertionError("standalone bus used")):
            with mock.patch.object(lcd_ui, "build_display", side_effect=AssertionError("standalone display used")):
                with mock.patch.dict(
                    sys.modules,
                    {
                        "pico.lcd_renderer_spi": fake_renderer_module,
                        "lcd_renderer_spi": fake_renderer_module,
                    },
                    clear=False,
                ):
                    ui = lcd_ui.initialize_lcd_ui(mode="bridge")

        self.assertEqual(renderer_calls, ["init"])
        self.assertIs(ui._renderer, fake_renderer)

    def test_initialize_lcd_ui_bridge_mode_ignores_stage_led_failures(self):
        lcd_ui = _load_module("pico.lcd_ui")
        fake_renderer = object()

        fake_board = types.SimpleNamespace(LED="LED")

        def _raising_digital_in_out(_pin):
            raise RuntimeError("led unavailable")

        fake_digitalio = types.SimpleNamespace(DigitalInOut=_raising_digital_in_out)
        fake_renderer_module = types.SimpleNamespace(initialize_bridge_renderer=lambda: fake_renderer)

        with mock.patch.dict(
            sys.modules,
            {
                "board": fake_board,
                "digitalio": fake_digitalio,
                "pico.lcd_renderer_spi": fake_renderer_module,
                "lcd_renderer_spi": fake_renderer_module,
            },
            clear=False,
        ):
            ui = lcd_ui.initialize_lcd_ui(mode="bridge")

        self.assertIs(ui._renderer, fake_renderer)

    def test_initialize_lcd_ui_bridge_mode_same_cell_repress_does_not_redraw(self):
        lcd_ui = _load_module("pico.lcd_ui")
        renderer_calls = []

        class _FakeBridgeRenderer:
            def draw_pressed_cell(self, index):
                renderer_calls.append(("pressed", index))

            def draw_idle_cell(self, index):
                renderer_calls.append(("idle", index))

        fake_renderer_module = types.SimpleNamespace(
            initialize_bridge_renderer=lambda: _FakeBridgeRenderer()
        )

        with mock.patch.dict(
            sys.modules,
            {
                "pico.lcd_renderer_spi": fake_renderer_module,
                "lcd_renderer_spi": fake_renderer_module,
            },
            clear=False,
        ):
            ui = lcd_ui.initialize_lcd_ui(mode="bridge")

        ui.handle_press(1, now=10.0)
        ui.handle_press(1, now=10.1)
        ui.tick(now=10.55)

        self.assertEqual(renderer_calls, [("pressed", 1), ("idle", 1)])
        self.assertIsNone(ui.active_cell)
        self.assertEqual(ui.press_time, 10.1)

    def test_initialize_lcd_ui_bridge_mode_emits_renderer_stage_debug(self):
        lcd_ui = _load_module("pico.lcd_ui")
        renderer_calls = []
        debug_calls = []

        class _FakeBridgeRenderer:
            def draw_pressed_cell(self, index):
                renderer_calls.append(("pressed", index))

            def draw_idle_cell(self, index):
                renderer_calls.append(("idle", index))

        fake_renderer_module = types.SimpleNamespace(
            initialize_bridge_renderer=lambda: _FakeBridgeRenderer()
        )

        with mock.patch.dict(
            sys.modules,
            {
                "pico.lcd_renderer_spi": fake_renderer_module,
                "lcd_renderer_spi": fake_renderer_module,
            },
            clear=False,
        ):
            ui = lcd_ui.initialize_lcd_ui(mode="bridge")

        ui.set_debug_sender(debug_calls.append)
        ui.handle_press(1, now=10.0)
        ui.handle_press(3, now=10.1)

        self.assertEqual(
            debug_calls,
            [
                "draw_press:2",
                "press_done:2",
                "idle_prev:2",
                "draw_press:4",
                "press_done:4",
            ],
        )
        self.assertEqual(renderer_calls, [("pressed", 1), ("idle", 1), ("pressed", 3)])


if __name__ == "__main__":
    unittest.main()
