from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.protocol import build_context_new
from host_pc.raw_hid import AppCommand, SparkHIDClient, SparkProtocolError
from host_pc.serial_sender import DEFAULT_BAUD, SerialSender
from host_pc.summarize_stream import build_respond_request


USE_CASE_DIR = Path(__file__).resolve().parent
DEFAULT_SNIPPET_PATH = USE_CASE_DIR / "feature4_respond_snippets.json"
DEFAULT_CONTEXT_APP_NAME = "UseCaseTesting"
DEFAULT_CONTEXT_WINDOW_TITLE = "Feature 4 RESPOND Latency"
DEFAULT_CONTEXT_PROCESS_NAME = "respond_latency_feature4.py"
DEFAULT_CONTEXT_SOURCE = "full_window"
DEFAULT_CONTEXT_TAB_TITLE = "RESPOND latency"
DEFAULT_CONTEXT_URL = None
DEFAULT_CONTEXT_PID = 0
DEFAULT_CONTEXT_SETTLE_S = 0.25
DEFAULT_SAMPLE_COUNT = 100
DEFAULT_INTER_SAMPLE_DELAY_S = 1.0
DEFAULT_HID_POLL_INTERVAL_S = 0.01


@dataclass
class RespondLatencyResult:
    snippet_index: int
    snippet: str
    request_text: str
    response_text: str
    ttft_s: float | None
    total_time_s: float
    first_word: str
    last_word: str
    error: str | None = None


class RespondTimingRecorder:
    def __init__(self, request_sent_at: float):
        self.request_sent_at = float(request_sent_at)
        self._response_text = ""
        self._first_chunk_at: float | None = None
        self._terminal_at: float | None = None
        self._error: str | None = None

    def observe_text(self, text: str, *, received_at: float) -> None:
        self._response_text = text or ""
        if self._first_chunk_at is None and self._response_text.strip():
            self._first_chunk_at = float(received_at)

    def observe_chunk(self, text: str, *, received_at: float) -> None:
        self.observe_text(self._response_text + (text or ""), received_at=received_at)

    def observe_error(self, message: str, *, received_at: float) -> None:
        self._error = message or "[ERROR] Unknown bridge error"
        self._terminal_at = float(received_at)

    def finish(self, *, received_at: float) -> RespondLatencyResult:
        self._terminal_at = float(received_at)
        return self.build_result()

    def build_result(
        self,
        *,
        snippet_index: int = -1,
        snippet: str = "",
        request_text: str = "",
    ) -> RespondLatencyResult:
        if self._terminal_at is None:
            raise ValueError("Cannot build a result before a terminal packet is received.")

        words = self._response_text.split()
        first_word = words[0] if words else ""
        last_word = words[-1] if words else ""
        ttft_s = None
        if self._first_chunk_at is not None:
            ttft_s = self._first_chunk_at - self.request_sent_at

        return RespondLatencyResult(
            snippet_index=snippet_index,
            snippet=snippet,
            request_text=request_text,
            response_text=self._response_text,
            ttft_s=ttft_s,
            total_time_s=self._terminal_at - self.request_sent_at,
            first_word=first_word,
            last_word=last_word,
            error=self._error,
        )


def _word_count(text: str) -> int:
    return len((text or "").split())


def validate_snippets(snippets: list[str], *, expected_count: int = 100, expected_word_count: int = 20) -> None:
    if len(snippets) != expected_count:
        raise ValueError(f"Expected {expected_count} snippets but found {len(snippets)}.")

    for index, snippet in enumerate(snippets):
        if not isinstance(snippet, str):
            raise ValueError(f"Snippet {index} is not a string.")
        word_count = _word_count(snippet)
        if word_count != expected_word_count:
            raise ValueError(
                f"Snippet {index} must contain exactly {expected_word_count} words; found {word_count}."
            )


def load_snippets(path: Path = DEFAULT_SNIPPET_PATH) -> list[str]:
    snippets = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snippets, list):
        raise ValueError("Snippet file must contain a JSON array.")
    validate_snippets(snippets)
    return snippets


