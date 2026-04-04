# Pico Deploy Exact Sync Design

## Summary

The Pico deploy flow should make `CIRCUITPY` match the repo-owned default Pico runtime exactly, while preserving a small allowlist of CircuitPython system files. The repo should also stop treating non-runtime tooling and reference material as part of the Pico runtime source tree.

## Problem

Today `pico/deploy_to_pico.py` overwrites a managed file list and managed libraries, but it does not remove arbitrary stale files already present on `CIRCUITPY`. That means the board can keep old Python modules, old tests, and old support files that no longer exist in the repo.

At the same time, the `pico/` directory mixes true on-device runtime files with non-runtime items such as deploy tooling, docs, and reference code. That weakens the contract between the repo and the board.

## Goals

- Make deploy produce an exact repo-owned default Pico runtime file set on `CIRCUITPY`
- Remove stale non-repo code and libraries from the board during deploy
- Preserve a small built-in allowlist of CircuitPython/system-generated files
- Restructure the repo so `pico/` contains only code intended to run on the Pico
- Keep the existing deploy script behavior for runtime library installation and target detection

## Non-Goals

- Changing the Pico runtime architecture itself
- Changing the standalone smoke test behavior
- Supporting arbitrary board-local Python files outside the repo-owned runtime set
- Preserving arbitrary custom files on `CIRCUITPY`

## Proposed Layout

`pico/` becomes the source of truth for Pico-runnable code only.

Rule:

- `pico/` may contain Pico-runnable files that are not part of the default deployed runtime manifest
- the default deployed runtime manifest is an explicit subset of Pico-runnable files in `pico/`
- non-runtime tooling, docs, and host-only cache content must not live under `pico/`

Files that should remain in `pico/`:

- `boot.py`
- `code.py`
- `jetson_transport.py`
- `lcd_ui.py`
- `pico_debug.py`
- `pin_config.py`
- `protocol.py`
- `runtime_runner.py`
- `serial_bridge.py`
- `typeback.py`
- `upload_protocol.py`
- `usb_config.py`

`pico/` should not keep host-only packaging helpers such as `__init__.py` once deploy tooling no longer imports it as a Python package.

Files that should move out of `pico/`:

- `deploy_to_pico.py`
- `README.md`
- `HARDWARE_SMOKE_TEST.md`
- `main.py`
- `vendor/`

Required destinations:

- move deploy tooling to `tools/pico/deploy_to_pico.py`
- move vendor cache/source content to `tools/pico/vendor/`
- move Pico docs to `docs/pico/`
- move reference code to `pico_reference/`

`pico/lcd_smoke_test.py` stays in `pico/` because it is still meant to run on the Pico, even though it is not part of the default deployed runtime manifest.

## Deploy Contract

The deploy script should compute a desired on-device manifest from an explicit allowlist, not from a recursive directory scan.

The desired on-device manifest is made of:

- all explicitly listed runtime files sourced from `pico/`
- all managed runtime libraries copied into `lib/`

The deploy script should then:

1. discover the target `CIRCUITPY` volume
2. resolve all local source files and runtime libraries before touching the device
3. compute the exact desired file set relative to the target root
4. preserve files in a small built-in allowlist
5. compute stale target entries that are neither desired nor preserved
6. if free space is insufficient for the incoming copy set, delete stale target entries first while leaving desired entries and preserved entries untouched
7. copy all runtime support files and managed libraries except `code.py`
8. delete any remaining stale target entries that are neither desired nor preserved
9. copy `code.py` last so any reload sees the fully updated runtime set

If local source resolution or runtime library preparation fails, deploy must abort before deleting anything from `CIRCUITPY`.

This preserves the current safety goal of writing `code.py` last and avoids rebooting into a partially updated runtime.

Low-space strategy:

- precompute the incoming copy set size after source resolution
- estimate free space on `CIRCUITPY`
- if free space is too small, delete only stale entries first to free space
- never delete preserved entries to make room
- never delete desired entries to make room

## Failure Semantics

Exact-sync deploy is not transactional on `CIRCUITPY`.

