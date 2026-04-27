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
import re
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
DEFAULT_RECONNECT_WATCHDOG_GRACE = 10.0
DEFAULT_DB_PATH = "jetson_spark.db"
DEFAULT_AUDIT_LOG_PATH = "llm_request_response_audit.log"
MAX_SUMMARIZE_CHARS_PER_PACKET = 64
INTER_PACKET_DELAY_S = 0.01
AUDIT_DIVIDER = "=" * 80

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
        command = "unknown"
        try:
            payload = json.loads(request)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            raw_command = payload.get("command")
            if isinstance(raw_command, str) and raw_command.strip():
                command = raw_command.strip()
        logger.info("[UART IN] summarize_request chars=%d command=%s", len(request), command)
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

REFORMAT_SYSTEM_PROMPT = (
    "You are a code rewriter that rewrites selected text from the active window. "
    "Return only the rewritten selected text."
)

RESPOND_SYSTEM_PROMPT = (
    "You continue and complete the user's in-progress text using the active window context. "
    "Return only the continuation text. "
    "Keep it concise, generally 2-3 sentences."
)

RESPOND_CLASSIFIER_SYSTEM_PROMPT = (
    "You classify whether the visible app context contains something the user should respond to. "
    "Return JSON only."
)

RESPOND_CLASSIFICATION_JSON_SCHEMA = {
    "name": "respond_classification",
    "schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["reply_to_visible_context", "proactive_update"],
            },
            "reply_target_summary": {"type": "string"},
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
        },
        "required": ["mode", "reply_target_summary", "confidence"],
        "additionalProperties": False,
    },
}

KEYWORD_SEARCH_SYSTEM_PROMPT = (
    "You summarize the three most recent matching entries from SPARK history. "
    "Return only a concise plain-text summary grounded in the matched entries."
)
_NO_KEYWORD_MATCHES_PREFIX = "(no keyword matches)"
_KEYWORD_SNIPPET_CHARS = 120

SYNTHESIS_SYSTEM_PROMPT = (
    "You perform anchored session synthesis for SPARK. "
    "The active app is the anchor. Use only related recent context that helps explain or extend the active work."
)
SYNTHESIS_KEYWORD_EXTRACTION_SYSTEM_PROMPT = (
    "You extract concise retrieval keywords from the active anchor context for SPARK session synthesis. "
    "Return JSON only."
)

SYNTHESIS_KEYWORD_JSON_SCHEMA = {
    "name": "synthesis_keywords",
    "schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["keywords"],
        "additionalProperties": False,
    },
}

_SYNTHESIS_MAX_RELATED = 5
_SYNTHESIS_SOURCE_CHARS = 1200
_SYNTHESIS_ANCHOR_TEXT_RELEVANCE_CHARS = 600
_SYNTHESIS_MAX_KEYWORDS = 8
_SYNTHESIS_KEYWORD_MATCH_LIMIT = 5


def _button_press_request_text(button_id: int) -> str:
    return json.dumps({"command": "synthesize_session", "window_minutes": 30})


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


def _build_reformat_prompt(
    app_name: str,
    window_title: str,
    window_text: str,
    selected_text: str,
) -> str:
    app_name = (app_name or "").strip() or "(unknown app)"
    window_title = (window_title or "").strip() or "(untitled window)"
    window_text = (window_text or "").strip()
    selected_text = selected_text if isinstance(selected_text, str) else ""
    return (
        "Rewrite the selected text using only the provided context.\n"
        "Correct spelling, grammar, punctuation, and phrasing where needed.\n"
        "Preserve the meaning while making the text clearer and more polished, and keep it relevant to the current context.\n"
        "Return only the rewritten text.\n"
        "Do not add labels, explanations, commentary, or JSON.\n\n"
        f"Active application: {app_name}\n"
        f"Window title: {window_title}\n"
        "Visible text:\n"
        f"{window_text}\n"
        "Selected text:\n"
        f"{selected_text}\n"
    )


