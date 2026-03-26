# Pico Jetson Transport Implementation Plan

**Goal:** Send summarize requests from the host to Jetson through the Pico and stream the Jetson response back into the SPARK app `RELEASE OUTPUT` panel.

**Architecture:** Keep Raw HID as the host<->Pico transport. Make the Pico a transport-only UART relay with one in-flight request state machine. The host uploads a request over HID, the Pico forwards it to Jetson UART and buffers the streamed response, and the host polls that buffer over HID for partial updates.

**Tech Stack:** Python, PyQt6, CircuitPython, pyserial, Raw HID, Jetson UART bridge

---

## File Map

- Add: `C:\SPARK\pico\jetson_transport.py`
  - Transport-only helper for `payload + EOT`, `ACK` suppression, streamed response buffering, and completion state.
- Modify: `C:\SPARK\pico\upload_protocol.py`
  - Expose response-state flags and current response data to the host.
- Modify: `C:\SPARK\pico\code.py`
  - Use the new Jetson transport helper and route `FEATURE_1` requests into UART instead of local echo.
- Modify: `C:\SPARK\host_pc\raw_hid.py`
  - Parse response flags and add a polling stream helper for partial response updates.
- Modify: `C:\SPARK\spark_app_v2.py`
  - Stream partial summarize output into `RELEASE OUTPUT`.
- Test: `C:\SPARK\tests\test_pico_jetson_transport.py`
  - Cover UART framing and streamed response state.
- Test: `C:\SPARK\tests\test_pico_upload_protocol.py`
  - Cover response-info flags.
- Test: `C:\SPARK\tests\test_host_raw_hid_client.py`
  - Cover streamed polling until completion.
- Modify after verification: `C:\SPARK\README.md`, `C:\SPARK\ENGINEERING_SPEC.md`, `C:\SPARK\REPO_STRUCTURE.md`, `C:\SPARK\documentation_reference.md`, `C:\SPARK\pico\README.md`
  - Sync docs to the verified Pico<->Jetson transport behavior.

### Task 1: Pico UART Transport Helper

**Files:**
- Add: `C:\SPARK\pico\jetson_transport.py`
- Test: `C:\SPARK\tests\test_pico_jetson_transport.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_start_request_writes_payload_and_eot():
    ...


def test_poll_ignores_ack_and_appends_streamed_bytes_until_eot():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_pico_jetson_transport -v`
Expected: FAIL because the transport helper does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class JetsonTransport:
    def start_request(self, payload: bytes): ...
    def poll(self, max_chunk_size=64): ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_pico_jetson_transport -v`
Expected: PASS

### Task 2: HID Response Metadata For Streaming

**Files:**
- Modify: `C:\SPARK\pico\upload_protocol.py`
- Test: `C:\SPARK\tests\test_pico_upload_protocol.py`

- [ ] **Step 1: Write the failing test**

```python
def test_get_response_info_reports_length_chunk_count_and_flags():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_pico_upload_protocol.UploadProtocolTests.test_get_response_info_reports_length_chunk_count_and_flags -v`
Expected: FAIL because flags are not present yet.

- [ ] **Step 3: Write minimal implementation**

```python
def _handle_get_response_info(self):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_pico_upload_protocol.UploadProtocolTests.test_get_response_info_reports_length_chunk_count_and_flags -v`
Expected: PASS

### Task 3: Host Streaming HID Poller

**Files:**
- Modify: `C:\SPARK\host_pc\raw_hid.py`
- Test: `C:\SPARK\tests\test_host_raw_hid_client.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_get_response_info_parses_flags():
    ...


def test_stream_round_trip_text_emits_partial_updates_until_complete():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_host_raw_hid_client -v`
Expected: FAIL because the client cannot parse flags or poll partial updates yet.

- [ ] **Step 3: Write minimal implementation**

```python
def get_response_info(self): ...
def stream_round_trip_text(self, app_command, text, on_update): ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_host_raw_hid_client -v`
Expected: PASS

### Task 4: Wire The Pico Runtime And The App

**Files:**
- Modify: `C:\SPARK\pico\code.py`
- Modify: `C:\SPARK\spark_app_v2.py`

- [ ] **Step 1: Write the failing app-side test or narrow behavior test**

```python
def test_summarize_stream_updates_release_output_incrementally():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_summarize_stream -v`
Expected: FAIL after adding the new incremental-update expectation.

- [ ] **Step 3: Write minimal implementation**

Behavior:
- `FEATURE_1` starts a downstream Jetson request instead of local echo
- Pico main loop polls UART continuously and exposes the latest response state
- `SparkPanel._on_summarize()` clears `RELEASE OUTPUT`
- summarize worker emits partial updates while polling

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_pico_jetson_transport tests.test_pico_upload_protocol tests.test_host_raw_hid_client tests.test_summarize_stream -v`
Expected: PASS

### Task 5: Hardware Verification And Docs

**Files:**
- Modify after verification: `C:\SPARK\README.md`
- Modify after verification: `C:\SPARK\ENGINEERING_SPEC.md`
- Modify after verification: `C:\SPARK\REPO_STRUCTURE.md`
- Modify after verification: `C:\SPARK\documentation_reference.md`
- Modify after verification: `C:\SPARK\pico\README.md`

- [ ] **Step 1: Deploy firmware**

Run: `.\.venv\Scripts\python.exe .\pico\deploy_to_pico.py --target G:\`

- [ ] **Step 2: Verify live path**

Run:
- start the Jetson bridge
- start `spark_app_v2.py`
- trigger `Summarize Window`
- confirm partial text appears in `RELEASE OUTPUT`
- confirm the final response came from Jetson

- [ ] **Step 3: Sync docs**

Document:
- Raw HID remains the host<->Pico transport for summarize
- Pico forwards summarize payloads to Jetson UART
- Jetson owns prompt wrapping and summarize semantics
- partial summarize updates now appear in the host panel
