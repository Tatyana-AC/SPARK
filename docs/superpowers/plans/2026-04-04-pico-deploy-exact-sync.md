# Pico Deploy Exact Sync Implementation Plan

> Historical note (repo cleanup 2026-04-18): references below to `pico_reference/main.py` and `tests/test_watch_pico_cdc_debug.py` describe files that existed when this plan was written but were later removed from the repo.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pico deploy produce an exact repo-owned default runtime on `CIRCUITPY`, delete stale non-preserved files, and reorganize the repo so `pico/` contains only Pico-runnable code.

**Architecture:** Move the deploy tool and vendor cache out of `pico/`, keep an explicit runtime manifest for the default deployed firmware, and make deploy compute a normalized desired on-device file set before mutating `CIRCUITPY`. Preserve only a small system allowlist, copy support files before `code.py`, and delete stale files in a controlled exact-sync pass with explicit low-space and partial-failure behavior.

**Tech Stack:** Python 3, `pathlib`, `shutil`, `ctypes`, CircuitPython `CIRCUITPY` volume semantics, `pytest`, PowerShell docs/scripts

---

## File Structure

**Create:**

- `tools/pico/deploy_to_pico.py` — the relocated deploy tool and single source of truth for the default deploy manifest, preserve rules, and exact-sync behavior
- `tools/pico/vendor/` — vendor cache/source tree moved out of `pico/`
- `docs/pico/README.md` — Pico deploy/runtime docs moved out of `pico/`
- `docs/pico/HARDWARE_SMOKE_TEST.md` — smoke-test instructions moved out of `pico/`
- `pico_reference/main.py` — readable reference implementation moved out of `pico/`

**Modify:**

- `tests/test_pico_deploy_to_pico.py` — update import path and add exact-sync cleanup, preserve, low-space, and dry-run coverage
- `README.md` — update deploy command examples and warn that deploy deletes stale non-preserved files
- `docs/WINDOWS_PICO_JETSON_BRINGUP.md` — update deploy command path
- `documentation_reference.md` — update deploy helper path and repo references
- `docs/BRANCH_HANDOFF_2026-03-24.md` — update stale deploy references if present
- `docs/BRANCH_HANDOFF_2026-03-29.md` — update deploy path references if present
- `ENGINEERING_SPEC.md` — update any deploy path or repo-structure references
- `diagram.md` — update any deploy path or runtime-layout references
- `REPO_STRUCTURE.md` — reflect that `pico/` is Pico-runnable only, with deploy tooling moved out
- `lcd_screen_ui/README.md` — update any smoke/deploy workflow references
- `docs/plans/2026-03-25-pico-jetson-transport.md` — update stale deploy path references if still kept current

**Keep in `pico/`:**

- `boot.py`, `code.py`, `jetson_transport.py`, `lcd_ui.py`, `lcd_smoke_test.py`, `pico_debug.py`, `pin_config.py`, `protocol.py`, `runtime_runner.py`, `serial_bridge.py`, `typeback.py`, `upload_protocol.py`, `usb_config.py`

**Remove from `pico/`:**

- `deploy_to_pico.py`, `README.md`, `HARDWARE_SMOKE_TEST.md`, `main.py`, `vendor/`, and `__init__.py`

### Task 1: Move Deploy Tooling And Runtime-Only Repo Boundaries

**Files:**
- Create: `tools/pico/deploy_to_pico.py`
- Create: `tools/pico/vendor/`
- Create: `docs/pico/README.md`
- Create: `docs/pico/HARDWARE_SMOKE_TEST.md`
- Create: `pico_reference/main.py`
- Modify: `tests/test_pico_deploy_to_pico.py:11,97-98,289-303`
- Modify: `REPO_STRUCTURE.md` (deploy tool and `pico/` layout references)
- Delete: `pico/deploy_to_pico.py`
- Delete: `pico/vendor/`
- Delete: `pico/README.md`
- Delete: `pico/HARDWARE_SMOKE_TEST.md`
- Delete: `pico/main.py`
- Delete: `pico/__init__.py`

- [ ] **Step 1: Write the failing import-path tests**

```python
from tools.pico import deploy_to_pico


class DeployToPicoTests(unittest.TestCase):
    def test_runtime_code_disables_circuitpython_autoreload(self):
        code_py = Path(__file__).resolve().parents[1] / "pico" / "code.py"
        self.assertIn("supervisor.runtime.autoreload = False", code_py.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -q`
Expected: FAIL with `ModuleNotFoundError` or old import-path assertions still pointing at `pico.deploy_to_pico`

