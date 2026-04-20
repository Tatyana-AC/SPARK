import importlib.util
import json
from pathlib import Path
import sys
from unittest import mock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "use-case testing" / "reformat_grammar_feature2.py"
DATASET_PATH = REPO_ROOT / "use-case testing" / "feature2_reformat_incorrect_sentences.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("reformat_grammar_feature2", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_sentences_requires_exact_count():
    module = _load_module()

    sentences = [
        "this sentence is missing punctuation",
        "another broken sentence",
        "a third incorrect sentence",
    ]

    module.validate_sentences(sentences, expected_count=3)

    with pytest.raises(ValueError, match="Expected 3 sentences"):
        module.validate_sentences(sentences[:2], expected_count=3)


def test_load_sentences_reads_json_array(tmp_path):
    module = _load_module()

    dataset_path = tmp_path / "feature2_reformat_incorrect_sentences.json"
    sentences_in = [f"broken sentence {index}" for index in range(100)]
    dataset_path.write_text(json.dumps(sentences_in), encoding="utf-8")

    sentences = module.load_sentences(dataset_path)

    assert sentences == sentences_in


def test_response_recorder_uses_first_non_empty_chunk_for_ttft_and_done_for_total():
    module = _load_module()

    recorder = module.ReformatTimingRecorder(request_sent_at=10.0)
    recorder.observe_chunk("", received_at=10.2)
    recorder.observe_chunk("hello", received_at=10.4)
    recorder.observe_chunk(" world", received_at=10.8)
    result = recorder.finish(received_at=11.6)

    assert result.ttft_s == pytest.approx(0.4)
    assert result.total_latency_s == pytest.approx(1.6)
    assert result.response_text == "hello world"
    assert result.error is None


def test_format_result_reports_request_response_only():
    module = _load_module()

    result = module.ReformatGrammarResult(
        sentence_index=3,
        sentence="She go to the office every Monday.",
        request_text='{"command": "reformat_selection", "selected_text": "She go to the office every Monday."}',
        response_text="She goes to the office every Monday.",
        ttft_s=0.2,
        total_latency_s=0.6,
        error=None,
    )

    formatted = module._format_result(result)

    assert "response_text=She goes to the office every Monday." in formatted
    assert "grammar_" not in formatted


def test_dataset_file_contains_100_sentences():
    module = _load_module()

    sentences = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    module.validate_sentences(sentences)
    assert len(sentences) == 100


def test_write_results_persists_request_response_fields_only(tmp_path):
    module = _load_module()

    result = module.ReformatGrammarResult(
        sentence_index=7,
        sentence="She go to the office every Monday.",
        request_text="She go to the office every Monday.",
        response_text="She goes to the office every Monday.",
        ttft_s=0.12,
        total_latency_s=0.84,
        error=None,
    )
    output_path = tmp_path / "results.json"

    module.write_results([result], output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload[0]["response_text"] == "She goes to the office every Monday."
    assert "grammar" not in payload[0]


def test_run_feature2_reformat_test_uses_hid_round_trip_for_request(monkeypatch):
    module = _load_module()

    serial_writes = []

    class _FakeSerial:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def reset_input_buffer(self):
            return None

        def write(self, data):
            serial_writes.append(bytes(data))
            return len(data)

        def flush(self):
            return None

    fake_serial = _FakeSerial()
    fake_hid = mock.Mock()
    fake_hid.stream_round_trip_text.return_value = "The report needs a quick review before noon."

    perf_counter_values = iter([10.0, 10.4])
    monkeypatch.setattr(module, "_open_serial", lambda port, baud: fake_serial)
    monkeypatch.setattr(module, "SparkHIDClient", mock.Mock(return_value=fake_hid))
    monkeypatch.setattr(module.time, "perf_counter", lambda: next(perf_counter_values))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    result = module.run_feature2_reformat_test(
        sentence="The report need a quick review before noon.",
        port="COM17",
        baud=115200,
        context_settle_s=0.0,
        sentence_index=0,
    )

    assert len(serial_writes) == 1
    assert not hasattr(module, "evaluate_grammar")
    fake_hid.stream_round_trip_text.assert_called_once_with(
        module.AppCommand.FEATURE_2,
        '{"command": "reformat_selection", "selected_text": "The report need a quick review before noon."}',
        timeout_ms=30000,
    )
    assert result.response_text == "The report needs a quick review before noon."
    assert result.ttft_s == pytest.approx(0.4)
