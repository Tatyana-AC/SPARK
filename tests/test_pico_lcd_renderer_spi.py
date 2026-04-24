import importlib
import importlib.util
import unittest
from unittest import mock


def _load_module(name):
    spec = importlib.util.find_spec(name)
    assert spec is not None, f"missing module: {name}"
    return importlib.import_module(name)


class _FakeDrawTarget:
    def __init__(self):
        self.calls = []
        self.displayio_mutation_calls = []

    def fill(self, color):
        self.calls.append(("fill", color))

    def fill_rect(self, x, y, width, height, color):
        self.calls.append(("fill_rect", x, y, width, height, color))

    def draw_text(self, x, y, text, color, *, scale, background_color=None):
        self.calls.append(("draw_text", x, y, text, color, scale, background_color))

    def append(self, *_args, **_kwargs):
        self.displayio_mutation_calls.append("append")

    def remove(self, *_args, **_kwargs):
        self.displayio_mutation_calls.append("remove")


class _FakeBlitTarget(_FakeDrawTarget):
    def __init__(self):
        super().__init__()
        self.blit_calls = []

    def blit_pixels(self, x, y, width, height, pixel_bytes):
        self.blit_calls.append((x, y, width, height, len(pixel_bytes)))


def _bordered_region_calls(renderer_spi, x, y, width, height, fill_color):
    return [
        ("fill_rect", x, y, width, height, fill_color),
        ("fill_rect", x, y, width, 2, renderer_spi.ACCENT),
        ("fill_rect", x, y + height - 2, width, 2, renderer_spi.ACCENT),
        ("fill_rect", x, y, 2, height, renderer_spi.ACCENT),
        ("fill_rect", x + width - 2, y, 2, height, renderer_spi.ACCENT),
    ]


def _spacer_calls(renderer_spi, index):
    x, y = renderer_spi.spacer_origin(index)
    return _bordered_region_calls(renderer_spi, x, y, renderer_spi.spacer_width(index), renderer_spi.CELL_H, renderer_spi.SURFACE)


def _cell_calls(renderer_spi, index, fill_color):
    x, y = renderer_spi.cell_origin(index)
    text_x, text_y = renderer_spi.cell_label_position(index, renderer_spi.ACTIONS[index])
    return _bordered_region_calls(renderer_spi, x, y, renderer_spi.cell_width(index), renderer_spi.CELL_H, fill_color) + [
        (
            "draw_text",
            text_x,
            text_y,
            renderer_spi.ACTIONS[index],
            renderer_spi.WHITE,
            renderer_spi.CELL_LABEL_FONT_SCALE,
            fill_color,
        ),
    ]


