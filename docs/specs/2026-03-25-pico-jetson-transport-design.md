# Pico Jetson Transport Design

## Goal

Turn the current host<->Pico HID summarize round-trip into a real
host->Pico->Jetson->Pico->host path while keeping the Pico transport-only.

The host should still talk to the Pico over Raw HID. The Pico should forward
the summarize payload to Jetson over UART, collect the streamed Jetson response,
and expose the growing response buffer back to the host through the existing HID
response-read mechanism.

## Boundaries

- Host owns UI, active-window extraction, and HID upload/polling.
- Pico owns transport only:
  - forward request bytes to Jetson UART
  - track one in-flight response
  - buffer returned bytes
- Jetson owns command interpretation, prompt wrapping, system prompt use,
  and future button-command semantics.

## Data Flow

1. The host builds a summarize request from the active window.
2. The host uploads that request to the Pico using Raw HID `FEATURE_1`.
3. Pico accepts the request and immediately forwards the UTF-8 payload to Jetson
   over UART, followed by `EOT`.
4. Jetson bridge replies with:
   - `ACK`
   - streamed UTF-8 text chunks
   - final `EOT`
5. Pico drops the initial `ACK`, appends streamed bytes into its response buffer,
   and marks the response complete on `EOT`.
6. The host polls the Pico response metadata over HID, fetches the current
   response bytes, and updates `RELEASE OUTPUT` incrementally until completion.

## Protocol Changes

The Raw HID response-read commands stay in place:

- `GET_RESPONSE_INFO`
- `GET_RESPONSE_CHUNK`

`GET_RESPONSE_INFO` needs one new field:

- response state flags
  - bit 0: response complete
  - bit 1: downstream request active

This lets the host distinguish:

- no response yet
- partial streamed response
- completed response

## Pico Runtime Design

Add a focused UART transport helper rather than putting state directly into
`code.py`.

Responsibilities:

- start one downstream request at a time
- clear the old response buffer when a new request begins
- write `payload + EOT` to UART
- consume UART bytes in the main loop
- ignore leading `ACK`
- append streamed bytes to an internal response buffer
- mark completion on `EOT`
- expose:
  - current response bytes
  - whether a request is active
  - whether the response is complete

This keeps `code.py` thin and makes the framing behavior testable.

## Host Design

Extend the Raw HID client with:

- `get_response_info()`
- `fetch_response_bytes()` or equivalent current-buffer read
- `stream_round_trip_text(...)`

`stream_round_trip_text(...)` should:

1. upload the request
2. poll response info on a short interval
3. fetch the current buffered text whenever the total length changes
4. emit partial text updates to the caller
5. stop when the Pico reports completion

The Qt app should use that path for `Summarize Window` so the panel shows
partial output instead of waiting for the final full response.

## Error Handling

- If the Pico already has an active downstream request, new summarize uploads
  should be rejected with `BUSY`.
- If Jetson never responds, the host should time out and keep any partial text.
- If Jetson sends an error message as plain text, Pico transports it unchanged.
- If no bytes arrive before timeout, the host should surface a summarize error.

## Testing

Required coverage:

- Pico transport helper:
  - writes `payload + EOT`
  - ignores `ACK`
  - accumulates streamed bytes
  - marks complete on `EOT`
  - resets correctly for a new request
- Upload protocol:
  - response info exposes flags
  - response chunk reads return the current buffer
- Host HID client:
  - parses response-info flags
  - polls until completion
  - emits incremental updates
- App summarize path:
  - clears `RELEASE OUTPUT`
  - streams partial updates
  - re-enables the button on completion/error

## Verification Target

The pass is complete only when:

- the Pico is deployed with the new transport helper
- the Jetson bridge is running
- a summarize request from the host reaches Jetson
- streamed Jetson bytes appear in the SPARK `RELEASE OUTPUT` panel
- no keyboard type-back is involved
