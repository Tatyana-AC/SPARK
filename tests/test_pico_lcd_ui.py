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
