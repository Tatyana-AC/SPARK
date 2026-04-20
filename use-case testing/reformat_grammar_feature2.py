from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.protocol import (
    build_context_new,
)
from host_pc.raw_hid import AppCommand, SparkHIDClient
from host_pc.serial_sender import DEFAULT_BAUD, SerialSender
from host_pc.summarize_stream import build_reformat_request


USE_CASE_DIR = Path(__file__).resolve().parent
DEFAULT_SENTENCE_PATH = USE_CASE_DIR / "feature2_reformat_incorrect_sentences.json"
DEFAULT_CONTEXT_APP_NAME = "UseCaseTesting"
DEFAULT_CONTEXT_WINDOW_TITLE = "Feature 2 REFORMAT Grammar"
DEFAULT_CONTEXT_PROCESS_NAME = "reformat_grammar_feature2.py"
DEFAULT_CONTEXT_SOURCE = "full_window"
DEFAULT_CONTEXT_TAB_TITLE = "REFORMAT grammar"
DEFAULT_CONTEXT_URL = None
DEFAULT_CONTEXT_PID = 0
DEFAULT_CONTEXT_SETTLE_S = 0.25
DEFAULT_DATASET_COUNT = 100
DEFAULT_RESULTS_DIR = USE_CASE_DIR / "results"


@dataclass
class ReformatGrammarResult:
    sentence_index: int
    sentence: str
    request_text: str
    response_text: str
    ttft_s: float | None
    total_latency_s: float
    error: str | None = None


class ReformatTimingRecorder:
    def __init__(self, request_sent_at: float):
        self.request_sent_at = float(request_sent_at)
        self._chunks: list[str] = []
        self._first_chunk_at: float | None = None
        self._terminal_at: float | None = None
        self._error: str | None = None

    def observe_chunk(self, text: str, *, received_at: float) -> None:
        chunk = text or ""
        self._chunks.append(chunk)
        if self._first_chunk_at is None and chunk.strip():
            self._first_chunk_at = float(received_at)

    def observe_error(self, message: str, *, received_at: float) -> None:
        self._error = message or "[ERROR] Unknown bridge error"
        self._terminal_at = float(received_at)

    def finish(self, *, received_at: float) -> ReformatGrammarResult:
        self._terminal_at = float(received_at)
        return self.build_result()

    def build_result(
        self,
        *,
        sentence_index: int = -1,
        sentence: str = "",
        request_text: str = "",
    ) -> ReformatGrammarResult:
        if self._terminal_at is None:
            raise ValueError("Cannot build a result before a terminal packet is received.")

        response_text = "".join(self._chunks)
        ttft_s = None
        if self._first_chunk_at is not None:
            ttft_s = self._first_chunk_at - self.request_sent_at

        return ReformatGrammarResult(
            sentence_index=sentence_index,
            sentence=sentence,
            request_text=request_text,
            response_text=response_text,
            ttft_s=ttft_s,
            total_latency_s=self._terminal_at - self.request_sent_at,
            error=self._error,
        )


def validate_sentences(sentences: Sequence[str], *, expected_count: int = DEFAULT_DATASET_COUNT) -> None:
    if isinstance(sentences, (str, bytes)):
        raise ValueError("Sentence dataset must be a sequence of strings.")

    if len(sentences) != expected_count:
        raise ValueError(f"Expected {expected_count} sentences but found {len(sentences)}.")

    for index, sentence in enumerate(sentences):
        if not isinstance(sentence, str):
            raise ValueError(f"Sentence {index} is not a string.")
        if not sentence.strip():
            raise ValueError(f"Sentence {index} is empty.")


def load_sentences(path: Path = DEFAULT_SENTENCE_PATH) -> list[str]:
    sentences = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sentences, list):
        raise ValueError("Sentence file must contain a JSON array.")
    validate_sentences(sentences)
    return sentences


def _build_context_payload(sentence: str) -> dict[str, Any]:
    return {
        "app_name": DEFAULT_CONTEXT_APP_NAME,
        "window_title": DEFAULT_CONTEXT_WINDOW_TITLE,
        "process_name": DEFAULT_CONTEXT_PROCESS_NAME,
        "pid": DEFAULT_CONTEXT_PID,
        "source": DEFAULT_CONTEXT_SOURCE,
        "tab_title": DEFAULT_CONTEXT_TAB_TITLE,
        "url": DEFAULT_CONTEXT_URL,
        "text": sentence,
        "timestamp": time.time(),
    }


def _open_serial(port: str | None, baud: int):
    try:
        import serial
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("pyserial is required to run the live REFORMAT grammar harness.") from exc

    selected_port = port or SerialSender._find_pico_port()
    if not selected_port:
        raise RuntimeError("Could not auto-detect a Pico CDC port. Pass --port explicitly.")
    return serial.Serial(selected_port, baud, timeout=0.05, write_timeout=2.0)


