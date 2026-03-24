from dataclasses import dataclass, field
from typing import Optional


def append_capture_line(
    lines: list[str],
    line: str,
    max_lines: int = 6,
    dedupe: bool = False,
) -> list[str]:
    if dedupe and lines and lines[-1] == line:
        return list(lines)

    updated = [*lines, line]
    if len(updated) > max_lines:
        updated = updated[-max_lines:]
    return updated


@dataclass
class LiveCaptureFeed:
    max_lines: int = 6
    lines: list[str] = field(default_factory=list)
    last_poll_line: Optional[str] = None

    def push_poll_line(self, line: str) -> None:
        if line == self.last_poll_line:
            return
        self.last_poll_line = line
        self.lines = append_capture_line(self.lines, line, max_lines=self.max_lines)

    def push_event_line(self, line: str) -> None:
        self.lines = append_capture_line(self.lines, line, max_lines=self.max_lines)