def _build_respond_prompt(
    app_name: str,
    window_title: str,
    window_text: str,
    previous_user_input: str,
) -> str:
    app_name = (app_name or "").strip() or "(unknown app)"
    window_title = (window_title or "").strip() or "(untitled window)"
    window_text = (window_text or "").strip()
    previous_user_input = previous_user_input if isinstance(previous_user_input, str) else ""
    return (
        "Continue and complete the user's in-progress text using only the provided context.\n"
        "Treat the previous user input as the start of the draft.\n"
        "Keep the continuation consistent with the active application context and visible content.\n"
        "Return only the continuation text.\n"
        "Do not add labels, explanations, commentary, or JSON.\n\n"
        "Part 1 - Current Draft\n"
        "Current app:\n"
        f"{app_name}\n"
        "Previous written text in current text box:\n"
        f"{previous_user_input}\n\n"
        "Part 2 - Context\n"
        "Window title:\n"
        f"{window_title}\n"
        "Visible text:\n"
        f"{window_text}\n"
    )


def _build_respond_classification_prompt(anchor) -> str:
    return "\n".join(
        [
            "Classify whether the visible app context contains something to respond to.",
            "Choose reply_to_visible_context when the visible text includes a question, request, prompt, message, or thread that calls for a reply.",
            "Choose proactive_update when there is no visible thing to answer and RESPOND should draft a neutral recent-work update instead.",
            "Return JSON only.",
            "",
            "Active application:",
            (anchor["app_name"] or "").strip() or "(unknown app)",
            "Window title:",
            (anchor["window_title"] or "").strip() or "(untitled window)",
            "Tab title:",
            (anchor["tab_title"] or "").strip() or "(untitled tab)",
            "URL:",
            (anchor["url"] or "").strip() or "(no url)",
            "Visible text:",
            _trim_synthesis_text(anchor["text"] or ""),
        ]
    ).strip()


def _fallback_respond_classification(active_text: str) -> dict:
    active_text = (active_text or "").strip()
    return {
        "mode": "reply_to_visible_context" if active_text else "proactive_update",
        "reply_target_summary": active_text[:240],
        "confidence": "low",
    }


def _parse_respond_classification(raw: str, *, active_text: str) -> dict:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        logger.warning("RESPOND classification was not valid JSON")
        return _fallback_respond_classification(active_text)

    if not isinstance(payload, dict):
        return _fallback_respond_classification(active_text)

    mode = payload.get("mode")
    confidence = payload.get("confidence")
    summary = payload.get("reply_target_summary")
    if mode not in {"reply_to_visible_context", "proactive_update"}:
        return _fallback_respond_classification(active_text)
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    if not isinstance(summary, str):
        summary = ""

    return {
        "mode": mode,
        "reply_target_summary": summary.strip(),
        "confidence": confidence,
    }


def _build_keyword_search_prompt(selected_text: str, matches) -> str:
    selected_text = (selected_text or "").strip()
    lines = [
        "Summarize the three most recent matching entries for the selected keyword.",
        "Stay grounded in the matched entries only.",
        "Return only the summary text.",
        f'Selected keyword: {selected_text}',
        "",
        "Matched entries:",
    ]
    for idx, row in enumerate(matches, start=1):
        snippet = _extract_keyword_snippet(row["text"] or "", selected_text)
        lines.extend(
            [
                f"Entry {idx}:",
                f"App: {(row['app_name'] or '').strip() or '(unknown app)'}",
                f"Window title: {(row['window_title'] or '').strip() or '(untitled window)'}",
                "Matched text snippet:",
                snippet,
                "",
            ]
        )
    return "\n".join(lines).strip()


def _extract_keyword_snippet(text: str, selected_text: str, max_chars: int = _KEYWORD_SNIPPET_CHARS) -> str:
    text = text or ""
    selected_text = (selected_text or "").strip()
    if not text:
        return ""
    if not selected_text:
        trimmed = text[:max_chars].strip()
        return trimmed if len(text) <= max_chars else f"{trimmed}…"

    text_lower = text.lower()
    selected_lower = selected_text.lower()
    match_index = text_lower.find(selected_lower)
    if match_index < 0:
        trimmed = text[:max_chars].strip()
        return trimmed if len(text) <= max_chars else f"{trimmed}…"

    half_window = max_chars // 2
    start = max(0, match_index - half_window)
    end = min(len(text), match_index + len(selected_text) + half_window)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = f"…{snippet}"
    if end < len(text):
        snippet = f"{snippet}…"
    return snippet


