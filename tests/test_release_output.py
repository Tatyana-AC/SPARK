import unittest


class ReleaseOutputTests(unittest.TestCase):
    def test_format_echo_output_wraps_text_with_echo_markers(self):
        from host_pc.release_output import format_release_output

        formatted = format_release_output("hello world")

        self.assertEqual(formatted, "(echo) hello world (echo)")


if __name__ == "__main__":
    unittest.main()
