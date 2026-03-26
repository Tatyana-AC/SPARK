import json
from dataclasses import dataclass


ACK = 0x06
EOT = 0x04


def build_test_summary_request() -> str:
    return build_summary_request(
        app_name="Cursor",
        window_title="Weekly planning - SPARK transport debug",
        window_text=(
            "The user is reviewing the SPARK host to pico to jetson loop. "
            "They want to verify that the generated summary appears in the "
            "release output window without typing back into another app. "
            "The next step is to confirm the visible app can send a fake "
            "context payload and stream the Jetson response."
        ),
    )


def build_summary_request(app_name: str, window_title: str, window_text: str) -> str:
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


@dataclass
class SummaryStreamUpdate:
    text: str
    completed: bool


class SummaryStreamAccumulator:
    def __init__(self):
        self._buffer = bytearray()
        self.completed = False

    def reset(self):
        self._buffer.clear()
        self.completed = False

    @property
    def text(self) -> str:
        return self._buffer.decode("utf-8", errors="replace")

    def feed(self, payload: bytes) -> SummaryStreamUpdate:
        if self.completed:
            return SummaryStreamUpdate(text=self.text, completed=True)

        for byte in payload:
            if byte == ACK:
                continue
            if byte == EOT:
                self.completed = True
                break
            self._buffer.append(byte)

        return SummaryStreamUpdate(text=self.text, completed=self.completed)
