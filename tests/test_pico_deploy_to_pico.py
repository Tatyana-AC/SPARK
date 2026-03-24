import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pico import deploy_to_pico


class DeployToPicoTests(unittest.TestCase):
    def test_firmware_files_are_flattened_from_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            pico_dir = repo_root / "pico"
            pico_dir.mkdir()

            expected = []
            for name in deploy_to_pico.FIRMWARE_FILES:
                path = pico_dir / name
                path.write_text(name, encoding="utf-8")
                expected.append(path)

            self.assertEqual(deploy_to_pico.firmware_sources(repo_root), expected)

    def test_find_local_adafruit_hid_prefers_explicit_library_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            explicit = base / "bundle"
            package_dir = explicit / "adafruit_hid"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("# test\n", encoding="utf-8")

            resolved = deploy_to_pico.find_local_adafruit_hid(base, explicit)
            self.assertEqual(resolved, package_dir)

    def test_find_local_adafruit_hid_accepts_package_directory_directly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "adafruit_hid"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("# test\n", encoding="utf-8")

            resolved = deploy_to_pico.find_local_adafruit_hid(Path(temp_dir), package_dir)
            self.assertEqual(resolved, package_dir)

    def test_find_local_adafruit_hid_uses_imported_package_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "site-packages" / "adafruit_hid"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("# test\n", encoding="utf-8")
            fake_spec = mock.Mock(origin=str(package_dir / "__init__.py"))
            with mock.patch("importlib.util.find_spec", return_value=fake_spec):
                resolved = deploy_to_pico.find_local_adafruit_hid(Path.cwd(), None)
            self.assertEqual(package_dir, resolved)

    def test_select_bundle_asset_url_picks_bundle_py_zip(self):
        release = {
            "assets": [
                {"name": "adafruit-circuitpython-bundle-10.x-mpy-20260101.zip", "browser_download_url": "mpy"},
                {"name": "adafruit-circuitpython-bundle-py-20260101.zip", "browser_download_url": "py"},
            ]
        }
        self.assertEqual(deploy_to_pico.select_bundle_asset_url(release), "py")

    def test_extract_adafruit_hid_from_bundle_copies_only_library(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_zip = temp_path / "bundle.zip"
            target_root = temp_path / "lib"
            target_root.mkdir()

            with zipfile.ZipFile(bundle_zip, "w") as archive:
                archive.writestr(
                    "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_hid/__init__.py",
                    "# hid\n",
                )
                archive.writestr(
                    "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_hid/keyboard.py",
                    "# keyboard\n",
                )
                archive.writestr(
                    "adafruit-circuitpython-bundle-py-20260101/lib/not_needed.py",
                    "# ignore\n",
                )

            extracted = deploy_to_pico.extract_adafruit_hid_from_bundle(bundle_zip, target_root)

            self.assertEqual(extracted, target_root / "adafruit_hid")
            self.assertTrue((target_root / "adafruit_hid" / "__init__.py").exists())
            self.assertTrue((target_root / "adafruit_hid" / "keyboard.py").exists())
            self.assertFalse((target_root / "not_needed.py").exists())

    def test_detect_target_uses_macos_volume(self):
        fake_volume = Path("/Volumes/CIRCUITPY")
        with mock.patch.object(Path, "exists", autospec=True) as exists:
            exists.side_effect = lambda self: str(self) == str(fake_volume)
            target = deploy_to_pico.detect_target_path(None)
        self.assertEqual(target, fake_volume)

    def test_detect_target_uses_override_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = deploy_to_pico.detect_target_path(temp_dir)
            self.assertEqual(target, Path(temp_dir))

    def test_fetch_latest_bundle_release_parses_json_payload(self):
        payload = {"assets": [{"name": "adafruit-circuitpython-bundle-py-20260101.zip"}]}
        fake_response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            release = deploy_to_pico.fetch_latest_bundle_release()
        self.assertEqual(release["assets"][0]["name"], payload["assets"][0]["name"])

    def test_ensure_adafruit_hid_downloads_into_repo_cache_then_copies_to_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            (repo / "pico").mkdir(parents=True)
            target = root / "target"
            target.mkdir()

            def fake_download(destination):
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr(
                        "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_hid/__init__.py",
                        "# hid\n",
                    )
                    archive.writestr(
                        "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_hid/keyboard.py",
                        "# keyboard\n",
                    )
                return destination

            with mock.patch.object(deploy_to_pico, "download_bundle_zip", side_effect=fake_download):
                source_package, target_package, mode = deploy_to_pico.ensure_adafruit_hid(
                    target,
                    repo=repo,
                    library_source=None,
                    dry_run=False,
                )

            cached_package = repo / "pico" / "vendor" / "adafruit_hid"
            self.assertEqual(mode, "download")
            self.assertEqual(source_package, cached_package)
            self.assertEqual(target_package, target / "lib" / "adafruit_hid")
            self.assertTrue((cached_package / "__init__.py").exists())
            self.assertTrue((cached_package / "keyboard.py").exists())
            self.assertTrue((target / "lib" / "adafruit_hid" / "__init__.py").exists())


if __name__ == "__main__":
    unittest.main()
