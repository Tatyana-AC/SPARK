import subprocess
import unittest
from pathlib import Path


class SetupSparkMacOSTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script_path = self.repo_root / "setup_spark_macos.sh"

    def test_script_is_valid_bash(self):
        result = subprocess.run(
            ["bash", "-n", str(self.script_path)],
            capture_output=True,
            text=True,
            cwd=self.repo_root,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_dry_run_reports_pico_and_jetson_setup_without_launching_apps(self):
        result = subprocess.run(
            [
                "bash",
                str(self.script_path),
                "--dry-run",
                "--skip-smoke-test",
                "--skip-app-launch",
                "--jetson-host",
                "10.0.0.2",
                "--jetson-user",
                "sidac",
                "--jetson-remote-path",
                "/mnt/usb_drive",
            ],
            capture_output=True,
            text=True,
            cwd=self.repo_root,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("== Environment ==", result.stdout)
        self.assertIn("DRY-RUN", result.stdout)
        self.assertIn("deploy_to_pico.py --target /Volumes/CIRCUITPY", result.stdout)
        self.assertIn("rsync", result.stdout)
        self.assertIn("sidac@10.0.0.2:/mnt/usb_drive/demo/pico_bridge/", result.stdout)
        self.assertIn("chmod\\ +x\\ \\'/mnt/usb_drive/demo/pico_bridge/run_bridge.sh\\'", result.stdout)
        self.assertNotIn("spark_app_v2.py launched", result.stdout)
        self.assertNotIn("watch_full_stack.py launched", result.stdout)


if __name__ == "__main__":
    unittest.main()