def _build_context_payload(snippet: str) -> dict[str, Any]:
    return {
        "app_name": DEFAULT_CONTEXT_APP_NAME,
        "window_title": DEFAULT_CONTEXT_WINDOW_TITLE,
        "process_name": DEFAULT_CONTEXT_PROCESS_NAME,
        "pid": DEFAULT_CONTEXT_PID,
        "source": DEFAULT_CONTEXT_SOURCE,
        "tab_title": DEFAULT_CONTEXT_TAB_TITLE,
        "url": DEFAULT_CONTEXT_URL,
        "text": snippet,
        "timestamp": time.time(),
    }


def _open_serial(port: str | None, baud: int):
    try:
        import serial
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("pyserial is required to run the live RESPOND latency harness.") from exc

    selected_port = port or SerialSender._find_pico_port()
    if not selected_port:
        raise RuntimeError("Could not auto-detect a Pico CDC port. Pass --port explicitly.")
    return serial.Serial(selected_port, baud, timeout=0.05, write_timeout=2.0)


def _wait_for_context_settle(delay_s: float) -> None:
    if delay_s > 0:
        time.sleep(delay_s)


def _send_context(ser, snippet: str) -> None:
    ser.write(build_context_new(_build_context_payload(snippet)))
    ser.flush()


def _wait_for_hid_idle(
    client: SparkHIDClient,
    *,
    max_wait_s: float,
    poll_interval_s: float = DEFAULT_HID_POLL_INTERVAL_S,
) -> None:
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        info = client.get_response_info()
        if not info.active:
            return
        time.sleep(poll_interval_s)
    raise TimeoutError(f"Timed out waiting {max_wait_s:.2f}s for the previous HID response to become idle.")


def run_feature4_latency_test(
    *,
    snippet: str,
    request_text: str | None = None,
    port: str | None = None,
    baud: int = DEFAULT_BAUD,
    timeout_s: float = 30.0,
    context_settle_s: float = DEFAULT_CONTEXT_SETTLE_S,
    snippet_index: int = -1,
    hid_client: SparkHIDClient | None = None,
    hid_poll_interval_s: float = DEFAULT_HID_POLL_INTERVAL_S,
) -> RespondLatencyResult:
    request_payload = build_respond_request(request_text or snippet)
    recorder = RespondTimingRecorder(request_sent_at=0.0)
    owns_client = hid_client is None
    client = hid_client or SparkHIDClient()

    if not client.is_connected():
        raise RuntimeError("SPARK Raw HID interface is not connected.")

    try:
        _wait_for_hid_idle(client, max_wait_s=timeout_s, poll_interval_s=hid_poll_interval_s)

        with _open_serial(port, baud) as ser:
            if hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
            _send_context(ser, snippet)
            _wait_for_context_settle(context_settle_s)

        def on_update(text: str) -> None:
            recorder.observe_text(text, received_at=time.perf_counter())

        recorder.request_sent_at = time.perf_counter()
        response_text = client.stream_round_trip_text(
            AppCommand.FEATURE_4,
            request_payload,
            on_update=on_update,
            timeout_ms=max(1, int(timeout_s * 1000)),
            poll_interval_s=hid_poll_interval_s,
        )
        now = time.perf_counter()
        recorder.observe_text(response_text, received_at=now)
        recorder.finish(received_at=now)
        return recorder.build_result(
            snippet_index=snippet_index,
            snippet=snippet,
            request_text=request_payload,
        )
    except SparkProtocolError as exc:
        recorder.observe_error(str(exc), received_at=time.perf_counter())
        return recorder.build_result(
            snippet_index=snippet_index,
            snippet=snippet,
            request_text=request_payload,
        )
    finally:
        if owns_client:
            client.close()


def _format_result(result: RespondLatencyResult) -> str:
    lines = [
        f"snippet_index={result.snippet_index}",
        f"snippet={result.snippet}",
        f"request_text={result.request_text}",
        f"ttft_s={result.ttft_s if result.ttft_s is not None else 'n/a'}",
        f"total_time_s={result.total_time_s}",
        f"first_word={result.first_word}",
        f"last_word={result.last_word}",
        f"response_text={result.response_text}",
    ]
    if result.error:
        lines.append(f"error={result.error}")
    return "\n".join(lines)