- [ ] **Step 3: Move the deploy tool and supporting assets minimally**

```python
# tools/pico/deploy_to_pico.py
def repo_root():
    return Path(__file__).resolve().parents[2]


def pico_source_dir(repo=None):
    return (repo or repo_root()) / "pico"


def pico_vendor_dir(repo=None):
    return (repo or repo_root()) / "tools" / "pico" / "vendor"
```

- [ ] **Step 4: Move/remove the old non-runtime `pico/` contents explicitly**

```text
Move:
- pico/README.md -> docs/pico/README.md
- pico/HARDWARE_SMOKE_TEST.md -> docs/pico/HARDWARE_SMOKE_TEST.md
- pico/main.py -> pico_reference/main.py
- pico/vendor/ -> tools/pico/vendor/

Delete after migration and import updates:
- pico/deploy_to_pico.py
- pico/__init__.py
```

- [ ] **Step 5: Update the tests to import the moved tool and vendor cache path**

```python
from tools.pico import deploy_to_pico


def test_runtime_libraries_downloads_into_repo_cache_then_copies_to_target():
    cached_vendor = repo / "tools" / "pico" / "vendor"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tools/pico/deploy_to_pico.py tools/pico/vendor docs/pico/README.md docs/pico/HARDWARE_SMOKE_TEST.md pico_reference/main.py tests/test_pico_deploy_to_pico.py REPO_STRUCTURE.md
git rm -r pico/vendor pico/deploy_to_pico.py pico/README.md pico/HARDWARE_SMOKE_TEST.md pico/main.py pico/__init__.py
git commit -m "refactor: move pico deploy tooling out of runtime tree"
```

### Task 2: Add Explicit Runtime Manifest And Normalized Preserve Rules

**Files:**
- Modify: `tools/pico/deploy_to_pico.py`
- Modify: `tests/test_pico_deploy_to_pico.py`

- [ ] **Step 1: Write the failing manifest and preserve tests**

```python
class DeployToPicoTests(unittest.TestCase):
    def test_desired_manifest_excludes_lcd_smoke_test(self):
        manifest = deploy_to_pico.default_runtime_manifest()
        self.assertNotIn("lcd_smoke_test.py", manifest)
        self.assertIn("code.py", manifest)

    def test_desired_target_paths_include_managed_lib_entries(self):
        source_plan = deploy_to_pico.build_source_plan(...)
        desired = deploy_to_pico.default_desired_target_paths_from_source_plan(source_plan)
        self.assertIn("code.py", desired)
        self.assertIn("lib/adafruit_hid/__init__.py", desired)
        self.assertIn("lib/adafruit_ili9341.py", desired)

    def test_preserve_match_is_case_insensitive_and_normalized(self):
        self.assertTrue(deploy_to_pico.is_preserved_path("BOOT_OUT.TXT"))
        self.assertTrue(deploy_to_pico.is_preserved_path("System Volume Information/indexerVolumeGuid"))

    def test_preserve_match_does_not_use_prefix_matching(self):
        self.assertFalse(deploy_to_pico.is_preserved_path("boot_out.txt.bak"))
        self.assertFalse(deploy_to_pico.is_preserved_path("System Volume Information-old/indexerVolumeGuid"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -k "manifest or preserve" -q`
Expected: FAIL because the new manifest/preserve helpers do not exist yet

- [ ] **Step 3: Implement the explicit manifest and normalized path helpers**

```python
DEFAULT_RUNTIME_FILES = (
    "boot.py",
    "jetson_transport.py",
    "lcd_ui.py",
    "pico_debug.py",
    "pin_config.py",
    "protocol.py",
    "runtime_runner.py",
    "upload_protocol.py",
    "serial_bridge.py",
    "typeback.py",
    "usb_config.py",
    "code.py",
)

PRESERVE_PATHS = (
    "boot_out.txt",
    "system volume information/",
    ".trashes/",
    ".spotlight-v100/",
    ".fseventsd/",
)


def normalize_target_relpath(path: str) -> str:
    return path.replace("\\", "/").strip("/").lower()


def default_runtime_manifest() -> tuple[str, ...]:
    return DEFAULT_RUNTIME_FILES


def default_preserve_paths() -> tuple[str, ...]:
    return PRESERVE_PATHS


def is_preserved_path(path: str) -> bool:
    normalized = normalize_target_relpath(path)
    ...


def default_desired_target_paths_from_source_plan(source_plan) -> set[str]:
    desired = {normalize_target_relpath(name) for name in DEFAULT_RUNTIME_FILES}
    desired.update(iter_library_target_files_from_sources(...))
    return desired
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -k "manifest or preserve" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/pico/deploy_to_pico.py tests/test_pico_deploy_to_pico.py
git commit -m "fix: add explicit pico deploy manifest"
```

