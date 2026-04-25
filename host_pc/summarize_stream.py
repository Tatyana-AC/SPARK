import json

# HID upload limit is 4096 bytes; reserve headroom for JSON envelope + metadata.
_MAX_WINDOW_TEXT_CHARS = 3500


def build_context_key(*, app_name: str, window_title: str, url: str | None) -> str:
    """Build the same context-key shape Jetson persists for each session."""
    app_name = app_name if isinstance(app_name, str) else ""
    window_title = window_title if isinstance(window_title, str) else ""
    url = url if isinstance(url, str) else ""

    app_name_value = app_name.strip()
    anchor_value = url or window_title
    if not app_name_value or not anchor_value.strip():
        raise ValueError("context key requires app_name and either url or window_title")
    return f"{app_name}|{url}" if url else f"{app_name}|{window_title}"


def build_summarize_command() -> str:
    """Lightweight summarize signal — Jetson pulls context from its own DB."""
    return json.dumps({"command": "summarize"})


def build_synthesize_session_request(anchor_context_key: str, window_minutes: int = 30) -> str:
    """Build an anchored session synthesis request."""
    anchor_context_key = (anchor_context_key or "").strip()
    if not anchor_context_key:
        raise ValueError("anchor_context_key is required")
    window_minutes = int(window_minutes)
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    return json.dumps(
        {
            "command": "synthesize_session",
            "window_minutes": window_minutes,
            "anchor_context_key": anchor_context_key,
        }
    )


def build_test_summary_request() -> str:
    """Fixed debug payload for smoke-testing the summarize round-trip."""
    return build_summarize_command()


def build_summary_request(app_name: str, window_title: str, window_text: str) -> str:
    """Build a summarize_window request with inline context.

    Truncates window_text to fit within the Pico HID upload size limit (4096 bytes).
    """
    app_name = (app_name or "").strip() or "(unknown app)"
    window_title = (window_title or "").strip() or "(untitled window)"
    window_text = (window_text or "").strip()

    if len(window_text) > _MAX_WINDOW_TEXT_CHARS:
        window_text = window_text[:_MAX_WINDOW_TEXT_CHARS]

    return json.dumps(
        {
            "command": "summarize_window",
            "app_name": app_name,
            "window_title": window_title,
            "window_text": window_text,
        }
    )


def build_reformat_request(selected_text: str) -> str:
    """Build a reformat_selection request with only selected text context."""
    selected_text = (selected_text or "").strip()

    if len(selected_text) > _MAX_WINDOW_TEXT_CHARS:
        selected_text = selected_text[:_MAX_WINDOW_TEXT_CHARS]

    return json.dumps(
        {
            "command": "reformat_selection",
            "selected_text": selected_text,
        }
    )


def build_respond_request(previous_user_input: str) -> str:
    """Build a respond_selection request from automatically extracted draft text."""
    previous_user_input = (previous_user_input or "").strip()

    if len(previous_user_input) > _MAX_WINDOW_TEXT_CHARS:
        previous_user_input = previous_user_input[:_MAX_WINDOW_TEXT_CHARS]

    return json.dumps(
        {
            "command": "respond_selection",
            "previous_user_input": previous_user_input,
        }
    )


def build_keyword_search_request(selected_text: str) -> str:
    """Build a keyword_search request from selected text."""
    selected_text = (selected_text or "").strip()

    if len(selected_text) > _MAX_WINDOW_TEXT_CHARS:
        selected_text = selected_text[:_MAX_WINDOW_TEXT_CHARS]

    return json.dumps(
        {
            "command": "keyword_search",
            "selected_text": selected_text,
        }
    )
