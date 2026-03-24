import unittest


class FakeLayout:
    def __init__(self):
        self.written = []

    def write(self, text):
        self.written.append(text)


class TypebackTests(unittest.TestCase):
    def test_prepare_typeback_text_skips_non_ascii_characters(self):
        from pico.typeback import prepare_typeback_text

        prepared = prepare_typeback_text("hello ✓ 世界")

        self.assertEqual(prepared["typed_text"], "hello  ")
        self.assertEqual(prepared["typable_count"], 7)
        self.assertEqual(prepared["skipped_count"], 3)
        self.assertEqual(prepared["detail"], "best-effort")

    def test_prepare_typeback_text_keeps_newlines_tabs_and_ascii_punctuation(self):
        from pico.typeback import prepare_typeback_text

        prepared = prepare_typeback_text("A\tB\nC!?")

        self.assertEqual(prepared["typed_text"], "A\tB\nC!?")
        self.assertEqual(prepared["typable_count"], 7)
        self.assertEqual(prepared["skipped_count"], 0)

    def test_typeback_service_writes_one_character_per_step(self):
        from pico.typeback import TypebackService

        layout = FakeLayout()
        service = TypebackService(layout)
        service.enqueue_text("abc")

        first = service.step(max_chars=1)
        second = service.step(max_chars=1)
        third = service.step(max_chars=1)

        self.assertEqual((first, second, third), (1, 1, 1))
        self.assertEqual(layout.written, ["a", "b", "c"])
        self.assertFalse(service.has_pending())


if __name__ == "__main__":
    unittest.main()