class PicoLcdRendererSpiTests(unittest.TestCase):
    def test_renderer_uses_staggered_bottom_cell_geometry_with_fit_cell_labels(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")

        self.assertEqual(renderer_spi.cell_origin(0), (8, 196))
        self.assertEqual(renderer_spi.cell_origin(1), (74, 144))
        self.assertEqual(renderer_spi.cell_origin(2), (137, 196))
        self.assertEqual(renderer_spi.cell_origin(3), (197, 144))
        self.assertEqual(renderer_spi.spacer_origin(0), (8, 144))
        self.assertEqual(renderer_spi.spacer_origin(1), (254, 196))
        self.assertEqual(renderer_spi.cell_width(0), 121)
        self.assertEqual(renderer_spi.cell_width(1), 115)
        self.assertEqual(renderer_spi.cell_width(2), 109)
        self.assertEqual(renderer_spi.cell_width(3), 115)
        self.assertEqual(renderer_spi.CELL_H, 44)
        self.assertEqual(renderer_spi.spacer_width(0), 58)
        self.assertEqual(renderer_spi.spacer_width(1), 58)
        self.assertEqual(renderer_spi.LAYOUT_TOP, 144)
        self.assertEqual(renderer_spi.CELL_LABEL_FONT_SCALE, 2)

        for index, action in enumerate(renderer_spi.ACTIONS):
            text_x, text_y = renderer_spi.cell_label_position(index, action)
            cell_x, cell_y = renderer_spi.cell_origin(index)
            self.assertGreaterEqual(text_x, cell_x)
            self.assertGreaterEqual(text_y, cell_y)
            self.assertLessEqual(
                text_x + renderer_spi.text_width(action, scale=renderer_spi.CELL_LABEL_FONT_SCALE),
                cell_x + renderer_spi.cell_width(index),
            )
            self.assertLessEqual(
                text_y + (renderer_spi.FONT_HEIGHT * renderer_spi.CELL_LABEL_FONT_SCALE),
                cell_y + renderer_spi.CELL_H,
            )

    def test_renderer_with_blit_target_defers_pixel_buffer_builds_until_draw(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeBlitTarget()

        with mock.patch.object(renderer_spi, "_build_spacer_pixels", side_effect=AssertionError("should not prebuild spacers")):
            with mock.patch.object(renderer_spi, "_build_cell_pixels", side_effect=AssertionError("should not prebuild cells")):
                renderer_spi.SpiLcdRenderer(target=target)

    def test_renderer_uses_prebuilt_blits_when_target_supports_it(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeBlitTarget()
        renderer = renderer_spi.SpiLcdRenderer(target=target)

        renderer.draw_idle_layout()

        self.assertEqual(target.calls, [("fill", renderer_spi.BG)])
        self.assertEqual(len(target.blit_calls), 6)

        target.calls.clear()
        target.blit_calls.clear()

        renderer.draw_pressed_cell(2)

        self.assertEqual(target.calls, _cell_calls(renderer_spi, 2, renderer_spi.ACTIVE))
        self.assertEqual(target.blit_calls, [])

    def test_renderer_emits_pressed_cell_stage_debug(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeBlitTarget()
        debug_calls = []
        renderer = renderer_spi.SpiLcdRenderer(target=target)

        renderer.set_debug_sender(debug_calls.append)
        renderer.draw_pressed_cell(1)

        self.assertEqual(
            debug_calls,
            [
                "render_press:2",
                "render_press_done:2",
            ],
        )

    def test_renderer_draws_idle_layout_once(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeDrawTarget()
        renderer = renderer_spi.SpiLcdRenderer(target=target)

        renderer.draw_idle_layout()

        expected_calls = [
            ("fill", renderer_spi.BG),
        ]
        for index in range(2):
            expected_calls.extend(_spacer_calls(renderer_spi, index))
        for index in range(4):
            expected_calls.extend(_cell_calls(renderer_spi, index, renderer_spi.SURFACE))

        self.assertEqual(target.calls, expected_calls)

        renderer.draw_idle_layout()
        self.assertEqual(target.calls, expected_calls)

    def test_renderer_redraws_single_pressed_cell_region(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeDrawTarget()
        renderer = renderer_spi.SpiLcdRenderer(target=target)

        renderer.draw_idle_layout()
        target.calls.clear()

        renderer.draw_pressed_cell(2)

        self.assertEqual(target.calls, _cell_calls(renderer_spi, 2, renderer_spi.ACTIVE))

    def test_renderer_clears_pressed_cell_without_displayio_mutation_calls(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeDrawTarget()
        renderer = renderer_spi.SpiLcdRenderer(target=target)

        renderer.draw_idle_layout()
        renderer.draw_pressed_cell(1)
        target.calls.clear()
        target.displayio_mutation_calls.clear()

        renderer.draw_idle_cell(1)

        self.assertEqual(target.calls, _cell_calls(renderer_spi, 1, renderer_spi.SURFACE))
        self.assertEqual(target.displayio_mutation_calls, [])

    def test_spi_target_draw_text_uses_single_window_setup(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")

        class _FakeSpi:
            def __init__(self):
                self.writes = []

            def try_lock(self):
                return True

            def configure(self, **_kwargs):
                return None

            def write(self, payload):
                self.writes.append(bytes(payload))

            def unlock(self):
                return None

        class _FakePin:
            def __init__(self):
                self.value = None

            def switch_to_output(self, value=False):
                self.value = value

        target = renderer_spi.Ili9341SpiTarget(_FakeSpi(), _FakePin(), _FakePin(), _FakePin())
        target._spi.writes.clear()

        target.draw_text(
            10,
            20,
            "SPARK",
            renderer_spi.WHITE,
            scale=renderer_spi.FONT_SCALE,
            background_color=renderer_spi.SURFACE,
        )

        self.assertEqual(target._spi.writes.count(bytes((renderer_spi._ILI9341_COLUMN_SET,))), 1)
        self.assertEqual(target._spi.writes.count(bytes((renderer_spi._ILI9341_PAGE_SET,))), 1)
        self.assertEqual(target._spi.writes.count(bytes((renderer_spi._ILI9341_RAM_WRITE,))), 1)
        payload_writes = [payload for payload in target._spi.writes if len(payload) > 2]
        self.assertTrue(payload_writes)
        self.assertTrue(all(len(payload) <= target._chunk_pixels * 2 for payload in payload_writes))

    def test_spi_target_blit_pixels_uses_single_window_setup(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")

        class _FakeSpi:
            def __init__(self):
                self.writes = []

            def try_lock(self):
                return True

            def configure(self, **_kwargs):
                return None

            def write(self, payload):
                self.writes.append(bytes(payload))

            def unlock(self):
                return None

        class _FakePin:
            def __init__(self):
                self.value = None

            def switch_to_output(self, value=False):
                self.value = value

        target = renderer_spi.Ili9341SpiTarget(_FakeSpi(), _FakePin(), _FakePin(), _FakePin())
        target._spi.writes.clear()

        pixels = bytes(range(32))
        target.blit_pixels(10, 20, 4, 4, pixels)

        self.assertEqual(target._spi.writes.count(bytes((renderer_spi._ILI9341_COLUMN_SET,))), 1)
        self.assertEqual(target._spi.writes.count(bytes((renderer_spi._ILI9341_PAGE_SET,))), 1)
        self.assertEqual(target._spi.writes.count(bytes((renderer_spi._ILI9341_RAM_WRITE,))), 1)
        self.assertIn(pixels, target._spi.writes)


if __name__ == "__main__":
    unittest.main()
