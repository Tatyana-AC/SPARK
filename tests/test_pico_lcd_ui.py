import unittest


class FakeBitmap:
    def __init__(self, width, height, colors):
        self.width = width
        self.height = height
        self.colors = colors


class FakePalette(list):
    def __init__(self, size):
        super().__init__([None] * size)


class FakeTileGrid:
    def __init__(self, bitmap, *, pixel_shader, x, y):
        self.bitmap = bitmap
        self.pixel_shader = pixel_shader
        self.x = x
        self.y = y


class FakeGroup(list):
    pass


class FakeDisplayIOModule:
    Bitmap = FakeBitmap
    Palette = FakePalette
    TileGrid = FakeTileGrid
    Group = FakeGroup


class FakeLabel:
    def __init__(self, font, **kwargs):
        self.font = font
        self.kwargs = kwargs


class FakeLabelModule:
    @staticmethod
    def Label(font, **kwargs):
        return FakeLabel(font, **kwargs)


class BadCellPalette(list):
    def __init__(self):
        super().__init__([None])

    def __setitem__(self, key, value):
        raise RuntimeError("palette write failed")


class FakeFourWire:
    def __init__(self, spi, **kwargs):
        self.spi = spi
        self.kwargs = kwargs


class FakeDisplayDriver:
    def __init__(self, bus, **kwargs):
        self.bus = bus
        self.kwargs = kwargs


