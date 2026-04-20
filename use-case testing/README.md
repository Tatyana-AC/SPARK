# Use-Case Testing

This folder holds live use-case benchmarks that exercise the real SPARK Pico -> Jetson feature paths.

## Feature 2 REFORMAT Recording

`reformat_grammar_feature2.py` measures:

- request/response latency for feature 2 `REFORMAT`
- the exact returned text from Jetson for each incorrect input sentence

The harness:

1. Loads one of the 100 incorrect sentences from `feature2_reformat_incorrect_sentences.json`
2. Sends the sentence as `CONTEXT_NEW` text so the Jetson DB has active context
3. Waits briefly for the Jetson DB to ingest that context
4. Starts the timer and sends feature 2 `REFORMAT`
5. Records the returned response text and timing in a JSON results file

## Feature 2 Dataset

`feature2_reformat_incorrect_sentences.json` contains 100 ASCII sentences. The test suite enforces:

- exactly 100 items
- each item is a non-empty string

## Run One REFORMAT Case

```powershell
python "use-case testing/reformat_grammar_feature2.py" --index 0
```

If Pico port auto-detection does not find the board, pass the port explicitly:

```powershell
python "use-case testing/reformat_grammar_feature2.py" --port COM10 --index 0
```

## Run A REFORMAT Batch

```powershell
python "use-case testing/reformat_grammar_feature2.py" --index 0 --count 10 --json
```

Use `--output` to choose a specific file. If omitted, the harness writes a timestamped JSON file under `use-case testing/results/`.

## Feature 2 Notes

- The harness uses the incorrect sentence itself as both active context and `selected_text`.
- The script does not evaluate whether the Jetson response is correct. It only records the request, the returned text, and timing.
- This is a live hardware benchmark. It does not mock Pico, UART, or the Jetson bridge.

## Feature 4 RESPOND Latency

`respond_latency_feature4.py` measures:

- TTFT: time from the framed `respond_selection` request write until the first non-empty streamed response text arrives
- Total time: time from the request write until the full response completes
- First and last response words seen from the Jetson stream

The harness:

1. Loads one of the 100 snippets from `feature4_respond_snippets.json`
2. Sends the full 20-word snippet as `CONTEXT_NEW` text over Pico CDC
3. Waits briefly for the Jetson DB to ingest that context
4. Starts the timer and sends feature 4 `RESPOND` over the Pico Raw HID upload path
5. Polls the HID response state until the streamed response completes

## Dataset

`feature4_respond_snippets.json` contains 100 ASCII snippets. The test suite enforces:

- exactly 100 items
- exactly 20 words per snippet

## Run One Snippet

```powershell
python "use-case testing/respond_latency_feature4.py" --port COM17 --index 0 --count 1
```

If Pico port auto-detection does not find the board, pass the port explicitly:

```powershell
python "use-case testing/respond_latency_feature4.py" --port COM17 --index 0 --count 1
```

## Run A Batch

```powershell
python "use-case testing/respond_latency_feature4.py" --port COM17 --index 0 --count 100 --delay 1 --json
```

## Notes

- The harness uses the snippet itself as the `previous_user_input` request text unless `--request-text` is supplied.
- `--context-settle` defaults to `0.25` seconds so the context packet can land before timing starts.
- `--count` defaults to `100`.
- `--delay` defaults to `1.0` seconds between samples.
- This is a live hardware benchmark. It does not mock Pico, UART, Raw HID, or the Jetson bridge.