### Task 3: Implement Exact-Sync Cleanup, Low-Space Handling, And Safe Copy Order

**Files:**
- Modify: `tools/pico/deploy_to_pico.py`
- Modify: `tests/test_pico_deploy_to_pico.py`

- [ ] **Step 1: Write the failing exact-sync tests**

```python
class DeployToPicoTests(unittest.TestCase):
    def test_exact_sync_removes_stale_root_file(self):
        ...

    def test_exact_sync_removes_stale_directory(self):
        ...

    def test_exact_sync_preserves_boot_out(self):
        ...

    def test_exact_sync_removes_stale_lib_package(self):
        ...

    def test_exact_sync_removes_runtime_logs(self):
        ...

    def test_exact_sync_preserves_system_volume_information_subtree(self):
        ...

    def test_exact_sync_keeps_desired_files(self):
        ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -k "exact_sync or preserves_boot_out" -q`
Expected: FAIL because cleanup helpers do not exist yet

- [ ] **Step 3: Implement desired target path expansion from resolved runtime-library sources**

```python
def iter_library_target_files_from_sources(source_paths, target_root):
    ...
    yield "lib/adafruit_hid/__init__.py"
    yield "lib/adafruit_hid/keyboard.py"
    yield "lib/adafruit_bus_device/__init__.py"
```

- [ ] **Step 4: Implement stale-path discovery and the exact cleanup helper**

```python
def exact_sync_cleanup(target_root, desired_paths, preserve_paths):
    stale_paths = find_stale_target_paths(target_root, desired_paths, preserve_paths)
    delete_stale_paths(target_root, stale_paths)
```

- [ ] **Step 5: Implement the high-level deploy ordering with `code.py` copied last**

```python
def run_deploy(target=None, library_source=None, dry_run=False):
    target_path = detect_target_path(target)
    source_plan = build_source_plan(...)
    desired_files = default_desired_target_paths_from_source_plan(source_plan)
    preserve_paths = default_preserve_paths()
    stale_paths = find_stale_target_paths(target_path, desired_files, preserve_paths)
    if not dry_run and needs_space_cleanup(target_path, source_plan, stale_paths):
        delete_stale_paths(target_path, stale_paths)
        if still_insufficient_space(target_path, source_plan):
            raise DeployError("Not enough space after stale cleanup; preserved and desired files were left untouched")
    copy_support_files_except_code_py(...)
    delete_remaining_stale_paths(...)
    copy_code_py_last(...)
```

- [ ] **Step 6: Add low-space and abort-before-cleanup tests**

```python
class DeployToPicoTests(unittest.TestCase):
    def test_run_deploy_deletes_stale_entries_first_when_space_is_low(self):
        ...

    def test_run_deploy_fails_when_space_is_still_insufficient_after_cleanup(self):
        ...

    def test_run_deploy_aborts_before_cleanup_when_library_resolution_fails(self):
        ...
```

- [ ] **Step 7: Add the partial-update failure messaging tests**

```python
class DeployToPicoTests(unittest.TestCase):
    def test_run_deploy_reports_partial_update_when_delete_fails(self):
        with self.assertRaisesRegex(DeployError, "Reconnect or reset the Pico and rerun deploy"):
            ...
        self.assertEqual(call_log, ["delete:old_script.py"])

    def test_run_deploy_reports_partial_update_when_copy_fails_after_cleanup(self):
        with self.assertRaisesRegex(DeployError, "Reconnect or reset the Pico and rerun deploy"):
            ...
        self.assertEqual(call_log, ["copy:lcd_ui.py"])
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -q`
Expected: PASS with new cleanup, preserve, low-space, and copy-order tests green

- [ ] **Step 9: Commit**

```bash
git add tools/pico/deploy_to_pico.py tests/test_pico_deploy_to_pico.py
git commit -m "fix: exact-sync pico deploy target"
```

### Task 4: Update Docs, Warnings, And Dry-Run Output

**Files:**
- Modify: `README.md`
- Modify: `docs/pico/README.md`
- Modify: `docs/pico/HARDWARE_SMOKE_TEST.md`
- Modify: `docs/WINDOWS_PICO_JETSON_BRINGUP.md`
- Modify: `documentation_reference.md`
- Modify: `docs/BRANCH_HANDOFF_2026-03-24.md`
- Modify: `docs/BRANCH_HANDOFF_2026-03-29.md`
- Modify: `ENGINEERING_SPEC.md`
- Modify: `diagram.md`
- Modify: `REPO_STRUCTURE.md`
- Modify: `lcd_screen_ui/README.md`
- Modify: `docs/plans/2026-03-25-pico-jetson-transport.md`
- Modify: `tools/pico/deploy_to_pico.py`

