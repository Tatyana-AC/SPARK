import unittest


class PicoPinConfigTests(unittest.TestCase):
    def test_button_pin_numbers_match_physical_order(self):
        from pico.pin_config import BUTTON_PIN_NUMBERS

        self.assertEqual(BUTTON_PIN_NUMBERS, (2, 3, 4, 5))


if __name__ == "__main__":
    unittest.main()
