"""Windows-specific browser content extraction helpers.

The helpers in this module use UI Automation to find likely document-like
controls and apply conservative heuristics before returning extracted text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional
import re
import time

from . import browser_windows


MIN_CONTENT_LEN = 24
MAX_UI_LABEL_RATIO = 0.30
MAX_REPEAT_RATIO = 0.60
MIN_TOKEN_DIVERSITY = 0.38
BROWSER_NOISE_TOKENS = {
    "back",
    "forward",
    "reload",
    "address",
    "search",
    "bookmarks",
    "extensions",
    "settings",
    "profile",
    "menu",
    "tabs",
    "new",
    "tab",
    "home",
    "favorites",
    "history",
    "help",
}
WINDOWS_LIVE_EXTRACTION_BUDGET_SECONDS = 0.9
WINDOWS_LIVE_EXTRACTION_MAX_CANDIDATES = 120


@dataclass
class ScoredTextCandidate:
    text: str
    score: float = 0.0
    source_hint: str = "uia_control"


@dataclass
class WindowsLiveExtractionResult:
    text: Optional[str] = None
    source: Optional[str] = None
    error: Optional[str] = None
    is_useful: bool = False
    quality_score: float = 0.0


def _normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub("\\s+", " ", text).strip()


def _tokenize(text: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[\w']+", text, flags=re.UNICODE)]
    if len(tokens) <= 1 and any(ord(ch) > 127 for ch in text):
        return [char.lower() for char in text if char.isalpha() or char.isdigit()]
    return tokens


def _repeat_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    top = 1
    total = len(tokens)
    for token, count in _token_counts(tokens).items():
        if count > top:
            top = count
    return top / float(total)


def _token_counts(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _noise_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    noise_count = sum(1 for token in tokens if token in BROWSER_NOISE_TOKENS)
    return noise_count / float(len(tokens))


def evaluate_candidate(candidate: ScoredTextCandidate) -> WindowsLiveExtractionResult:
    text = _normalize_text(candidate.text)
    if not text:
        return WindowsLiveExtractionResult(
            text=None,
            source=candidate.source_hint,
            error="candidate text was empty",
            is_useful=False,
            quality_score=0.0,
        )

    if len(text) < MIN_CONTENT_LEN:
        return WindowsLiveExtractionResult(
            text=None,
            source=candidate.source_hint,
            error="candidate text is too short",
            is_useful=False,
            quality_score=0.0,
        )

    tokens = _tokenize(text)
    if not tokens:
        return WindowsLiveExtractionResult(
            text=None,
            source=candidate.source_hint,
            error="candidate text has no extractable tokens",
            is_useful=False,
            quality_score=0.0,
        )

    unique_ratio = len(set(tokens)) / float(len(tokens))
    label_ratio = _noise_ratio(tokens)
    repeat_ratio = _repeat_ratio(tokens)

    length_score = min(1.0, len(text) / 2000.0)
    quality_score = (
        length_score * 0.35
        + unique_ratio * 0.35
        + (1.0 - min(1.0, label_ratio / MAX_UI_LABEL_RATIO)) * 0.15
        + (1.0 - min(1.0, repeat_ratio / MAX_REPEAT_RATIO)) * 0.15
    )
    if (
        len(text) >= MIN_CONTENT_LEN
        and unique_ratio >= MIN_TOKEN_DIVERSITY
        and label_ratio <= MAX_UI_LABEL_RATIO
        and repeat_ratio <= MAX_REPEAT_RATIO
        and quality_score >= 0.45
    ):
        return WindowsLiveExtractionResult(
            text=text,
            source=candidate.source_hint,
            error=None,
            is_useful=True,
            quality_score=quality_score,
        )

    return WindowsLiveExtractionResult(
        text=None,
        source=candidate.source_hint,
        error="candidate text rejected by heuristics",
        is_useful=False,
        quality_score=quality_score,
    )


def _evaluate_fallback_text(text: str, source_hint: str) -> WindowsLiveExtractionResult:
    candidate = ScoredTextCandidate(text=text, source_hint=source_hint)
    return evaluate_candidate(candidate)


def evaluate_focused_fallback(text: str) -> WindowsLiveExtractionResult:
    """Evaluate focused accessibility text with Windows browser fallback heuristics."""
    return _evaluate_fallback_text(text, source_hint="focused_element")


def evaluate_window_fallback(text: str) -> WindowsLiveExtractionResult:
    """Evaluate full-window accessibility text with the same heuristics."""
    return _evaluate_fallback_text(text, source_hint="full_window")


def _control_source_hint(control: Any) -> str:
    try:
        control_type = control.control_type()
        if isinstance(control_type, str):
            return f"uia_{control_type.lower()}"
    except Exception:
        pass
    return "uia_control"


def _collect_candidate_controls(window: Any) -> list[Any]:
    controls = []
    if not window or not hasattr(window, "descendants"):
        return controls

    control_types: Iterable[str] = [
        "Document",
        "Pane",
        "Text",
        "Edit",
    ]
    for control_type in control_types:
        try:
            controls.extend(window.descendants(control_type=control_type))
        except Exception:
            pass

    if not controls:
        try:
            controls.extend(window.descendants())
        except Exception:
            pass

    return controls


def extract_windows_live_tab_text(
    url: str,
    app_name: str,
    window_target: Optional[int] = None,
) -> WindowsLiveExtractionResult:
    start = time.monotonic()

    try:
        window = browser_windows._connect_to_active_window(window_target)
    except Exception as exc:
        return WindowsLiveExtractionResult(
            text=None,
            source="live_tab",
            error=f"Windows live extraction dependency failure: {exc}",
            is_useful=False,
            quality_score=0.0,
        )

    if not window:
        return WindowsLiveExtractionResult(
            text=None,
            source="live_tab",
            error="Unable to connect to active browser window",
            is_useful=False,
            quality_score=0.0,
        )

    best_result: Optional[WindowsLiveExtractionResult] = None
    controls = _collect_candidate_controls(window)

    for index, control in enumerate(controls[:WINDOWS_LIVE_EXTRACTION_MAX_CANDIDATES]):
        if time.monotonic() - start > WINDOWS_LIVE_EXTRACTION_BUDGET_SECONDS:
            if best_result and best_result.text:
                return best_result
            return WindowsLiveExtractionResult(
                text=None,
                source="live_tab",
                error="Windows live extraction timed out",
                is_useful=False,
                quality_score=0.0,
            )

        try:
            raw_text = browser_windows._control_text(control)
        except Exception as exc:
            raw_text = ""
            logger = None
            if hasattr(browser_windows, "logger"):
                logger = browser_windows.logger
            if logger:
                logger.debug("Failed reading text from candidate control: %s", exc)

        if not raw_text:
            continue

        candidate = ScoredTextCandidate(
            text=raw_text,
            source_hint=_control_source_hint(control),
            score=float(index),
        )
        evaluated = evaluate_candidate(candidate)
        if evaluated.is_useful:
            if not best_result or evaluated.quality_score > best_result.quality_score:
                best_result = evaluated
            if evaluated.quality_score >= 0.8:
                return WindowsLiveExtractionResult(
                    text=evaluated.text,
                    source="live_tab",
                    error=None,
                    is_useful=True,
                    quality_score=evaluated.quality_score,
                )

    if best_result:
        return best_result

    return WindowsLiveExtractionResult(
        text=None,
        source="live_tab",
        error="No suitable candidate control found",
        is_useful=False,
        quality_score=0.0,
    )