- [ ] **Step 1: Write the failing dry-run output test**

```python
def test_dry_run_reports_planned_deletions(capsys):
    deploy_to_pico.main(["--dry-run", "--target", str(target)])
    out = capsys.readouterr().out
    assert "Would delete" in out
    assert "Would copy" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -k dry_run -q`
Expected: FAIL because dry-run does not yet report deletions

- [ ] **Step 3: Implement minimal dry-run reporting in the deploy tool**

```python
for stale_path in stale_paths:
    action = "Would delete" if dry_run else "Deleted"
    print(f"{action}: {stale_path}")
```

```markdown
Warning: deploy now removes stale non-preserved files from `CIRCUITPY`.
Use `--dry-run` to review planned deletions and copies before mutating the board.
```

- [ ] **Step 4: Update README and Pico docs with the new command path and destructive-sync warning**

- [ ] **Step 5: Update remaining docs and reference files to the new locations and semantics**

- [ ] **Step 6: Sweep the targeted repo files for stale deploy-path and moved-doc references**

Run: `rg "pico/deploy_to_pico.py|pico/README.md|pico/HARDWARE_SMOKE_TEST.md" C:\SPARK\README.md C:\SPARK\documentation_reference.md C:\SPARK\docs\pico C:\SPARK\docs\WINDOWS_PICO_JETSON_BRINGUP.md C:\SPARK\docs\BRANCH_HANDOFF_2026-03-24.md C:\SPARK\docs\BRANCH_HANDOFF_2026-03-29.md C:\SPARK\ENGINEERING_SPEC.md C:\SPARK\diagram.md C:\SPARK\REPO_STRUCTURE.md C:\SPARK\lcd_screen_ui\README.md C:\SPARK\docs\plans\2026-03-25-pico-jetson-transport.md`
Expected: no stale references remain in the targeted live files

Run: `rg "pico/main.py|lcd_smoke_test.py" C:\SPARK\README.md C:\SPARK\documentation_reference.md C:\SPARK\docs\pico C:\SPARK\docs\WINDOWS_PICO_JETSON_BRINGUP.md C:\SPARK\docs\BRANCH_HANDOFF_2026-03-24.md C:\SPARK\docs\BRANCH_HANDOFF_2026-03-29.md C:\SPARK\ENGINEERING_SPEC.md C:\SPARK\diagram.md C:\SPARK\REPO_STRUCTURE.md C:\SPARK\lcd_screen_ui\README.md C:\SPARK\docs\plans\2026-03-25-pico-jetson-transport.md`
Expected: references either point to `pico_reference/main.py` or clearly describe that `pico/lcd_smoke_test.py` is Pico-runnable but not part of the default deploy manifest

Run: `rg "pico\.deploy_to_pico|pico/deploy_to_pico" C:\SPARK\tests C:\SPARK\README.md C:\SPARK\documentation_reference.md C:\SPARK\docs\pico C:\SPARK\docs\WINDOWS_PICO_JETSON_BRINGUP.md C:\SPARK\docs\BRANCH_HANDOFF_2026-03-24.md C:\SPARK\docs\BRANCH_HANDOFF_2026-03-29.md C:\SPARK\lcd_screen_ui\README.md`
Expected: no live code/test patch targets or docs still refer to the old module path

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -k dry_run -q`
Expected: PASS

- [ ] **Step 8: Run the full verification slice**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py tests/test_pico_code.py tests/test_pico_lcd_ui.py tests/test_pico_runtime_runner.py tests/test_watch_pico_cdc_debug.py -q`
Expected: PASS with 0 failures

- [ ] **Step 9: Commit**

```bash
git add README.md docs/pico/README.md docs/pico/HARDWARE_SMOKE_TEST.md docs/WINDOWS_PICO_JETSON_BRINGUP.md documentation_reference.md docs/BRANCH_HANDOFF_2026-03-24.md docs/BRANCH_HANDOFF_2026-03-29.md ENGINEERING_SPEC.md diagram.md REPO_STRUCTURE.md lcd_screen_ui/README.md docs/plans/2026-03-25-pico-jetson-transport.md tools/pico/deploy_to_pico.py tests/test_pico_deploy_to_pico.py
git commit -m "docs: document exact-sync pico deploy"
```
