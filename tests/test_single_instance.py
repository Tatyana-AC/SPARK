import tempfile
import unittest
from pathlib import Path

try:
    from host_pc.single_instance import SingleInstanceGuard
except ImportError:  # pragma: no cover - environment-dependent test guard
    SingleInstanceGuard = None


@unittest.skipUnless(SingleInstanceGuard is not None, "PyQt6 is not installed")
class SingleInstanceGuardTests(unittest.TestCase):
    def test_second_guard_cannot_acquire_lock_while_first_is_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "spark_app.lock"
            first = SingleInstanceGuard(lock_path)
            second = SingleInstanceGuard(lock_path)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())

            first.release()
            self.assertTrue(second.acquire())
            second.release()


if __name__ == "__main__":
    unittest.main()
