import unittest


class PicoButtonLayoutTests(unittest.TestCase):
    def test_button_definitions_match_hardware_and_lcd_order(self):
        from pico.button_layout import BUTTON_DEFINITIONS

        self.assertEqual(
            [(button.index, button.physical_number, button.name, button.action_label) for button in BUTTON_DEFINITIONS],
            [
                (0, 1, "PB1", "SYNTHESIS"),
                (1, 2, "PB2", "REFORMAT"),
                (2, 3, "PB3", "SEARCH"),
                (3, 4, "PB4", "RESPOND"),
            ],
        )

    def test_button_definitions_follow_pin_config_scan_order(self):
        from pico.button_layout import BUTTON_DEFINITIONS
        from pico.pin_config import BUTTON_PIN_NUMBERS

        self.assertEqual([button.index for button in BUTTON_DEFINITIONS], list(range(len(BUTTON_PIN_NUMBERS))))

    def test_actions_export_matches_button_definitions(self):
        from pico.button_layout import ACTIONS, BUTTON_DEFINITIONS

        self.assertEqual(ACTIONS, tuple(button.action_label for button in BUTTON_DEFINITIONS))

    def test_debug_label_helpers_convert_zero_based_index_to_one_based_text(self):
        from pico.button_layout import debug_label, runtime_alias

        self.assertEqual(debug_label("button", 0), "button:1")
        self.assertEqual(debug_label("render_press_done", 3), "render_press_done:4")
        self.assertEqual(runtime_alias("render_press_done", 3), "rdone:4")

    def test_runtime_alias_uses_compact_prefixes(self):
        from pico.button_layout import runtime_alias

        self.assertEqual(runtime_alias("button", 0), "button:1")
        self.assertEqual(runtime_alias("pre_press", 1), "pre:2")
        self.assertEqual(runtime_alias("post_press", 3), "post:4")
        self.assertEqual(runtime_alias("draw_press", 2), "draw:3")
        self.assertEqual(runtime_alias("press_done", 2), "done:3")
        self.assertEqual(runtime_alias("idle_prev", 1), "idle:2")
        self.assertEqual(runtime_alias("render_press", 1), "rpress:2")

    def test_runtime_checkpoint_alias_normalizes_ui_press_checkpoints(self):
        from pico.button_layout import runtime_checkpoint_alias

        self.assertEqual(runtime_checkpoint_alias("before_ui_press:0"), "ui_pre")
        self.assertEqual(runtime_checkpoint_alias("after_ui_press:1"), "ui_post")
        self.assertEqual(runtime_checkpoint_alias("after_sleep"), "after_sleep")

    def test_invalid_index_falls_back_to_question_mark(self):
        from pico.button_layout import debug_label, runtime_alias

        self.assertEqual(debug_label("button", 99), "button:?")
        self.assertEqual(runtime_alias("pre_press", 99), "pre:?")


if __name__ == "__main__":
    unittest.main()
