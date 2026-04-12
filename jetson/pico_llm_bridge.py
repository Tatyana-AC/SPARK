#!/usr/bin/env python3
"""
SPARK Jetson bridge.

This is the deployable Jetson-side bridge script intended to be copied directly
into the Jetson bridge folder. It combines:
  - framed UART packet handling for Host/Pico/Jetson traffic
  - durable rich context persistence into JetsonDB
  - summarize requests forwarded to a llama.cpp OpenAI-compatible server
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import requests

try:
    from core.protocol import (
        PacketParser,
        PKT_BUTTON_PRESS,
        PKT_CONTEXT_NEW,
        PKT_CONTEXT_UPDATE,
        PKT_SUMMARIZE_REQUEST,
        build_error,
        build_summarize_chunk,
        build_summarize_done,
    )
except ImportError:
    from protocol import (
        PacketParser,
        PKT_BUTTON_PRESS,
        PKT_CONTEXT_NEW,
        PKT_CONTEXT_UPDATE,
        PKT_SUMMARIZE_REQUEST,
        build_error,
        build_summarize_chunk,
        build_summarize_done,
    )

try:
    from jetson.db_manager import JetsonDB
except ImportError:
    from db_manager import JetsonDB

logger = logging.getLogger("spark-jetson-bridge")

DEFAULT_SERIAL_PORT = "/dev/ttyTHS0"
DEFAULT_BAUD_RATE = 115200
DEFAULT_LLM_URL = "http://127.0.0.1:8080"
DEFAULT_RECONNECT_DELAY = 2.0
DEFAULT_DB_PATH = "jetson_spark.db"
MAX_SUMMARIZE_CHARS_PER_PACKET = 64
INTER_PACKET_DELAY_S = 0.01

_PKT_NAMES = {
    PKT_BUTTON_PRESS: "button_press",
    PKT_CONTEXT_NEW: "context_new",
    PKT_CONTEXT_UPDATE: "context_update",
    PKT_SUMMARIZE_REQUEST: "summarize_request",
}


def _packet_name(pkt_type: int) -> str:
    return _PKT_NAMES.get(pkt_type, f"pkt_{pkt_type}")


def _log_inbound_packet(pkt: dict) -> None:
    pkt_type = pkt.get("type")
    if pkt_type == PKT_BUTTON_PRESS:
        logger.info("[UART IN] button_press button_id=%s", pkt.get("button_id"))
        return
    if pkt_type == PKT_SUMMARIZE_REQUEST:
        request = pkt.get("request") or ""
        logger.info("[UART IN] summarize_request chars=%d", len(request))
        return
    if pkt_type == PKT_CONTEXT_NEW:
        logger.debug("[UART IN] context_new text_chars=%d", len(pkt.get("text") or ""))
        return
    if pkt_type == PKT_CONTEXT_UPDATE:
        logger.debug("[UART IN] context_update text_chars=%d", len(pkt.get("text") or ""))
        return
    logger.info("[UART IN] %s", _packet_name(pkt_type))


def _log_parser_diagnostic(event: dict) -> None:
    logger.warning(
        "[UART IN] parser_%s pkt_type=%s reason=%s pkt_len=%s",
        event.get("event"),
        _packet_name(event.get("pkt_type")),
        event.get("reason", "-"),
        event.get("pkt_len", "-"),
    )


def _write_bridge_packet(ser, payload: bytes, *, label: str) -> None:
    logger.info("[UART OUT] %s bytes=%d", label, len(payload))
    ser.write(payload)
    ser.flush()

SUMMARY_JSON_SCHEMA = {
    "name": "summary",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": "The active application name",
            },
            "activity": {
                "type": "string",
                "description": "What the user appears to be doing on screen",
            },
            "next_step": {
                "type": "string",
                "description": "The most likely immediate next action",
            },
        },
        "required": ["app", "activity", "next_step"],
        "additionalProperties": False,
    },
}


def _build_summarize_prompt(app_name: str, window_title: str, window_text: str) -> str:
    app_name = (app_name or "").strip() or "(unknown app)"
    window_title = (window_title or "").strip() or "(untitled window)"
    window_text = (window_text or "").strip()
    return (
        "Summarize the user's current active application context.\n"
        "State what appears to be happening on screen, what content is visible, "
        "and the most likely immediate next step.\n"
        "Be concise, concrete, and grounded only in the provided context.\n\n"
        f"Active application: {app_name}\n"
        f"Window title: {window_title}\n"
        "Visible text:\n"
        f"{window_text}\n"
    )


def build_llm_request(raw_prompt: str, default_system_prompt: str, *, db=None) -> tuple[str, str]:
    try:
        request = json.loads(raw_prompt)
    except json.JSONDecodeError:
        return default_system_prompt, raw_prompt

    command = request.get("command")

    if command == "summarize":
        if db is None:
            return default_system_prompt, "(no database available)"
        session = db.get_active_session()
        if session is None:
            return default_system_prompt, "(no active session)"
        user_prompt = _build_summarize_prompt(
            session["app_name"], session["window_title"], session["text"],
        )
        return default_system_prompt, user_prompt

    if command == "summarize_window":
        user_prompt = _build_summarize_prompt(
            request.get("app_name"), request.get("window_title"), request.get("window_text"),
        )
        return default_system_prompt, user_prompt

    return default_system_prompt, raw_prompt


def _build_payload(prompt: str, system_prompt: str, *, stream: bool, structured: bool) -> dict:
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": stream,
    }
    if structured:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": SUMMARY_JSON_SCHEMA,
        }
    return payload


def query_llm_streaming(url: str, prompt: str, system_prompt: str, timeout: int, *, structured: bool = False):
    endpoint = f"{url}/v1/chat/completions"
    payload = _build_payload(prompt, system_prompt, stream=True, structured=structured)
    with requests.post(endpoint, json=payload, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[len("data: ") :]
            if data_str.strip() == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                delta = data["choices"][0]["delta"]
                if delta.get("content"):
                    yield delta["content"]
            except (json.JSONDecodeError, KeyError, IndexError):
                continue


def query_llm_blocking(url: str, prompt: str, system_prompt: str, timeout: int, *, structured: bool = False) -> str:
    endpoint = f"{url}/v1/chat/completions"
    payload = _build_payload(prompt, system_prompt, stream=False, structured=structured)
    resp = requests.post(endpoint, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def format_structured_summary(raw: str) -> str:
    """Parse structured JSON from the LLM and format as display text.

    Falls back to the raw string if the JSON is malformed.
    """
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Structured response was not valid JSON; using raw text")
        return raw

    parts: list[str] = []
    if obj.get("app"):
        parts.append(obj["app"])
    if obj.get("activity"):
        parts.append(obj["activity"])
    if obj.get("next_step"):
        parts.append(f"Next: {obj['next_step']}")
    return " | ".join(parts) if parts else raw


def _emit_summary_response(ser, text: str) -> None:
    if not text:
        return
    packet_count = (len(text) + MAX_SUMMARIZE_CHARS_PER_PACKET - 1) // MAX_SUMMARIZE_CHARS_PER_PACKET
    logger.info("[UART OUT] summarize_response chars=%d packets=%d", len(text), packet_count)
    for start in range(0, len(text), MAX_SUMMARIZE_CHARS_PER_PACKET):
        _write_bridge_packet(
            ser,
            build_summarize_chunk(text[start : start + MAX_SUMMARIZE_CHARS_PER_PACKET]),
            label="summarize_chunk",
        )
        time.sleep(INTER_PACKET_DELAY_S)


def handle_summarize_request(ser, request_text: str, args, *, db=None) -> None:
    llm_system_prompt, llm_prompt = build_llm_request(request_text, args.system_prompt, db=db)
    structured = args.structured
    logger.info(
        "Handling summarize request: chars=%d stream=%s structured=%s llm_url=%s",
        len(request_text or ""),
        args.stream,
        structured,
        args.llm_url,
    )

    # If no context has been received from the host, skip the LLM and send
    # a diagnostic warning back so the user knows what went wrong.
    _NO_CONTEXT_MARKERS = ("(no database available)", "(no active session)")
    if llm_prompt in _NO_CONTEXT_MARKERS:
        warning_msg = (
            "[WARNING] No context received from host. "
            "Context polling may not be reaching the Jetson."
        )
        logger.warning("Summarize skipped LLM: %s", warning_msg)
        try:
            _emit_summary_response(ser, warning_msg)
            time.sleep(INTER_PACKET_DELAY_S)
            _write_bridge_packet(ser, build_summarize_done(), label="summarize_done")
        except Exception:
            logger.exception("Failed to send no-context warning back to Pico")
        return

    try:
        if args.stream:
            if structured:
                # Buffer the full streamed response so we can parse as JSON.
                buf: list[str] = []
                for chunk in query_llm_streaming(
                    args.llm_url, llm_prompt, llm_system_prompt, args.timeout, structured=True
                ):
                    buf.append(chunk)
                raw = "".join(buf)
                formatted = format_structured_summary(raw)
                logger.info(
                    "Structured streaming complete (%d raw chars -> %d formatted chars)",
                    len(raw),
                    len(formatted),
                )
                _emit_summary_response(ser, formatted)
            else:
                streamed_any = False
                chunk_count = 0
                for chunk in query_llm_streaming(
                    args.llm_url, llm_prompt, llm_system_prompt, args.timeout
                ):
                    streamed_any = True
                    chunk_count += 1
                    _emit_summary_response(ser, chunk)
                if not streamed_any:
                    _emit_summary_response(ser, "")
                logger.info("Summarize request completed with %d streamed chunk(s)", chunk_count)
        else:
            response = query_llm_blocking(
                args.llm_url, llm_prompt, llm_system_prompt, args.timeout, structured=structured
            )
            if structured:
                response = format_structured_summary(response)
            _emit_summary_response(ser, response)
            logger.info("Summarize request completed with blocking response (%d chars)", len(response))
        time.sleep(INTER_PACKET_DELAY_S)
        _write_bridge_packet(ser, build_summarize_done(), label="summarize_done")
    except Exception as exc:
        logger.exception("LLM request failed")
        try:
            _write_bridge_packet(ser, build_error(f"[ERROR] {exc}"), label="error")
        except Exception:
            logger.exception("Failed to send error packet back to Pico")


def open_serial_with_retry(port: str, baud: int, reconnect_delay: float):
    import serial

    while True:
        try:
            logger.info("Opening %s at %d baud", port, baud)
            ser = serial.Serial(port, baud, timeout=0.1)
            ser.reset_input_buffer()
            if hasattr(ser, "reset_output_buffer"):
                ser.reset_output_buffer()
            logger.info("Serial connected")
            return ser
        except serial.SerialException as exc:
            logger.warning(
                "Serial open failed for %s: %s; retrying in %.1fs",
                port,
                exc,
                reconnect_delay,
            )
            time.sleep(reconnect_delay)


def run_bridge(args) -> int:
    try:
        import serial  # noqa: F401
    except ImportError:
        logger.error("pyserial not installed - run: pip install pyserial")
        return 1

    db = JetsonDB(args.db)
    ser = None

    def shutdown(sig=None, frame=None):
        logger.info("Shutting down bridge")
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        db.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    def handle_packet(pkt: dict) -> None:
        pkt_type = pkt["type"]
        _log_inbound_packet(pkt)
        if pkt_type == PKT_CONTEXT_NEW:
            db.on_context_new(pkt)
            return
        if pkt_type == PKT_CONTEXT_UPDATE:
            db.on_context_update(pkt)
            return
        if pkt_type == PKT_BUTTON_PRESS:
            db.on_button_press(pkt["button_id"])
            threading.Thread(
                target=handle_summarize_request,
                args=(ser, '{"command": "summarize"}', args),
                kwargs={"db": db},
                daemon=True,
            ).start()
            return
        if pkt_type == PKT_SUMMARIZE_REQUEST:
            threading.Thread(
                target=handle_summarize_request,
                args=(ser, pkt.get("request", ""), args),
                kwargs={"db": db},
                daemon=True,
            ).start()
            return

    parser = None

    try:
        while True:
            if ser is None:
                ser = open_serial_with_retry(args.port, args.baud, args.reconnect_delay)
                parser = PacketParser(on_packet=handle_packet, diagnostic_hook=_log_parser_diagnostic)
                logger.info("Packet parser reset after serial reconnect")

            try:
                chunk = ser.read(256)
                if chunk:
                    logger.debug("Read %d byte(s) from serial", len(chunk))
                    parser.feed(chunk)
            except Exception as exc:
                logger.warning(
                    "Serial link lost on %s: %s; waiting %.1fs before reopen",
                    args.port,
                    exc,
                    args.reconnect_delay,
                )
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                parser = None
                time.sleep(args.reconnect_delay)
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        db.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SPARK bridge between Pico UART and llama.cpp server"
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_SERIAL_PORT,
        help=f"Serial port device (default: {DEFAULT_SERIAL_PORT})",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD_RATE,
        help=f"Baud rate (default: {DEFAULT_BAUD_RATE})",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--llm-url",
        default=DEFAULT_LLM_URL,
        help=f"llama.cpp server base URL (default: {DEFAULT_LLM_URL})",
    )
    parser.add_argument(
        "--system-prompt",
        default="You are a helpful assistant.",
        help="System prompt sent with every summarize request",
    )
    parser.add_argument(
        "--structured",
        action="store_true",
        default=False,
        help="Enable structured JSON output via response_format (requires llama.cpp grammar support)",
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        default=True,
        help="Disable streaming and wait for full response before sending",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
        help="Seconds to wait before retrying serial reconnect (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    return run_bridge(args)


if __name__ == "__main__":
    raise SystemExit(main())
