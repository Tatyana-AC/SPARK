import unittest


class PicoPinConfigTests(unittest.TestCase):
    def test_confirmed_button_and_lcd_pin_numbers(self):
        from pico.pin_config import (
            BUTTON_PIN_NUMBERS,
            LCD_PIN_NUMBERS,
        )

        self.assertEqual(BUTTON_PIN_NUMBERS, (2, 4, 3, 5))
        self.assertEqual(
            LCD_PIN_NUMBERS,
            {
                "mosi": 19,
                "clk": 18,
                "cs": 17,
                "dc": 16,
                "rst": 20,
            },
        )


if __name__ == "__main__":
    unittest.main()
