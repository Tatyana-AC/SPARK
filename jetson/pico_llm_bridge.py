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


def build_llm_request(raw_prompt: str, default_system_prompt: str) -> tuple[str, str]:
    try:
        request = json.loads(raw_prompt)
    except json.JSONDecodeError:
        return default_system_prompt, raw_prompt

    command = request.get("command")
    if command == "summarize_window":
        app_name = (request.get("app_name") or "").strip() or "(unknown app)"
        window_title = (request.get("window_title") or "").strip() or "(untitled window)"
        window_text = (request.get("window_text") or "").strip()

        user_prompt = (
            "Summarize the user's current active application context.\n"
            "State what appears to be happening on screen, what content is visible, "
            "and the most likely immediate next step.\n"
            "Be concise, concrete, and grounded only in the provided context.\n\n"
            f"Active application: {app_name}\n"
            f"Window title: {window_title}\n"
            "Visible text:\n"
            f"{window_text}\n"
        )
        return default_system_prompt, user_prompt

    return default_system_prompt, raw_prompt


def query_llm_streaming(url: str, prompt: str, system_prompt: str, timeout: int):
    endpoint = f"{url}/v1/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
    }
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


def query_llm_blocking(url: str, prompt: str, system_prompt: str, timeout: int) -> str:
    endpoint = f"{url}/v1/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    resp = requests.post(endpoint, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _emit_summary_response(ser, text: str) -> None:
    if not text:
        return
    for start in range(0, len(text), MAX_SUMMARIZE_CHARS_PER_PACKET):
        ser.write(build_summarize_chunk(text[start : start + MAX_SUMMARIZE_CHARS_PER_PACKET]))
        ser.flush()
        time.sleep(INTER_PACKET_DELAY_S)


def handle_summarize_request(ser, request_text: str, args) -> None:
    llm_system_prompt, llm_prompt = build_llm_request(request_text, args.system_prompt)
    try:
        if args.stream:
            streamed_any = False
            for chunk in query_llm_streaming(args.llm_url, llm_prompt, llm_system_prompt, args.timeout):
                streamed_any = True
                _emit_summary_response(ser, chunk)
            if not streamed_any:
                _emit_summary_response(ser, "")
        else:
            response = query_llm_blocking(args.llm_url, llm_prompt, llm_system_prompt, args.timeout)
            _emit_summary_response(ser, response)
        time.sleep(INTER_PACKET_DELAY_S)
        ser.write(build_summarize_done())
        ser.flush()
    except Exception as exc:
        logger.exception("LLM request failed")
        ser.write(build_error(f"[ERROR] {exc}"))
        ser.flush()


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
        if pkt_type == PKT_CONTEXT_NEW:
            db.on_context_new(pkt)
            return
        if pkt_type == PKT_CONTEXT_UPDATE:
            db.on_context_update(pkt)
            return
        if pkt_type == PKT_BUTTON_PRESS:
            db.on_button_press(pkt["button_id"])
            return
        if pkt_type == PKT_SUMMARIZE_REQUEST:
            handle_summarize_request(ser, pkt.get("request", ""), args)
            return

    parser = PacketParser(on_packet=handle_packet)

    try:
        while True:
            if ser is None:
                ser = open_serial_with_retry(args.port, args.baud, args.reconnect_delay)

            try:
                chunk = ser.read(256)
                if chunk:
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
