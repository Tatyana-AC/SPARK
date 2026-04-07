import io
import json
import shutil
import tempfile
import types
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

from tools.pico import deploy_to_pico


class DeployToPicoTests(unittest.TestCase):
    def _workspace_tempdir(self, name: str) -> Path:
        root = Path(__file__).resolve().parents[1] / ".tmp" / f"{name}-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def _populate_firmware_repo(self, repo_root: Path) -> None:
        pico_dir = repo_root / "pico"
        pico_dir.mkdir(parents=True, exist_ok=True)
        for name in deploy_to_pico.FIRMWARE_FILES:
            (pico_dir / name).write_text(name, encoding="utf-8")

    def _populate_runtime_library_repo(self, repo_root: Path) -> None:
        lib_dir = repo_root / "lib"
        (lib_dir / "adafruit_hid").mkdir(parents=True, exist_ok=True)
        (lib_dir / "adafruit_hid" / "__init__.py").write_text("# hid\n", encoding="utf-8")
        (lib_dir / "adafruit_hid" / "keyboard.py").write_text("# keyboard\n", encoding="utf-8")
        (lib_dir / "adafruit_bus_device").mkdir(parents=True, exist_ok=True)
        (lib_dir / "adafruit_bus_device" / "__init__.py").write_text("# bus\n", encoding="utf-8")
        (lib_dir / "adafruit_display_text").mkdir(parents=True, exist_ok=True)
        (lib_dir / "adafruit_display_text" / "__init__.py").write_text("# text\n", encoding="utf-8")
        (lib_dir / "adafruit_ili9341.py").write_text("# lcd\n", encoding="utf-8")

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

    def test_firmware_bundle_includes_shared_pin_config(self):
        self.assertIn("pin_config.py", deploy_to_pico.FIRMWARE_FILES)

    def test_firmware_bundle_includes_lcd_ui_module(self):
        self.assertIn("lcd_ui.py", deploy_to_pico.FIRMWARE_FILES)

    def test_firmware_bundle_includes_runtime_runner_module(self):
        self.assertIn("runtime_runner.py", deploy_to_pico.FIRMWARE_FILES)

    def test_firmware_bundle_includes_pico_debug_module(self):
        self.assertIn("pico_debug.py", deploy_to_pico.FIRMWARE_FILES)

    def test_firmware_bundle_includes_bridge_lcd_runtime_modules(self):
        required = {
            "bridge_app.py",
            "bridge_runtime.py",
            "button_input.py",
            "lcd_renderer_spi.py",
            "lcd_state.py",
            "lcd_ui.py",
            "pin_config.py",
        }

        self.assertTrue(required.issubset(set(deploy_to_pico.FIRMWARE_FILES)))

    def test_default_runtime_manifest_excludes_lcd_smoke_test(self):
        manifest = deploy_to_pico.default_runtime_manifest()

        self.assertNotIn("lcd_smoke_test.py", manifest)
        self.assertNotIn("typeback.py", manifest)
        self.assertEqual(manifest[-1], "code.py")

    def test_default_desired_target_paths_from_source_plan_includes_bridge_lcd_assets(self):
        root = self._workspace_tempdir("desired-target-paths")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)

        source_plan = deploy_to_pico.build_source_plan(repo=repo_root)
        desired = deploy_to_pico.default_desired_target_paths_from_source_plan(source_plan)

        self.assertIn("code.py", desired)
        self.assertIn("pin_config.py", desired)
        self.assertIn("lcd_ui.py", desired)
        self.assertIn("lib/adafruit_hid/__init__.py", desired)
        self.assertIn("lib/adafruit_hid/keyboard.py", desired)
        self.assertNotIn("lib/adafruit_bus_device/__init__.py", desired)
        self.assertNotIn("lib/adafruit_display_text/__init__.py", desired)
        self.assertNotIn("lib/adafruit_ili9341.py", desired)

    def test_is_preserved_path_is_exact_and_normalized(self):
        self.assertTrue(deploy_to_pico.is_preserved_path("BOOT_OUT.TXT"))
        self.assertTrue(deploy_to_pico.is_preserved_path("System Volume Information/indexerVolumeGuid"))
        self.assertFalse(deploy_to_pico.is_preserved_path("boot_out.txt.bak"))
        self.assertFalse(deploy_to_pico.is_preserved_path("System Volume Information-old/indexerVolumeGuid"))

    def test_firmware_sources_copy_code_py_last_for_safe_autoreload(self):
        repo_root = self._workspace_tempdir("deploy-order-sources")
        pico_dir = repo_root / "pico"
        pico_dir.mkdir()

        for name in deploy_to_pico.FIRMWARE_FILES:
            (pico_dir / name).write_text(name, encoding="utf-8")

        sources = deploy_to_pico.firmware_sources(repo_root)

        self.assertEqual(sources[-1].name, "code.py")

    def test_copy_firmware_files_writes_code_py_last(self):
        root = self._workspace_tempdir("deploy-order-copy")
        repo_root = root / "repo"
        pico_dir = repo_root / "pico"
        pico_dir.mkdir(parents=True)
        target_root = root / "target"
        target_root.mkdir()

        for name in deploy_to_pico.FIRMWARE_FILES:
            (pico_dir / name).write_text(name, encoding="utf-8")

        copies = deploy_to_pico.copy_firmware_files(target_root, repo=repo_root, dry_run=False)

        self.assertEqual(copies[-1][0].name, "code.py")
        self.assertEqual(copies[-1][1].name, "code.py")

    def test_copy_firmware_files_retries_transient_device_missing_error(self):
        root = self._workspace_tempdir("deploy-copy-retry")
        repo_root = root / "repo"
        pico_dir = repo_root / "pico"
        pico_dir.mkdir(parents=True)
        target_root = root / "target"
        target_root.mkdir()

        for name in deploy_to_pico.FIRMWARE_FILES:
            (pico_dir / name).write_text(name, encoding="utf-8")

        attempts = {"count": 0}
        real_copy2 = shutil.copy2

        def flaky_copy(source, destination, *args, **kwargs):
            if Path(destination).name == "protocol.py" and attempts["count"] == 0:
                attempts["count"] += 1
                error = OSError("device missing")
                error.winerror = 433
                raise error
            return real_copy2(source, destination, *args, **kwargs)

        with mock.patch("tools.pico.deploy_to_pico.shutil.copy2", side_effect=flaky_copy), mock.patch(
            "tools.pico.deploy_to_pico.time.sleep"
        ):
            copies = deploy_to_pico.copy_firmware_files(target_root, repo=repo_root, dry_run=False)

        self.assertEqual(attempts["count"], 1)
        self.assertEqual(copies[-1][1].name, "code.py")
        self.assertTrue((target_root / "protocol.py").exists())

    def test_exact_sync_cleanup_removes_stale_root_file(self):
        target_root = self._workspace_tempdir("stale-root-file") / "target"
        target_root.mkdir(parents=True)
        (target_root / "old_script.py").write_text("old\n", encoding="utf-8")

        deploy_to_pico.exact_sync_cleanup(
            target_root,
            desired_paths={"code.py"},
            preserve_paths=set(deploy_to_pico.default_preserve_paths()),
        )

        self.assertFalse((target_root / "old_script.py").exists())

    def test_exact_sync_cleanup_removes_stale_directory(self):
        target_root = self._workspace_tempdir("stale-dir") / "target"
        stale_dir = target_root / "old_dir"
        stale_dir.mkdir(parents=True)
        (stale_dir / "nested.txt").write_text("old\n", encoding="utf-8")

        deploy_to_pico.exact_sync_cleanup(
            target_root,
            desired_paths={"code.py"},
            preserve_paths=set(deploy_to_pico.default_preserve_paths()),
        )

        self.assertFalse(stale_dir.exists())

    def test_exact_sync_cleanup_removes_stale_lib_package(self):
        target_root = self._workspace_tempdir("stale-lib") / "target"
        stale_pkg = target_root / "lib" / "old_pkg"
        stale_pkg.mkdir(parents=True)
        (stale_pkg / "__init__.py").write_text("# old\n", encoding="utf-8")

        deploy_to_pico.exact_sync_cleanup(
            target_root,
            desired_paths={"code.py", "lib/adafruit_hid/__init__.py"},
            preserve_paths=set(deploy_to_pico.default_preserve_paths()),
        )

        self.assertFalse(stale_pkg.exists())

    def test_exact_sync_cleanup_removes_runtime_logs(self):
        target_root = self._workspace_tempdir("runtime-logs") / "target"
        target_root.mkdir(parents=True)
        for name in ("runtime_error.txt", "startup_trace.txt", "uart_diag.txt"):
            (target_root / name).write_text("artifact\n", encoding="utf-8")

        deploy_to_pico.exact_sync_cleanup(
            target_root,
            desired_paths={"code.py"},
            preserve_paths=set(deploy_to_pico.default_preserve_paths()),
        )

        self.assertFalse((target_root / "runtime_error.txt").exists())
        self.assertFalse((target_root / "startup_trace.txt").exists())
        self.assertFalse((target_root / "uart_diag.txt").exists())

    def test_exact_sync_cleanup_preserves_system_volume_information_subtree(self):
        target_root = self._workspace_tempdir("preserve-system") / "target"
        preserved_dir = target_root / "System Volume Information"
        preserved_dir.mkdir(parents=True)
        (preserved_dir / "indexerVolumeGuid").write_text("keep\n", encoding="utf-8")

        deploy_to_pico.exact_sync_cleanup(
            target_root,
            desired_paths={"code.py"},
            preserve_paths=set(deploy_to_pico.default_preserve_paths()),
        )

        self.assertTrue((preserved_dir / "indexerVolumeGuid").exists())

    def test_exact_sync_cleanup_keeps_desired_files(self):
        target_root = self._workspace_tempdir("keep-desired") / "target"
        target_root.mkdir(parents=True)
        (target_root / "code.py").write_text("print('hi')\n", encoding="utf-8")

        deploy_to_pico.exact_sync_cleanup(
            target_root,
            desired_paths={"code.py"},
            preserve_paths=set(deploy_to_pico.default_preserve_paths()),
        )

        self.assertTrue((target_root / "code.py").exists())

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
            repo_root = Path(temp_dir) / "repo"
            (repo_root / "pico").mkdir(parents=True)
            package_dir = Path(temp_dir) / "site-packages" / "adafruit_hid"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("# test\n", encoding="utf-8")
            fake_spec = mock.Mock(origin=str(package_dir / "__init__.py"))
            with mock.patch("importlib.util.find_spec", return_value=fake_spec):
                resolved = deploy_to_pico.find_local_adafruit_hid(repo_root, None)
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

    def test_extract_runtime_libraries_from_bundle_copies_only_adafruit_hid(self):
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
                    "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_bus_device/__init__.py",
                    "# bus device\n",
                )
                archive.writestr(
                    "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_display_text/__init__.py",
                    "# display text\n",
                )
                archive.writestr(
                    "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_ili9341.py",
                    "# ili9341\n",
                )
                archive.writestr(
                    "adafruit-circuitpython-bundle-py-20260101/lib/not_needed.py",
                    "# ignore\n",
                )

            extracted = deploy_to_pico.extract_required_libraries_from_bundle(
                bundle_zip,
                target_root,
                required_paths=deploy_to_pico.RUNTIME_LIBRARY_PATHS,
            )

            self.assertEqual(
                {path.name for path in extracted},
                {"adafruit_hid"},
            )
            self.assertTrue((target_root / "adafruit_hid" / "__init__.py").exists())
            self.assertFalse((target_root / "adafruit_bus_device" / "__init__.py").exists())
            self.assertFalse((target_root / "adafruit_display_text" / "__init__.py").exists())
            self.assertFalse((target_root / "adafruit_ili9341.py").exists())
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

    def test_runtime_library_paths_include_only_adafruit_hid(self):
        self.assertEqual(deploy_to_pico.RUNTIME_LIBRARY_PATHS, ("adafruit_hid",))

    def test_ensure_runtime_libraries_downloads_only_adafruit_hid_into_repo_cache_then_copies_to_target(self):
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
                    archive.writestr(
                        "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_bus_device/__init__.py",
                        "# bus\n",
                    )
                    archive.writestr(
                        "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_display_text/__init__.py",
                        "# text\n",
                    )
                    archive.writestr(
                        "adafruit-circuitpython-bundle-py-20260101/lib/adafruit_ili9341.py",
                        "# lcd\n",
                    )
                return destination

            with mock.patch.object(deploy_to_pico, "download_bundle_zip", side_effect=fake_download):
                source_paths, copied_paths, mode = deploy_to_pico.ensure_runtime_libraries(
                    target,
                    repo=repo,
                    library_source=None,
                    dry_run=False,
                )

            cached_vendor = repo / "tools" / "pico" / "vendor"
            self.assertEqual(mode, "download")
            self.assertEqual(
                {path.name for path in source_paths},
                {"adafruit_hid"},
            )
            self.assertEqual(
                {path.name for path in copied_paths},
                {"adafruit_hid"},
            )
            self.assertTrue((cached_vendor / "adafruit_hid" / "__init__.py").exists())
            self.assertTrue((cached_vendor / "adafruit_hid" / "keyboard.py").exists())
            self.assertTrue((target / "lib" / "adafruit_hid" / "__init__.py").exists())
            self.assertFalse((cached_vendor / "adafruit_bus_device").exists())
            self.assertFalse((cached_vendor / "adafruit_display_text").exists())
            self.assertFalse((cached_vendor / "adafruit_ili9341.py").exists())
            self.assertFalse((target / "lib" / "adafruit_bus_device").exists())
            self.assertFalse((target / "lib" / "adafruit_display_text").exists())
            self.assertFalse((target / "lib" / "adafruit_ili9341.py").exists())

    def test_exact_sync_cleanup_keeps_bridge_lcd_firmware_and_removes_old_libraries(self):
        root = self._workspace_tempdir("stale-lcd-assets")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)
        target_root = root / "target"
        (target_root / "lib").mkdir(parents=True)
        (target_root / "lcd_ui.py").write_text("lcd\n", encoding="utf-8")
        (target_root / "pin_config.py").write_text("pins\n", encoding="utf-8")
        (target_root / "lib" / "adafruit_ili9341.py").write_text("lcd\n", encoding="utf-8")
        (target_root / "lib" / "adafruit_display_text").mkdir(parents=True)
        (target_root / "lib" / "adafruit_display_text" / "__init__.py").write_text("# text\n", encoding="utf-8")
        (target_root / "lib" / "adafruit_bus_device").mkdir(parents=True)
        (target_root / "lib" / "adafruit_bus_device" / "__init__.py").write_text("# bus\n", encoding="utf-8")

        source_plan = deploy_to_pico.build_source_plan(repo=repo_root)
        deploy_to_pico.exact_sync_cleanup(
            target_root,
            desired_paths=deploy_to_pico.default_desired_target_paths_from_source_plan(source_plan),
            preserve_paths=set(deploy_to_pico.default_preserve_paths()),
        )

        self.assertTrue((target_root / "lcd_ui.py").exists())
        self.assertTrue((target_root / "pin_config.py").exists())
        self.assertFalse((target_root / "lib" / "adafruit_ili9341.py").exists())
        self.assertFalse((target_root / "lib" / "adafruit_display_text").exists())
        self.assertFalse((target_root / "lib" / "adafruit_bus_device").exists())

    def test_runtime_code_disables_circuitpython_autoreload(self):
        code_py = Path(__file__).resolve().parents[1] / "pico" / "code.py"
        code_text = code_py.read_text(encoding="utf-8")

        self.assertIn("supervisor.runtime.autoreload = False", code_text)

    def test_run_deploy_aborts_before_cleanup_when_firmware_source_missing(self):
        root = self._workspace_tempdir("missing-firmware-source")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)
        (repo_root / "pico" / "code.py").unlink()
        target_root = root / "target"
        target_root.mkdir()
        stale_file = target_root / "old_script.py"
        stale_file.write_text("old\n", encoding="utf-8")

        with self.assertRaisesRegex(deploy_to_pico.DeployError, "Missing firmware source files"):
            deploy_to_pico.run_deploy(target=target_root, repo=repo_root)

        self.assertTrue(stale_file.exists())

    def test_run_deploy_aborts_before_cleanup_when_library_resolution_fails(self):
        root = self._workspace_tempdir("library-resolution-fails")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        target_root = root / "target"
        target_root.mkdir()
        stale_file = target_root / "old_script.py"
        stale_file.write_text("old\n", encoding="utf-8")

        with mock.patch.object(deploy_to_pico, "download_bundle_zip", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(deploy_to_pico.DeployError, "Could not prepare runtime libraries"):
                deploy_to_pico.run_deploy(target=target_root, repo=repo_root)

        self.assertTrue(stale_file.exists())

    def test_run_deploy_deletes_stale_entries_first_when_space_is_low(self):
        root = self._workspace_tempdir("low-space")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)
        target_root = root / "target"
        target_root.mkdir()
        (target_root / "old_script.py").write_text("old\n", encoding="utf-8")
        call_log = []

        def fake_delete(stale_paths):
            call_log.append("delete")
            for path in stale_paths:
                deploy_to_pico._remove_existing_path(path)

        def fake_copy(source, destination):
            call_log.append(f"copy:{Path(destination).name}")
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        disk_results = [
            types.SimpleNamespace(free=0),
            types.SimpleNamespace(free=10**9),
        ]

        with mock.patch.object(deploy_to_pico.shutil, "disk_usage", side_effect=disk_results), mock.patch.object(
            deploy_to_pico, "delete_stale_paths", side_effect=fake_delete
        ), mock.patch.object(deploy_to_pico, "_copy_with_retry", side_effect=fake_copy):
            deploy_to_pico.run_deploy(target=target_root, repo=repo_root)

        self.assertEqual(call_log[0], "delete")
        self.assertEqual(call_log[-1], "copy:code.py")

    def test_run_deploy_fails_when_space_is_still_insufficient_after_cleanup(self):
        root = self._workspace_tempdir("space-still-low")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)
        target_root = root / "target"
        target_root.mkdir()
        (target_root / "old_script.py").write_text("old\n", encoding="utf-8")

        with mock.patch.object(
            deploy_to_pico.shutil,
            "disk_usage",
            side_effect=[types.SimpleNamespace(free=0), types.SimpleNamespace(free=0)],
        ):
            with self.assertRaisesRegex(deploy_to_pico.DeployError, "Not enough space after stale cleanup"):
                deploy_to_pico.run_deploy(target=target_root, repo=repo_root)

    def test_run_deploy_reports_partial_update_when_delete_fails(self):
        root = self._workspace_tempdir("delete-fails")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)
        target_root = root / "target"
        target_root.mkdir()
        (target_root / "old_script.py").write_text("old\n", encoding="utf-8")
        call_log = []

        def fake_delete(stale_paths):
            call_log.append("delete")
            raise OSError("cannot delete")

        with mock.patch.object(deploy_to_pico.shutil, "disk_usage", return_value=types.SimpleNamespace(free=0)), mock.patch.object(
            deploy_to_pico, "delete_stale_paths", side_effect=fake_delete
        ):
            with self.assertRaisesRegex(
                deploy_to_pico.DeployError,
                "Reconnect or reset the Pico and rerun deploy",
            ):
                deploy_to_pico.run_deploy(target=target_root, repo=repo_root)

        self.assertEqual(call_log, ["delete"])

    def test_run_deploy_reports_partial_update_when_copy_fails_after_cleanup(self):
        root = self._workspace_tempdir("copy-fails")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)
        target_root = root / "target"
        target_root.mkdir()
        call_log = []

        def fake_copy(source, destination):
            call_log.append(f"copy:{Path(destination).name}")
            raise OSError("cannot copy")

        with mock.patch.object(deploy_to_pico.shutil, "disk_usage", return_value=types.SimpleNamespace(free=10**9)), mock.patch.object(
            deploy_to_pico, "_copy_with_retry", side_effect=fake_copy
        ):
            with self.assertRaisesRegex(
                deploy_to_pico.DeployError,
                "Reconnect or reset the Pico and rerun deploy",
            ):
                deploy_to_pico.run_deploy(target=target_root, repo=repo_root)

        self.assertEqual(call_log, ["copy:boot.py"])

    def test_main_dry_run_reports_planned_deletions(self):
        root = self._workspace_tempdir("dry-run-output")
        repo_root = root / "repo"
        self._populate_firmware_repo(repo_root)
        self._populate_runtime_library_repo(repo_root)
        target_root = root / "target"
        target_root.mkdir()
        (target_root / "old_script.py").write_text("old\n", encoding="utf-8")

        stdout = io.StringIO()
        with mock.patch.object(deploy_to_pico, "repo_root", return_value=repo_root), mock.patch(
            "sys.stdout", stdout
        ):
            rc = deploy_to_pico.main(["--dry-run", "--target", str(target_root)])

        self.assertEqual(rc, 0)
        self.assertIn("Would delete", stdout.getvalue())
        self.assertIn("Would copy", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