def _is_related_session_candidate(anchor, row) -> bool:
    anchor_app = (anchor["app_name"] or "").strip().lower()
    row_app = (row["app_name"] or "").strip().lower()
    row_source = (row["source"] or "").strip().lower()
    row_url = (row["url"] or "").strip()
    same_app = False
    if anchor_app and row_app:
        same_app = anchor_app == row_app or anchor_app in row_app or row_app in anchor_app

    if same_app and (not row_url or row_source != "web_content"):
        return False

    return True


def _build_synthesis_keyword_prompt(anchor) -> str:
    return "\n".join(
        [
            "Extract a short list of retrieval keywords from this anchor context.",
            "Return the most topic-bearing entities, concepts, events, organizations, people, and laws only.",
            "Expand abbreviations into both forms when relevant, for example include both 'EIC' and 'East India Company'.",
            "Do not include generic UI words, browser names, filler words, or broad terms that would match unrelated technical pages.",
            f"Return 3 to {_SYNTHESIS_MAX_KEYWORDS} keywords.",
            "",
            "ANCHOR SOURCE",
            f"App: {(anchor['app_name'] or '').strip() or '(unknown app)'}",
            f"Window title: {(anchor['window_title'] or '').strip() or '(untitled window)'}",
            f"Tab title: {(anchor['tab_title'] or '').strip() or '(untitled tab)'}",
            f"URL: {(anchor['url'] or '').strip() or '(no url)'}",
            "Visible text:",
            _trim_synthesis_text((anchor["text"] or "")[:_SYNTHESIS_SOURCE_CHARS]),
        ]
    ).strip()


def _parse_synthesis_keywords(raw: str) -> list[str]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return []
    values = payload.get("keywords")
    if not isinstance(values, list):
        return []

    seen = set()
    keywords: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        keyword = value.strip()
        if not keyword:
            continue
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        keywords.append(keyword)
        if len(keywords) >= _SYNTHESIS_MAX_KEYWORDS:
            break
    return keywords


def _prepare_keyword_extraction_http_request(url: str, prompt: str) -> tuple[str, dict]:
    endpoint = f"{url}/v1/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": SYNTHESIS_KEYWORD_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": SYNTHESIS_KEYWORD_JSON_SCHEMA,
        },
    }
    return endpoint, payload


def _collect_synthesis_related_rows(db, anchor, *, keywords: list[str], cutoff_timestamp: float):
    hits_by_context: dict[str, dict] = {}
    for keyword in keywords:
        for row in db.get_recent_sessions_matching_text_since(
            keyword,
            cutoff_timestamp,
            limit=_SYNTHESIS_KEYWORD_MATCH_LIMIT,
            dedupe=True,
        ):
            if int(row["id"]) == int(anchor["id"]):
                continue
            if not _is_related_session_candidate(anchor, row):
                continue

            context_key = row["context_key"]
            lowered = keyword.strip().lower()
            entry = hits_by_context.setdefault(
                context_key,
                {"row": row, "keywords": set()},
            )
            entry["keywords"].add(lowered)

    ranked = sorted(
        hits_by_context.values(),
        key=lambda entry: (
            -len(entry["keywords"]),
            -(entry["row"]["host_observed_at"] or entry["row"]["updated_at"] or 0),
            -int(entry["row"]["id"]),
        ),
    )
    return [entry["row"] for entry in ranked[:_SYNTHESIS_MAX_RELATED]]


def _synthesis_cutoff_timestamp(anchor, *, window_minutes: int) -> float:
    anchor_timestamp = anchor["host_observed_at"] or anchor["updated_at"] or time.time()
    return float(anchor_timestamp) - (int(window_minutes) * 60)


