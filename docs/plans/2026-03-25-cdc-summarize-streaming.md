# HID Summarize Round-Trip Plan

## Scope

Implement the smallest verified bidirectional path between the host app and the Pico,
ignoring Jetson for now.

The approved design is:

- use Raw HID as the host<->Pico request/response channel
- keep USB CDC out of the summarize path for now
- make `Summarize Window` send a prompt to the Pico
- have the Pico return a device-generated response
- show that response in the host app `RELEASE OUTPUT` panel

## Why This Plan Replaced The Earlier CDC Version

The original CDC/Jetson plan was abandoned for this pass because live hardware testing
showed that the current Windows/CircuitPython CDC path was not reliable for host->Pico
reads, while Raw HID was already present and partially working.

The goal of this iteration is not real model summarization. The goal is to prove a
working bidirectional app<->Pico transport and wire that into the existing UI.

## File Map

- Modify: `C:\SPARK\host_pc\raw_hid.py`
  - Add response-buffer reads and a simple round-trip helper.
- Modify: `C:\SPARK\pico\upload_protocol.py`
  - Add device response metadata and chunk-read commands.
- Modify: `C:\SPARK\pico\code.py`
  - Return a simple Pico-generated echo response for the summarize request.
- Modify: `C:\SPARK\spark_app_v2.py`
  - Replace the summarize placeholder with a HID-backed round trip that updates
    `RELEASE OUTPUT`.
- Add: `C:\SPARK\host_pc\summarize_stream.py`
  - Centralize summarize prompt construction.
- Test: `C:\SPARK\tests\test_host_raw_hid_client.py`
  - Cover response metadata reads, response chunk reads, and round-trip behavior.
- Test: `C:\SPARK\tests\test_pico_upload_protocol.py`
  - Cover storage and retrieval of the device response buffer.
- Test: `C:\SPARK\tests\test_summarize_stream.py`
  - Cover summarize prompt generation.
- Modify after verification: `C:\SPARK\README.md`, `C:\SPARK\ENGINEERING_SPEC.md`,
  `C:\SPARK\REPO_STRUCTURE.md`, `C:\SPARK\documentation_reference.md`,
  `C:\SPARK\pico\README.md`
  - Sync docs to the verified HID-only behavior.

## Execution Plan

### Task 1: Add Host Readback Commands

- Add `GET_RESPONSE_INFO` and `GET_RESPONSE_CHUNK` to the host Raw HID client.
- Implement a host helper that:
  - uploads text
  - waits for success
  - reads the Pico response buffer back as UTF-8 text

### Task 2: Add Pico Response Buffer Support

- Extend the Pico upload protocol handler to:
  - store a response buffer after `COMMIT_UPLOAD`
  - report total response length and chunk count
  - return individual response chunks on request

### Task 3: Wire Summarize Window To HID

- Build a summarize prompt from:
  - active application name
  - active window title
  - extracted window text
- Clear `RELEASE OUTPUT` when summarize starts.
- Send the prompt with `FEATURE_1`.
- Read the Pico response and show it in `RELEASE OUTPUT`.

### Task 4: Verify On Real Hardware

- Deploy the updated CircuitPython firmware to the Pico.
- Verify:
  - `GET_INFO` works
  - a text round trip works against the real Pico
  - the host app code path compiles and launches

## Verified Outcome

This plan is now implemented and verified at the transport level.

Verified behavior:

- the host can upload text to the Pico over Raw HID
- the Pico stores a device response buffer
- the host can read that response back over Raw HID
- the real hardware round-trip returns `PICO ECHO: ...`
- `Summarize Window` now uses that same HID round-trip path

Still out of scope:

- Jetson-backed summarization
- streaming token output
- USB CDC as the primary summarize transport
