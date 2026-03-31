import json


def build_summarize_command() -> str:
    """Lightweight summarize signal — Jetson pulls context from its own DB."""
    return json.dumps({"command": "summarize"})


def build_test_summary_request() -> str:
    """Fixed debug payload for smoke-testing the summarize round-trip."""
    return build_summarize_command()


def build_summary_request(app_name: str, window_title: str, window_text: str) -> str:
    """Legacy full-payload summarize request (kept for backwards compatibility)."""
    app_name = (app_name or "").strip() or "(unknown app)"
    window_title = (window_title or "").strip() or "(untitled window)"
    window_text = (window_text or "").strip()

    return json.dumps(
        {
            "command": "summarize_window",
            "app_name": app_name,
            "window_title": window_title,
            "window_text": window_text,
        }
    )