def _trim_synthesis_text(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _SYNTHESIS_SOURCE_CHARS:
        return text
    return f"{text[:_SYNTHESIS_SOURCE_CHARS].strip()}…"


def _append_synthesis_source(lines: list[str], row) -> None:
    lines.extend(
        [
            f"App: {(row['app_name'] or '').strip() or '(unknown app)'}",
            f"Window title: {(row['window_title'] or '').strip() or '(untitled window)'}",
            f"Tab title: {(row['tab_title'] or '').strip() or '(untitled tab)'}",
            f"URL: {(row['url'] or '').strip() or '(no url)'}",
            "Visible text:",
            _trim_synthesis_text(row["text"] or ""),
        ]
    )


def _build_synthesize_session_prompt(anchor, related_rows, *, window_minutes: int) -> str:
    lines = [
        "The active app is the anchor. Summarize it first, then use related recent context "
        f"from the last {window_minutes} minutes only when it helps explain or extend the active work.",
        "Do not include unrelated recent windows.",
        "Only include a 'Related context' section if related sources are listed below, "
        "and mention what each related source contributes.",
        "If no related sources are listed below, do not mention related context, "
        "related sources, or the absence of related context at all.",
        "",
        "ANCHOR SOURCE",
    ]
    _append_synthesis_source(lines, anchor)
    if related_rows:
        lines.extend(["", "RELATED RECENT SOURCES"])
        for idx, row in enumerate(related_rows, start=1):
            lines.extend(["", f"Related source {idx}:"])
            _append_synthesis_source(lines, row)
    return "\n".join(lines).strip()


def _missing_synthesis_anchor_message(anchor_context_key: str | None) -> str:
    anchor_context_key = (anchor_context_key or "").strip()
    if not anchor_context_key:
        return "(missing anchor_context_key for synthesize_session)"
    return f"(no session found for anchor_context_key: {anchor_context_key})"


def _synthesis_request_error_message(llm_prompt: str) -> str | None:
    if llm_prompt == "(missing anchor_context_key for synthesize_session)":
        return "[ERROR] Cannot synthesize without anchor_context_key."
    if isinstance(llm_prompt, str) and llm_prompt.startswith("(no session found for anchor_context_key:"):
        return "[ERROR] Cannot synthesize: no session found for anchor_context_key."
    return None


_RELATED_CONTEXT_HEADING_RE = re.compile(
    r"(?im)^(?:#{1,6}\s*)?related context(?:\s*\(none\))?\s*:?\s*$"
)
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6}\s+.+)$")


def _synthesis_prompt_has_related_sources(llm_prompt: str) -> bool:
    return isinstance(llm_prompt, str) and "RELATED RECENT SOURCES" in llm_prompt