- If a copy or delete operation fails after device mutation has started, deploy should stop immediately and raise a clear error.
- The board should be treated as being in an unknown partial-update state after such a failure.
- The error message should tell the user to reconnect or reset the Pico and rerun deploy.
- The deploy script should not attempt rollback on-device.

The goal is predictable failure handling, not a fake transactional guarantee.

## Preserve Policy

User-approved preservation rule: keep system files, not arbitrary extras.

Preserve entries are exact normalized target-root-relative matches.

- path normalization uses forward-slash separators and lowercase comparison so FAT-backed `CIRCUITPY` behaves consistently across Windows, macOS, and Linux hosts
- exact file preserve: match the full normalized relative file name only
- exact directory preserve: match the normalized directory name and preserve the full subtree below it

Initial preserve allowlist:

- `boot_out.txt`
- `System Volume Information/`
- `.Trashes/`
- `.Spotlight-V100/`
- `.fseventsd/`

Optional future preserve entries can be added deliberately if the workflow needs them, but the default should stay strict.

Transient runtime log files created by the firmware are not preserved.

Examples:

- `runtime_error.txt`
- `startup_trace.txt`
- `uart_diag.txt`

Those files are considered disposable runtime artifacts and should be removed on the next exact-sync deploy if present.

## Deletion Semantics

The cleanup pass should remove:

- stale root files of any type that are not part of the desired manifest and are not preserved
- stale directories not part of the desired runtime manifest
- stale `lib/` packages or modules not in the managed runtime library set
- stale copies of repo files that were moved or renamed

The cleanup pass should not remove:

- files on the preserve allowlist

## Testing Strategy

Add or update deploy tests to cover:

- stale root file removal
- stale directory removal
- stale `lib/` package removal
- preserve allowlist behavior for `boot_out.txt`
- preserve allowlist behavior for exact directory preserves such as `System Volume Information/`
- runtime log files are deleted on the next deploy
- exact desired file retention after sync
- `code.py` copied last
- deploy aborts before cleanup when required source inputs are unavailable
- mid-deploy delete/copy failure stops immediately and surfaces a partial-update warning
- low-space deploy deletes stale entries first when needed
- repo layout assumptions for runtime files versus moved non-runtime files

## Migration Notes

- update every caller/reference that uses the old `pico/deploy_to_pico.py` path, including tests, docs, bring-up notes, and README examples
- any references to `pico/main.py` or `pico/lcd_smoke_test.py` as runtime files must be corrected after the move
- the deploy script should continue to support the current runtime library install flow so board setup does not regress
- keep `pico/lcd_smoke_test.py` runnable without changing its current on-device workflow semantics
- the deploy help text and docs must explicitly warn that deploy now removes stale non-preserved files from `CIRCUITPY`
- `--dry-run` output must show planned deletions as well as planned copies so the destructive behavior is inspectable before execution

Known migration inventory to update:

- `tests/test_pico_deploy_to_pico.py`
- `README.md`
- `pico/README.md` if retained as a historical stub or redirect
- `docs/WINDOWS_PICO_JETSON_BRINGUP.md`
- `documentation_reference.md`
- `docs/BRANCH_HANDOFF_2026-03-29.md`
- `ENGINEERING_SPEC.md`
- `diagram.md`
- `REPO_STRUCTURE.md`
- `lcd_screen_ui/README.md`
- `docs/plans/2026-03-25-pico-jetson-transport.md`
- any smoke-test or LCD workflow docs that point at the old deploy path

## Recommended Implementation Order

1. move non-runtime files out of `pico/` while keeping `lcd_smoke_test.py` in place
2. move the deploy tool to `tools/pico/deploy_to_pico.py` and vendor cache/source content to `tools/pico/vendor/`
3. update deploy-script path references in docs/tests/scripts
4. add explicit runtime manifest and normalized path handling
5. add exact-sync cleanup logic with low-space handling and `code.py` copied last
6. add preserve allowlist behavior and runtime-log cleanup behavior
7. add regression tests for cleanup and exact-sync semantics

## Success Criteria

- after deploy, `CIRCUITPY` contains only repo-owned default runtime files plus preserved system files
- stale non-repo files no longer survive deploy unless explicitly preserved
- `pico/` contains only code intended to run on the Pico
- tests verify both cleanup behavior and preserve behavior
