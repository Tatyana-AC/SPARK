import importlib.util
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "use-case testing" / "respond_latency_feature4.py"
SNIPPET_PATH = REPO_ROOT / "use-case testing" / "feature4_respond_snippets.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("respond_latency_feature4", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_snippets_requires_exact_word_count_and_total_count():
    module = _load_module()

    valid_snippet = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
    snippets = [valid_snippet] * 100

    module.validate_snippets(snippets)

    with pytest.raises(ValueError, match="100"):
        module.validate_snippets(snippets[:99])

    with pytest.raises(ValueError, match="20 words"):
        module.validate_snippets(
            snippets[:-1]
            + ["one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen"]
        )


def test_dataset_file_contains_100_exact_20_word_snippets():
    module = _load_module()
    snippets = json.loads(SNIPPET_PATH.read_text(encoding="utf-8"))

    module.validate_snippets(snippets)


def test_timing_recorder_uses_first_non_empty_chunk_for_ttft_and_done_for_total():
    module = _load_module()

    recorder = module.RespondTimingRecorder(request_sent_at=10.0)
    recorder.observe_chunk("", received_at=10.2)
    recorder.observe_chunk("hello", received_at=10.4)
    recorder.observe_chunk(" world", received_at=10.8)
    result = recorder.finish(received_at=11.6)

    assert result.ttft_s == pytest.approx(0.4)
    assert result.total_time_s == pytest.approx(1.6)
    assert result.response_text == "hello world"
    assert result.first_word == "hello"
    assert result.last_word == "world"


def test_timing_recorder_requires_terminal_packet():
    module = _load_module()

    recorder = module.RespondTimingRecorder(request_sent_at=1.0)
    recorder.observe_chunk("partial", received_at=1.2)

    with pytest.raises(ValueError, match="terminal"):
        recorder.build_result()


def test_run_batch_waits_between_samples_but_not_after_last(monkeypatch):
    module = _load_module()

    calls = []
    sleeps = []

    def fake_run_feature4_latency_test(*, snippet, snippet_index, **kwargs):
        calls.append((snippet_index, snippet))
        return module.RespondLatencyResult(
            snippet_index=snippet_index,
            snippet=snippet,
            request_text=snippet,
            response_text="done",
            ttft_s=0.5,
            total_time_s=1.0,
            first_word="done",
            last_word="done",
        )

    monkeypatch.setattr(module, "run_feature4_latency_test", fake_run_feature4_latency_test)

    results = module._run_batch(
        snippets=["a"] * 5,
        start_index=1,
        count=3,
        inter_sample_delay_s=1.0,
        time_sleep=sleeps.append,
    )

    assert [result.snippet_index for result in results] == [1, 2, 3]
    assert calls == [(1, "a"), (2, "a"), (3, "a")]
    assert sleeps == [1.0, 1.0]


def test_arg_parser_defaults_to_full_100_sample_run_with_one_second_delay():
    module = _load_module()

    args = module.build_arg_parser().parse_args([])

    assert args.count == 100
    assert args.delay == pytest.approx(1.0)