def _strip_empty_related_context_sections(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return text

    lines = text.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _RELATED_CONTEXT_HEADING_RE.match(line.strip()):
            kept.append(line)
            index += 1
            continue

        index += 1
        while index < len(lines):
            candidate = lines[index]
            stripped = candidate.strip()
            if _MARKDOWN_HEADING_RE.match(stripped) and not _RELATED_CONTEXT_HEADING_RE.match(stripped):
                break
            index += 1

        while kept and not kept[-1].strip():
            kept.pop()

    return "\n".join(kept).strip()


def _parse_request(raw_prompt: str) -> dict:
    try:
        request = json.loads(raw_prompt)
    except json.JSONDecodeError:
        return {}
    if not isinstance(request, dict):
        return {}
    return request


def build_llm_request(
    raw_prompt: str,
    default_system_prompt: str,
    *,
    db=None,
    _request: dict | None = None,
) -> tuple[str, str]:
    request = _request if _request is not None else _parse_request(raw_prompt)
    if not request:
        return default_system_prompt, raw_prompt

    command = request.get("command")

    if command == "reformat_selection":
        if db is None:
            return default_system_prompt, "(no database available)"
        session = db.get_active_session()
        if session is None:
            return default_system_prompt, "(no active session)"
        user_prompt = _build_reformat_prompt(
            session["app_name"],
            session["window_title"],
            session["text"],
            request.get("selected_text", ""),
        )
        return REFORMAT_SYSTEM_PROMPT, user_prompt

    if command == "respond_selection":
        if db is None:
            return default_system_prompt, "(no database available)"
        session = db.get_active_session()
        if session is None:
            return default_system_prompt, "(no active session)"
        user_prompt = _build_respond_prompt(
            session["app_name"],
            session["window_title"],
            session["text"],
            request.get("previous_user_input", ""),
        )
        return RESPOND_SYSTEM_PROMPT, user_prompt

    if command == "keyword_search":
        if db is None:
            return default_system_prompt, "(no database available)"
        selected_text = request.get("selected_text", "")
        matches = db.get_recent_sessions_matching_text(selected_text, limit=3)
        if not matches:
            return KEYWORD_SEARCH_SYSTEM_PROMPT, f'{_NO_KEYWORD_MATCHES_PREFIX}:{selected_text}'
        return (
            KEYWORD_SEARCH_SYSTEM_PROMPT,
            _build_keyword_search_prompt(selected_text, matches),
        )

    if command == "synthesize_session":
        if db is None:
            return SYNTHESIS_SYSTEM_PROMPT, "(no database available)"
        anchor_context_key = request.get("anchor_context_key")
        session = db.get_latest_session_for_context_key(anchor_context_key)
        if session is None:
            return SYNTHESIS_SYSTEM_PROMPT, _missing_synthesis_anchor_message(anchor_context_key)
        window_minutes = int(request.get("window_minutes") or 30)
        cutoff = _synthesis_cutoff_timestamp(session, window_minutes=window_minutes)
        keywords = request.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = []
        related = _collect_synthesis_related_rows(
            db,
            session,
            keywords=keywords,
            cutoff_timestamp=cutoff,
        )
        user_prompt = _build_synthesize_session_prompt(
            session,
            related,
            window_minutes=window_minutes,
        )
        return SYNTHESIS_SYSTEM_PROMPT, user_prompt

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


def _prepare_llm_http_request(
    url: str,
    prompt: str,
    system_prompt: str,
    *,
    stream: bool,
    structured: bool,
) -> tuple[str, dict]:
    endpoint = f"{url}/v1/chat/completions"
    payload = _build_payload(prompt, system_prompt, stream=stream, structured=structured)
    return endpoint, payload


def _append_llm_audit_record(
    audit_log_path: str | Path | None,
    *,
    command: str | None,
    endpoint: str,
    request_payload: dict,
    response_text: str,
) -> None:
    if not audit_log_path:
        return

    path = Path(audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"{AUDIT_DIVIDER}\n",
        "SPARK LLM AUDIT\n",
        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S %z')}\n",
        f"Command: {command or '(raw_prompt)'}\n",
        f"Endpoint: {endpoint}\n",
        "\n",
        "===== REQUEST JSON BEGIN =====\n",
        f"{json.dumps(request_payload, indent=2)}\n",
        "===== REQUEST JSON END =====\n",
        "\n",
        "===== RESPONSE TEXT BEGIN =====\n",
        response_text or "",
    ]
    if response_text and not response_text.endswith("\n"):
        lines.append("\n")
    lines.extend(
        [
            "===== RESPONSE TEXT END =====\n",
            f"{AUDIT_DIVIDER}\n\n",
        ]
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.writelines(lines)


def query_llm_streaming(endpoint: str, payload: dict, timeout: int):
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


def query_llm_blocking(endpoint: str, payload: dict, timeout: int) -> str:
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
    request = _parse_request(request_text)
    command = request.get("command") if request else None
    llm_system_prompt = args.system_prompt
    llm_prompt = ""
    if command == "synthesize_session":
        if db is None:
            llm_system_prompt, llm_prompt = SYNTHESIS_SYSTEM_PROMPT, "(no database available)"
        else:
            anchor_context_key = request.get("anchor_context_key")
            anchor = db.get_latest_session_for_context_key(anchor_context_key)
            if anchor is None:
                llm_system_prompt, llm_prompt = (
                    SYNTHESIS_SYSTEM_PROMPT,
                    _missing_synthesis_anchor_message(anchor_context_key),
                )
            else:
                window_minutes = int(request.get("window_minutes") or 30)
                cutoff = _synthesis_cutoff_timestamp(anchor, window_minutes=window_minutes)
                keyword_prompt = _build_synthesis_keyword_prompt(anchor)
                keyword_endpoint, keyword_payload = _prepare_keyword_extraction_http_request(
                    args.llm_url,
                    keyword_prompt,
                )
                try:
                    keyword_raw = query_llm_blocking(keyword_endpoint, keyword_payload, args.timeout)
                except Exception:
                    logger.exception("Keyword extraction request failed for synthesize_session")
                    keyword_raw = ""
                keywords = _parse_synthesis_keywords(keyword_raw)
                request = dict(request)
                request["keywords"] = keywords
                llm_system_prompt, llm_prompt = build_llm_request(
                    json.dumps(request),
                    args.system_prompt,
                    db=db,
                    _request=request,
                )
    else:
        llm_system_prompt, llm_prompt = build_llm_request(
            request_text,
            args.system_prompt,
            db=db,
            _request=request,
        )
    structured = args.structured and command not in {
        "reformat_selection",
        "respond_selection",
        "keyword_search",
        "synthesize_session",
    }
    logger.info(
        "Handling summarize request: chars=%d stream=%s structured=%s llm_url=%s command=%s",
        len(request_text or ""),
        args.stream,
        structured,
        args.llm_url,
        command,
    )

    synthesis_error_msg = _synthesis_request_error_message(llm_prompt)
    if synthesis_error_msg is not None:
        logger.warning("%s skipped LLM: %s", command, synthesis_error_msg)
        try:
            _write_bridge_packet(ser, build_error(synthesis_error_msg), label="error")
        except Exception:
            logger.exception("Failed to send synthesis error back to Pico")
        return

    # If no context has been received from the host, skip the LLM and send
    # a diagnostic warning back so the user knows what went wrong.
    _NO_CONTEXT_MARKERS = ("(no database available)", "(no active session)")
    if llm_prompt in _NO_CONTEXT_MARKERS:
        if command in {"reformat_selection", "respond_selection", "keyword_search"}:
            warning_msg = (
                "[ERROR] Cannot reformat without active context."
                if command == "reformat_selection"
                else "[ERROR] Cannot respond without active context."
                if command == "respond_selection"
                else "[ERROR] Cannot search without database."
            )
            logger.warning("%s skipped LLM: %s", command, warning_msg)
            try:
                _write_bridge_packet(ser, build_error(warning_msg), label="error")
            except Exception:
                logger.exception("Failed to send no-context error back to Pico")
            return

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

    if command == "keyword_search" and llm_prompt.startswith(f"{_NO_KEYWORD_MATCHES_PREFIX}:"):
        selected_text = llm_prompt.split(":", 1)[1].strip()
        no_match_msg = f'No recent entries matched "{selected_text}".'
        logger.info("Keyword search skipped LLM: %s", no_match_msg)
        try:
            _emit_summary_response(ser, no_match_msg)
            time.sleep(INTER_PACKET_DELAY_S)
            _write_bridge_packet(ser, build_summarize_done(), label="summarize_done")
        except Exception:
            logger.exception("Failed to send no-match keyword search response")
        return

    endpoint, request_payload = _prepare_llm_http_request(
        args.llm_url,
        llm_prompt,
        llm_system_prompt,
        stream=args.stream,
        structured=structured,
    )
    synthesize_without_related = (
        command == "synthesize_session" and not _synthesis_prompt_has_related_sources(llm_prompt)
    )

    try:
        audit_response_text = ""
        if args.stream:
            if structured:
                # Buffer the full streamed response so we can parse as JSON.
                buf: list[str] = []
                for chunk in query_llm_streaming(endpoint, request_payload, args.timeout):
                    buf.append(chunk)
                raw = "".join(buf)
                formatted = format_structured_summary(raw)
                logger.info(
                    "Structured streaming complete (%d raw chars -> %d formatted chars)",
                    len(raw),
                    len(formatted),
                )
                _emit_summary_response(ser, formatted)
                audit_response_text = formatted
            else:
                streamed_any = False
                chunk_count = 0
                emitted_chunks: list[str] = []
                for chunk in query_llm_streaming(endpoint, request_payload, args.timeout):
                    streamed_any = True
                    chunk_count += 1
                    emitted_chunks.append(chunk)
                    if not synthesize_without_related:
                        _emit_summary_response(ser, chunk)
                if not streamed_any:
                    if not synthesize_without_related:
                        _emit_summary_response(ser, "")
                audit_response_text = "".join(emitted_chunks)
                if synthesize_without_related:
                    audit_response_text = _strip_empty_related_context_sections(audit_response_text)
                    _emit_summary_response(ser, audit_response_text)
                logger.info("Summarize request completed with %d streamed chunk(s)", chunk_count)
        else:
            response = query_llm_blocking(endpoint, request_payload, args.timeout)
            if structured:
                response = format_structured_summary(response)
            if synthesize_without_related:
                response = _strip_empty_related_context_sections(response)
            _emit_summary_response(ser, response)
            audit_response_text = response
            logger.info("Summarize request completed with blocking response (%d chars)", len(response))
        time.sleep(INTER_PACKET_DELAY_S)
        _write_bridge_packet(ser, build_summarize_done(), label="summarize_done")
        try:
            _append_llm_audit_record(
                args.audit_log,
                command=command,
                endpoint=endpoint,
                request_payload=request_payload,
                response_text=audit_response_text,
            )
        except Exception:
            logger.exception("Failed to append LLM audit record")
    except Exception as exc:
        logger.exception("LLM request failed")
        error_text = f"[ERROR] {exc}"
        try:
            _write_bridge_packet(ser, build_error(error_text), label="error")
        except Exception:
            logger.exception("Failed to send error packet back to Pico")
        try:
            _append_llm_audit_record(
                args.audit_log,
                command=command,
                endpoint=endpoint,
                request_payload=request_payload,
                response_text=error_text,
            )
        except Exception:
            logger.exception("Failed to append LLM audit record after error")


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


def _close_serial_port(ser) -> None:
    if ser is None:
        return
    try:
        ser.close()
    except Exception:
        pass


def run_bridge(args) -> int:
    try:
        import serial  # noqa: F401
    except ImportError:
        logger.error("pyserial not installed - run: pip install pyserial")
        return 1

    db = JetsonDB(args.db)
    ser = None
    saw_inbound_packet = False
    reconnect_watchdog_deadline = None
    reconnect_watchdog_grace = float(
        getattr(args, "reconnect_watchdog_grace", DEFAULT_RECONNECT_WATCHDOG_GRACE)
    )

    def shutdown(sig=None, frame=None):
        logger.info("Shutting down bridge")
        _close_serial_port(ser)
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
                args=(ser, _button_press_request_text(pkt["button_id"]), args),
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
                try:
                    parser = PacketParser(on_packet=handle_packet, diagnostic_hook=_log_parser_diagnostic)
                except TypeError:
                    # Backward-compatible path for PacketParser variants that do not accept
                    # the optional diagnostic_hook parameter.
                    parser = PacketParser(on_packet=handle_packet)
                logger.info("Packet parser reset after serial reconnect")
                if saw_inbound_packet:
                    reconnect_watchdog_deadline = time.monotonic() + reconnect_watchdog_grace
                else:
                    reconnect_watchdog_deadline = None

            try:
                chunk = ser.read(256)
                if chunk:
                    saw_inbound_packet = True
                    reconnect_watchdog_deadline = None
                    logger.debug("Read %d byte(s) from serial", len(chunk))
                    parser.feed(chunk)
                elif (
                    reconnect_watchdog_deadline is not None
                    and time.monotonic() >= reconnect_watchdog_deadline
                ):
                    logger.warning(
                        "Serial reconnect on %s stayed idle for %.1fs after prior traffic; forcing reopen",
                        args.port,
                        reconnect_watchdog_grace,
                    )
                    _close_serial_port(ser)
                    ser = None
                    parser = None
                    reconnect_watchdog_deadline = None
                    time.sleep(args.reconnect_delay)
            except Exception as exc:
                logger.warning(
                    "Serial link lost on %s: %s; waiting %.1fs before reopen",
                    args.port,
                    exc,
                    args.reconnect_delay,
                )
                _close_serial_port(ser)
                ser = None
                parser = None
                reconnect_watchdog_deadline = None
                time.sleep(args.reconnect_delay)
    finally:
        _close_serial_port(ser)
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
        "--reconnect-watchdog-grace",
        type=float,
        default=DEFAULT_RECONNECT_WATCHDOG_GRACE,
        help=(
            "Force another serial reopen if a post-disconnect reconnect stays idle after prior "
            "traffic for this many seconds (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--audit-log",
        default=DEFAULT_AUDIT_LOG_PATH,
        help=f"Append-only plain-text audit log for llama.cpp request/response pairs (default: {DEFAULT_AUDIT_LOG_PATH})",
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
