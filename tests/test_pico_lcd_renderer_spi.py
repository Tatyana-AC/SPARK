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


def _cell_calls(renderer_spi, index, fill_color):
    x, y = renderer_spi.cell_origin(index)
    text_x, text_y = renderer_spi.cell_label_position(index, renderer_spi.ACTIONS[index])
    return [
        ("fill_rect", x, y, renderer_spi.CELL_W, renderer_spi.CELL_H, fill_color),
        ("fill_rect", x, y, renderer_spi.CELL_W, 2, renderer_spi.ACCENT),
        ("fill_rect", x, y + renderer_spi.CELL_H - 2, renderer_spi.CELL_W, 2, renderer_spi.ACCENT),
        ("fill_rect", x, y, 2, renderer_spi.CELL_H, renderer_spi.ACCENT),
        ("fill_rect", x + renderer_spi.CELL_W - 2, y, 2, renderer_spi.CELL_H, renderer_spi.ACCENT),
        (
            "draw_text",
            text_x,
            text_y,
            renderer_spi.ACTIONS[index],
            renderer_spi.WHITE,
            renderer_spi.FONT_SCALE,
            fill_color,
        ),
    ]


class PicoLcdRendererSpiTests(unittest.TestCase):
    def test_renderer_with_blit_target_defers_pixel_buffer_builds_until_draw(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeBlitTarget()

        with mock.patch.object(renderer_spi, "_build_header_pixels", side_effect=AssertionError("should not prebuild header")):
            with mock.patch.object(renderer_spi, "_build_cell_pixels", side_effect=AssertionError("should not prebuild cells")):
                renderer_spi.SpiLcdRenderer(target=target)

    def test_renderer_uses_prebuilt_blits_when_target_supports_it(self):
        renderer_spi = _load_module("pico.lcd_renderer_spi")
        target = _FakeBlitTarget()
        renderer = renderer_spi.SpiLcdRenderer(target=target)

        renderer.draw_idle_layout()

        self.assertEqual(target.calls, [("fill", renderer_spi.BG)])
        self.assertEqual(len(target.blit_calls), 5)

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
            ("fill_rect", 0, 0, renderer_spi.W, renderer_spi.BAR_H, renderer_spi.SURFACE),
            ("fill_rect", 0, renderer_spi.BAR_H - 2, renderer_spi.W, 2, renderer_spi.ACCENT),
            (
                "draw_text",
                renderer_spi.header_text_position(renderer_spi.TITLE_TEXT)[0],
                renderer_spi.header_text_position(renderer_spi.TITLE_TEXT)[1],
                renderer_spi.TITLE_TEXT,
                renderer_spi.ACCENT,
                renderer_spi.FONT_SCALE,
                renderer_spi.SURFACE,
            ),
        ]
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
