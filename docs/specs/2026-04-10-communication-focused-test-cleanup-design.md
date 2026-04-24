# Communication-Focused Test Cleanup Design

Date: 2026-04-10

## Goal

Reduce the automated test suite to the minimum set that directly protects communication correctness and end-to-end startup/smoke behavior.

The suite should stop trying to prove broad implementation details and instead answer a small number of concrete questions about whether messages move across the three-node system correctly.

## Problem

The current suite passes too often while real communication failures still happen.

The main cause is not lack of total test count. It is the shape of the coverage:

- too many tests assert mocked method calls, import order, or implementation details
- too few tests protect the actual communication boundaries that fail in practice
- the most realistic acceptance path is the PowerShell setup/smoke flow, but too many Python tests provide false confidence around adjacent helper behavior

## Principle

Only keep tests that directly protect one of these four outcomes:

1. a host context or polling-style message reaches the Jetson side and is stored correctly
2. a Pico-side button/request reaches the Jetson-side handler correctly
3. a Jetson response or error packet is parsed and surfaced correctly on the return path
4. `setup_spark.ps1` can refresh the stack and pass the real smoke loop

Malformed packet rejection is in scope only where it directly protects those communication outcomes by preventing bad inbound traffic from being misinterpreted as valid communication. It is not a separate fifth coverage area.

If a test does not materially protect one of those outcomes, it should be deleted.

## Keep Set

### Python

Keep one composed integration test as the anchor:

- `tests/test_context_stream_e2e.py`

Keep only minimal communication-contract tests beyond that anchor:

- `tests/test_pico_jetson_transport.py`
  - reduce to request-forward, first-response, timeout/error communication behavior only
- `tests/test_jetson_protocol.py`
  - reduce to malformed inbound packet rejection behavior that protects real communication parsing
- one minimal return-path test
  - this is required
  - it can stay in an existing file if it directly protects response/error delivery back out of the communication layer

### PowerShell

Keep `tests/setup_spark.Tests.ps1`, but only for setup-critical behavior that affects whether the real smoke loop can run:

- deploy target selection
- app relaunch behavior
- smoke recovery behavior
- Jetson mount/path behavior only where it affects whether setup can proceed

## Delete Set

Delete aggressively when tests are primarily about implementation detail rather than communication behavior.

Decision rule for borderline tests:

- if removing the test would leave one of the four required communication outcomes unprotected, keep or rewrite it
- otherwise delete it

Expected deletions include:

- `tests/test_tools/monitoring/watch_full_stack.py`
- `tests/test_spark_panel_ui.py`
- most import/bootstrap/order tests
- setup-script tests that inspect source text instead of behavior
- tests whose main assertion is that a mock was called rather than that data arrived or was rejected correctly

This is intentionally aggressive. The suite should become smaller and more trustworthy, not broader.

## Cleanup Strategy

Do the work in two passes.

### Pass 1: trim and sharpen the tests that remain

For each kept test file:

- delete cases that do not directly protect the communication contract
- rewrite cases that are too indirect or too implementation-specific
- keep only behavior-level assertions tied to message framing, transport state, DB handoff, response parsing, or smoke startup/recovery

### Pass 2: delete the rest

After the kept tests are trimmed and passing, remove the entire files that no longer fit the communication-focused scope.

This order prevents a temporary coverage hole where the broad tests are gone before the minimal contract set is stable.

## Required Remaining Coverage

### Host/Polling to Jetson DB

The suite must include a Python test that sends a context/polling-style host message using the real serialization path and confirms the Jetson-side DB receives the expected state.

The existing `tests/test_context_stream_e2e.py` is the preferred place for this.

One representative host-to-Jetson path is sufficient if context and polling messages share the same serialization and handling path in the current code. If they diverge into materially different paths, the kept suite must cover both.

### PB1/Pico Request to Jetson

The suite must include a Python test that protects the Pico-to-Jetson request transport contract.

This does not need to prove the whole UI flow. It needs to prove one observable communication outcome: a PB1-style request is framed, received, parsed, and reaches the Jetson-side handling boundary with the expected request semantics.

The surviving test must assert an observable effect beyond "a mock was called". Acceptable boundaries include:

- parsed request state on the transport object
- a button event recorded on the Jetson-side DB
- a request handed into the real Jetson-side handler path and reflected in durable state

### Jetson Response/Error Return Path

The suite must include a Python test that protects response/error packet parsing and surfacing on the return path.

This can live in a trimmed transport or host client test, but it must remain a communication test, not a UI orchestration test.

The surviving return-path coverage must include both:

- one successful response-path assertion
- one error-path assertion

### Real Acceptance Test

`setup_spark.ps1` smoke remains the primary real-system acceptance test.

It is the final authority for:

- fresh deployment
- fresh app launch
- Jetson service readiness
- actual summarize round-trip success

PowerShell unit tests do not need to prove the summarize round-trip itself. That remains the responsibility of the real smoke run. The PowerShell test file only needs to protect setup behaviors that determine whether the smoke run can start from a fresh state.

## What Will Be Removed Deliberately

The cleanup intentionally stops protecting some areas through unit tests:

- watcher helper implementation details
- Spark app UI wiring details
- import order/bootstrap sequencing
- script source-text patterns
- mock-only choreography between helpers

If these matter, they must be protected through communication-level tests or the setup/smoke path, not through a growing unit suite of internal details.

## Verification After Cleanup

After the cleanup:

1. run the kept Python communication tests only
2. run `tests/setup_spark.Tests.ps1`
3. run the real `setup_spark.ps1` smoke flow once

Success means:

- the trimmed suite is materially smaller
- the remaining tests map directly to communication correctness
- the real smoke path still passes

"Materially smaller" means the suite contains only the explicitly named keep-set files plus any unavoidable minimal return-path file, and no watcher-specific or UI-detail Python test files remain.

## Recommendation

Aggressively delete low-value tests and keep only a minimal communication-focused suite plus the real setup/smoke acceptance path.

The test suite should become a smaller instrument panel that tracks whether the system can actually communicate, not a large collection of green checks that mostly validate local implementation details.