class SparkLcdUiTests(unittest.TestCase):
    def setUp(self):
        from pico.lcd_ui import ACTIVE, HIGHLIGHT_SEC, SURFACE, SparkLcdUi

        self.ACTIVE = ACTIVE
        self.HIGHLIGHT_SEC = HIGHLIGHT_SEC
        self.SURFACE = SURFACE
        self.ui = SparkLcdUi(
            displayio_module=FakeDisplayIOModule,
            label_module=FakeLabelModule,
            font=object(),
        )

    def test_builds_idle_screen_with_four_mutable_cell_palettes(self):
        self.assertEqual(len(self.ui.cell_palettes), 4)
        self.assertTrue(all(palette[0] == self.SURFACE for palette in self.ui.cell_palettes))
        self.assertIsInstance(self.ui.root_group, FakeGroup)

    def test_press_highlights_selected_cell_and_clears_previous_one(self):
        self.ui.handle_press(1, now=10.0)
        self.ui.handle_press(3, now=10.1)

        self.assertEqual(self.ui.cell_palettes[1][0], self.SURFACE)
        self.assertEqual(self.ui.cell_palettes[3][0], self.ACTIVE)

    def test_tick_clears_highlight_after_timeout(self):
        self.ui.handle_press(2, now=5.0)

        self.ui.tick(now=5.0 + self.HIGHLIGHT_SEC - 0.01)
        self.assertEqual(self.ui.cell_palettes[2][0], self.ACTIVE)

        self.ui.tick(now=5.0 + self.HIGHLIGHT_SEC + 0.01)
        self.assertEqual(self.ui.cell_palettes[2][0], self.SURFACE)

    def test_handle_press_emits_only_selected_debug_checkpoint(self):
        from pico.lcd_ui import SparkLcdUi

        messages = []
        ui = SparkLcdUi(
            displayio_module=FakeDisplayIOModule,
            label_module=FakeLabelModule,
            font=object(),
            debug_hook=messages.append,
            debug_checkpoint="after_press_time",
        )

        ui.handle_press(1, now=10.0)

        self.assertEqual(
            messages,
            [
                "lcd:handle_press:after_press_time index=1",
            ],
        )

    def test_handle_press_emits_palette_write_error_if_it_fails(self):
        from pico.lcd_ui import SparkLcdUi

        class BadPalette:
            def __setitem__(self, key, value):
                raise RuntimeError("palette write failed")

        messages = []
        ui = SparkLcdUi(
            displayio_module=FakeDisplayIOModule,
            label_module=FakeLabelModule,
            font=object(),
            debug_hook=messages.append,
            debug_checkpoint="palette_error",
        )
        ui.cell_palettes = [BadPalette()]

        ui.handle_press(0, now=5.0)

        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].startswith("lcd:handle_press:palette_error"))

    def test_handle_press_skips_palette_write_when_disabled(self):
        from pico.lcd_ui import SparkLcdUi

        messages = []
        ui = SparkLcdUi(
            displayio_module=FakeDisplayIOModule,
            label_module=FakeLabelModule,
            font=object(),
            debug_hook=messages.append,
            debug_checkpoint="palette_write_skipped",
            skip_palette_write=True,
        )

        ui.handle_press(0, now=5.0)

        self.assertEqual(
            messages,
            [
                "lcd:handle_press:palette_write_skipped index=0",
            ],
        )
        self.assertEqual(ui.active_cell, 0)
        self.assertEqual(ui.press_time, 5.0)

    def test_skip_mode_second_press_avoids_previous_cell_palette_write(self):
        from pico.lcd_ui import SparkLcdUi

        ui = SparkLcdUi(
            displayio_module=FakeDisplayIOModule,
            label_module=FakeLabelModule,
            font=object(),
            skip_palette_write=True,
        )
        ui.cell_palettes = [BadCellPalette() for _ in range(4)]

        ui.handle_press(0, now=5.0)
        ui.handle_press(1, now=5.1)

        self.assertEqual(ui.active_cell, 1)
        self.assertEqual(ui.press_time, 5.1)

    def test_skip_mode_tick_avoids_timeout_palette_clear(self):
        from pico.lcd_ui import SparkLcdUi

        ui = SparkLcdUi(
            displayio_module=FakeDisplayIOModule,
            label_module=FakeLabelModule,
            font=object(),
            skip_palette_write=True,
        )
        ui.cell_palettes = [BadCellPalette() for _ in range(4)]

        ui.handle_press(0, now=5.0)
        ui.tick(now=5.0 + self.HIGHLIGHT_SEC + 0.01)

        self.assertIsNone(ui.active_cell)

    def test_disable_highlight_update_avoids_root_group_mutation_on_press(self):
        from pico.lcd_ui import SparkLcdUi

        ui = SparkLcdUi(
            displayio_module=FakeDisplayIOModule,
            label_module=FakeLabelModule,
            font=object(),
            skip_palette_write=True,
            skip_highlight_update=True,
        )
        initial_len = len(ui.root_group)

        ui.handle_press(0, now=5.0)

        self.assertEqual(len(ui.root_group), initial_len)
        self.assertNotIn(ui._highlight_grid, ui.root_group)
        self.assertEqual(ui.active_cell, 0)
        self.assertEqual(ui.press_time, 5.0)

    def test_build_display_bus_uses_supplied_fourwire_class(self):
        from pico.lcd_ui import build_display_bus

        spi = object()
        dc = object()
        cs = object()
        rst = object()

        bus = build_display_bus(spi, dc, cs, rst, fourwire_class=FakeFourWire)

        self.assertIsInstance(bus, FakeFourWire)
        self.assertIs(bus.spi, spi)
        self.assertEqual(
            bus.kwargs,
            {
                "command": dc,
                "chip_select": cs,
                "reset": rst,
                "baudrate": 24_000_000,
            },
        )

    def test_build_display_uses_expected_landscape_rotation(self):
        from pico.lcd_ui import DISPLAY_ROTATION, HEIGHT, WIDTH, build_display

        bus = object()

        display = build_display(bus, display_driver_class=FakeDisplayDriver)

        self.assertIs(display.bus, bus)
        self.assertEqual(
            display.kwargs,
            {"width": WIDTH, "height": HEIGHT, "rotation": DISPLAY_ROTATION},
        )
        self.assertEqual(DISPLAY_ROTATION, 180)


if __name__ == "__main__":
    unittest.main()
