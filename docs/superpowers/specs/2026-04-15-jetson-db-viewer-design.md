# Jetson DB Viewer Design

## Summary

Add a host-side debug viewer to `spark_app_v2.py` that lets the user inspect the full Jetson database without opening the live SQLite file on the `Z:\` share directly. The viewer should always copy the Jetson DB to a local temporary snapshot first, validate and open that snapshot only, then read it in a dedicated read-only UI with manual refresh.

## Context

SPARK's authoritative context database now lives on the Jetson side as `jetson_spark.db`, deployed under the mounted share path `Z:\demo\pico_bridge\jetson_spark.db`. The current host app still has a `Show History` action, but that only reflects host-side tracker history and does not expose the real Jetson-side database state.

For debugging transport and persistence issues, the user needs to see the actual database contents being written by the host -> Pico -> Jetson path. At the same time, the viewer must not add instability by opening or locking the live DB file while the Jetson bridge is writing to it.

## Problem Statement

The host app lacks a safe way to inspect the Jetson-owned SQLite database during live debugging. Directly opening the live DB over the network share risks file-locking and read-consistency problems, while the current host-side history UI is not an accurate representation of Jetson persistence.

## Goals

- Expose the full Jetson database contents from within the SPARK host app, including schema discovery for new tables.
- Avoid reading the live SQLite file directly from the UI.
- Keep refresh under explicit user control.
- Make the tool useful for debugging DB writes, active sessions, and button-event linkage.
- Fail safely when the `Z:\` share or DB file is unavailable.

## Non-Goals

- Editing the Jetson database from the host UI.
- Adding auto-refresh or background polling in the first pass.
- Changing the Jetson DB schema or host-to-Jetson payload format.
- Replacing external SQLite tools for advanced ad hoc querying.

## Approaches Considered

### 1. Recommended: embedded snapshot-based viewer in the SPARK app

Add a new `View Jetson DB` action that copies `Z:\demo\pico_bridge\jetson_spark.db` to a local temp file, opens the snapshot with SQLite, and renders the tables in a dedicated dialog or window. Every refresh repeats the copy-and-reload cycle.

This is the best debugging and stability tradeoff because it keeps the workflow inside SPARK while never holding the live DB open.

### 2. Open an external SQLite app on a copied snapshot

The host app could copy the DB to a temp file and ask the OS to open that file in the user's SQLite application.

This is low implementation effort, but it depends on external tooling being installed and provides a less integrated workflow.

### 3. Read the live DB directly from `Z:\`

The host app could connect to `Z:\demo\pico_bridge\jetson_spark.db` and query it in place.

This is the simplest implementation, but it has the worst safety profile and is not acceptable for the user's stability requirement.

## Chosen Approach

Implement an in-app viewer that always reads from a local snapshot copied from the Jetson share. Refresh remains manual.

## Design

### 1. User Entry Point

`spark_app_v2.py` should add a distinct `View Jetson DB` action rather than repurposing `Show History`. The existing history action serves a different purpose and should remain host-local.

The new action should open a dedicated viewer dialog or secondary window suitable for debugging rather than overloading the capture feed.

### 2. Snapshot Lifecycle

When the viewer opens or the user presses `Refresh`, the host app should:

1. resolve the live DB path, initially defaulting to `Z:\demo\pico_bridge\jetson_spark.db`
2. copy that file to a local temp directory using a unique snapshot filename
3. validate the copied snapshot by opening the copy only and confirming it can be queried cleanly
4. close any prior snapshot DB connection before loading the new copy into the viewer
5. query the new snapshot only

The app must never keep a SQLite connection open against the live `Z:\` path.

The snapshot file may be replaced on every refresh instead of trying to reuse one file in place. This keeps the lifecycle simple and avoids stale-handle edge cases.

The refresh path should include lightweight retry behavior for transient copy/open failures. If the copied file cannot be validated, the app should discard that snapshot, retry a small bounded number of times, and only then surface a refresh failure.

The viewer must also clean up temp snapshots. After a new snapshot loads successfully, the previously active snapshot file should be deleted if possible. On viewer close, the active snapshot should also be removed. Cleanup failures should be logged but must not break the UI.

Snapshot copy and load work should run off the UI thread so a slow `Z:\` read or retry loop does not freeze the rest of the host app.

Snapshot validation should be explicit. A copied file is only considered usable if it is non-empty, can be opened via SQLite in explicit read-only mode, can return table metadata from `sqlite_master`, and passes `PRAGMA integrity_check`. Failed validation must not be promoted into the viewer.

Failed or abandoned snapshot files must be deleted in `finally`-style cleanup paths so repeated transient failures do not accumulate temp artifacts.

Refresh must be single-flight. While a refresh worker is running, the `Refresh` action should be disabled or ignored. The controller should track the currently active refresh request so stale worker completions cannot overwrite a newer snapshot or update a viewer that has already been closed.

### 3. Viewer Scope

The first pass should expose the complete contents of the current Jetson schema, not just the currently expected tables.

The viewer should discover tables from the snapshot database itself, using the current schema as the source of truth. The table selector must be populated from discovered user tables rather than a hardcoded list. In the standard case this will include:

- `sessions`
- `button_events`

If additional tables exist, they should still be listed and inspectable in the viewer rather than hidden.

The UI should support switching between tables and inspecting all columns for each row. For `sessions`, this includes `context_key`, `content_fingerprint`, `app_name`, `window_title`, `process_name`, `pid`, `source`, `tab_title`, `url`, `text`, `host_observed_at`, `started_at`, and `updated_at`.

The default landing view should be `sessions`, ordered newest first when present. `button_events` should also be shown newest first. For unknown tables, the viewer may fall back to rowid-desc or schema-default ordering if no obvious timestamp column exists.

### 4. Read-Only Debug UI

The UI should be explicitly read-only. The first pass does not need sorting, filtering, or inline SQL execution. It only needs enough structure to inspect the latest rows reliably.

Recommended minimal UI elements:

- table selector built from discovered user tables, with `sessions` selected by default when present
- row grid for the selected table
- refresh button
- status text showing the live DB path, snapshot path, row count, and last refresh time
- error banner or status line for snapshot/copy/query failures

Long text columns such as `text` and `content_fingerprint` should remain accessible, even if the table truncates the displayed preview. A detail pane or full-cell expansion behavior is acceptable if needed to keep the table readable.

To keep the viewer responsive on larger datasets, tables should load with a pragmatic bounded query by default, such as the most recent rows first with a fixed initial limit. The UI should make that explicit and provide a clear path to inspect older rows, such as `Load More` and optionally `Load All` for an intentional deep-dive. Loading the full result set eagerly into the UI is not required.

### 5. Error Handling

Expected failures include:

- `Z:\` share missing
- `jetson_spark.db` missing
- copy failure while the share is temporarily unavailable
- snapshot open/query failure due to a partial or corrupt copy

These failures should be contained to the viewer. They must not block polling, HID actions, serial context sending, or the rest of the host app UI.

The viewer should surface a clear status message and keep the last successfully loaded snapshot visible if a refresh fails after at least one successful load.

The viewer should distinguish between source-path failures and snapshot-validation failures so debugging output makes it clear whether the problem was share access, copy, or SQLite readability.

If a refresh is in progress when the viewer closes, the completion result should be ignored and any abandoned snapshot artifact should still be cleaned up.

### 6. Configuration Surface

The first pass may hardcode the live DB path to the documented bring-up location `Z:\demo\pico_bridge\jetson_spark.db`, provided the implementation keeps the path centralized so it can become configurable later if needed.

No Jetson-side changes are required.

### 7. Testing

The implementation should follow TDD and cover the snapshot behavior rather than relying on manual UI-only verification.

Required automated coverage:

- path/copy logic for creating a local snapshot from a source DB path
- schema discovery and read-only query loading for both `sessions` and `button_events`, plus unknown tables
- graceful error behavior when the live DB path is missing or the copy fails
- snapshot validation and bounded retry behavior after partial-copy/open failures
- temp snapshot cleanup on refresh and close
- single-flight viewer/controller refresh behavior proving it reloads from a fresh snapshot rather than reusing a live DB connection, and ignores stale worker completions
- tests that assert SQLite connections are only opened against the local snapshot path, never directly against `Z:\demo\pico_bridge\jetson_spark.db`
- tests that assert snapshot connections use explicit read-only mode

UI tests should stay focused on observable behavior, such as status text and table population, rather than pixel-level details.

## Data Flow

1. user clicks `View Jetson DB`
2. host app copies live DB from `Z:\demo\pico_bridge\jetson_spark.db` to a local temp snapshot
3. host app validates the copied snapshot and retries if needed
4. host app opens the validated snapshot with SQLite
5. viewer discovers available tables and queries the selected one
6. user inspects rows
7. user clicks `Refresh` when they want a new snapshot

## Open Assumptions

- The Jetson share remains mounted at `Z:\` in the standard Windows bring-up flow.
- Copying the SQLite file is an acceptable and materially safer debugging strategy than reading the live DB directly.
- `sessions` and `button_events` remain the main tables of interest, but the viewer should not assume they are the only tables present.

## Testing Strategy

- Add focused unit tests around snapshot creation and DB loading helpers.
- Add a targeted UI/controller test for manual refresh and failure messaging.
- Do one manual smoke check against a real `Z:\demo\pico_bridge\jetson_spark.db` after automated tests pass.