def _wait_for_context_settle(delay_s: float) -> None:
    if delay_s > 0:
        time.sleep(delay_s)


def _send_context(ser, sentence: str) -> None:
    ser.write(build_context_new(_build_context_payload(sentence)))
    ser.flush()


def _build_reformat_request_text(sentence: str) -> str:
    return build_reformat_request(sentence)


def run_feature2_reformat_test(
    *,
    sentence: str,
    port: str | None = None,
    baud: int = DEFAULT_BAUD,
    timeout_s: float = 30.0,
    context_settle_s: float = DEFAULT_CONTEXT_SETTLE_S,
    sentence_index: int = -1,
) -> ReformatGrammarResult:
    with _open_serial(port, baud) as ser:
        if hasattr(ser, "reset_input_buffer"):
            ser.reset_input_buffer()
        _send_context(ser, sentence)
        _wait_for_context_settle(context_settle_s)

    request_text = _build_reformat_request_text(sentence)
    request_started_at = time.perf_counter()
    recorder = ReformatTimingRecorder(request_sent_at=request_started_at)
    hid_client = SparkHIDClient()
    try:
        response_text = hid_client.stream_round_trip_text(
            AppCommand.FEATURE_2,
            request_text,
            timeout_ms=int(timeout_s * 1000),
        )
    finally:
        close = getattr(hid_client, "close", None)
        if callable(close):
            close()
    request_finished_at = time.perf_counter()
    recorder.observe_chunk(response_text, received_at=request_finished_at)
    result = recorder.finish(received_at=request_finished_at)
    result.sentence_index = sentence_index
    result.sentence = sentence
    result.request_text = request_text
    return result


def _format_result(result: ReformatGrammarResult) -> str:
    lines = [
        f"sentence_index={result.sentence_index}",
        f"sentence={result.sentence}",
        f"request_text={result.request_text}",
        f"ttft_s={result.ttft_s if result.ttft_s is not None else 'n/a'}",
        f"total_latency_s={result.total_latency_s}",
        f"response_text={result.response_text}",
    ]
    if result.error:
        lines.append(f"error={result.error}")
    return "\n".join(lines)


def _validate_batch_window(sentences: Sequence[str], start_index: int, count: int) -> None:
    if start_index < 0:
        raise ValueError("--index must be >= 0.")
    if count < 1:
        raise ValueError("--count must be >= 1.")
    if start_index > len(sentences):
        raise ValueError("--index is beyond the end of the dataset.")
    if start_index + count > len(sentences):
        raise ValueError("Requested batch exceeds the available sentences.")


def _run_batch(
    *,
    sentences: Sequence[str],
    start_index: int,
    count: int,
    **kwargs: Any,
) -> list[ReformatGrammarResult]:
    _validate_batch_window(sentences, start_index, count)
    selected = sentences[start_index : start_index + count]
    results: list[ReformatGrammarResult] = []
    for offset, sentence in enumerate(selected):
        sentence_index = start_index + offset
        result = run_feature2_reformat_test(
            sentence=sentence,
            sentence_index=sentence_index,
            **kwargs,
        )
        results.append(result)
    return results


def default_output_path(*, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RESULTS_DIR / f"feature2_reformat_results_{timestamp}.json"


def write_results(results: Sequence[ReformatGrammarResult], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(result) for result in results], indent=2),
        encoding="utf-8",
    )
    return output_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure feature 2 REFORMAT TTFT, total latency, and grammar quality over the live Pico/Jetson path.")
    parser.add_argument("--port", help="Pico CDC serial port. If omitted, auto-detects the SPARK Pico port.")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Serial baud rate (default: {DEFAULT_BAUD}).")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds.")
    parser.add_argument("--context-settle", type=float, default=DEFAULT_CONTEXT_SETTLE_S, help="Delay after sending context before starting the REFORMAT timer.")
    parser.add_argument("--sentences", type=Path, default=DEFAULT_SENTENCE_PATH, help="Path to the 100-sentence JSON dataset.")
    parser.add_argument("--index", type=int, default=0, help="Sentence index to start from.")
    parser.add_argument("--count", type=int, default=1, help="How many sentences to run starting at --index.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path. Defaults to a timestamped file under use-case testing/results/.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    sentences = load_sentences(args.sentences)
    results = _run_batch(
        sentences=sentences,
        start_index=args.index,
        count=args.count,
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        context_settle_s=args.context_settle,
    )
    output_path = write_results(results, args.output or default_output_path())
    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        for result in results:
            print(_format_result(result))
            print("-" * 40)
        print(f"saved_results_path={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