def _result_from_exception(
    *,
    snippet_index: int,
    snippet: str,
    request_text: str,
    start_at: float,
    exc: Exception,
) -> RespondLatencyResult:
    end_at = time.perf_counter()
    return RespondLatencyResult(
        snippet_index=snippet_index,
        snippet=snippet,
        request_text=request_text,
        response_text="",
        ttft_s=None,
        total_time_s=end_at - start_at,
        first_word="",
        last_word="",
        error=str(exc),
    )


def _run_batch(
    *,
    snippets: list[str],
    start_index: int,
    count: int,
    inter_sample_delay_s: float = DEFAULT_INTER_SAMPLE_DELAY_S,
    time_sleep=time.sleep,
    **kwargs: Any,
) -> list[RespondLatencyResult]:
    selected = snippets[start_index : start_index + count]
    results: list[RespondLatencyResult] = []
    hid_client = SparkHIDClient()
    if not hid_client.is_connected():
        raise RuntimeError("SPARK Raw HID interface is not connected.")

    try:
        for offset, snippet in enumerate(selected):
            snippet_index = start_index + offset
            sample_start = time.perf_counter()
            request_payload = build_respond_request(kwargs.get("request_text") or snippet)
            try:
                result = run_feature4_latency_test(
                    snippet=snippet,
                    snippet_index=snippet_index,
                    hid_client=hid_client,
                    **kwargs,
                )
            except Exception as exc:
                results.append(
                    _result_from_exception(
                        snippet_index=snippet_index,
                        snippet=snippet,
                        request_text=request_payload,
                        start_at=sample_start,
                        exc=exc,
                    )
                )
                break
            results.append(result)
            if offset < len(selected) - 1 and inter_sample_delay_s > 0:
                time_sleep(inter_sample_delay_s)
    finally:
        hid_client.close()

    return results


def _summarize_results(results: list[RespondLatencyResult]) -> dict[str, Any]:
    completed = [result for result in results if not result.error]
    ttfts = [result.ttft_s for result in completed if result.ttft_s is not None]
    totals = [result.total_time_s for result in completed]

    def _avg(values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    return {
        "requested_samples": len(results),
        "completed_samples": len(completed),
        "error_samples": len(results) - len(completed),
        "avg_ttft_s": _avg(ttfts),
        "avg_total_time_s": _avg(totals),
        "max_ttft_s": max(ttfts) if ttfts else None,
        "max_total_time_s": max(totals) if totals else None,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure feature 4 RESPOND TTFT and total time over the live Pico/Jetson path.")
    parser.add_argument("--port", help="Pico CDC serial port. If omitted, auto-detects the SPARK Pico port.")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Serial baud rate (default: {DEFAULT_BAUD}).")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds.")
    parser.add_argument("--context-settle", type=float, default=DEFAULT_CONTEXT_SETTLE_S, help="Delay after sending context before starting the RESPOND timer.")
    parser.add_argument("--snippets", type=Path, default=DEFAULT_SNIPPET_PATH, help="Path to the 100-snippet JSON dataset.")
    parser.add_argument("--index", type=int, default=0, help="Snippet index to start from.")
    parser.add_argument("--count", type=int, default=DEFAULT_SAMPLE_COUNT, help="How many snippets to run starting at --index.")
    parser.add_argument("--delay", type=float, default=DEFAULT_INTER_SAMPLE_DELAY_S, help="Seconds to wait between samples.")
    parser.add_argument("--request-text", help="Optional explicit previous_user_input value. Defaults to the chosen snippet.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    snippets = load_snippets(args.snippets)
    results = _run_batch(
        snippets=snippets,
        start_index=args.index,
        count=args.count,
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        context_settle_s=args.context_settle,
        inter_sample_delay_s=args.delay,
        request_text=args.request_text,
    )
    payload = {"summary": _summarize_results(results), "results": [asdict(result) for result in results]}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"summary={json.dumps(payload['summary'])}")
        for result in results:
            print(_format_result(result))
            print("-" * 40)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
