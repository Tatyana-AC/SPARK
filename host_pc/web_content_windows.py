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
STRONG_BROWSER_SHELL_TOKENS = {
    "back",
    "forward",
    "reload",
    "address",
    "bookmarks",
    "extensions",
    "profile",
    "settings",
    "menu",
    "favorites",
    "home",
    "history",
    "grammarly",
    "ublock",
    "origin",
    "onetab",
    "bitwarden",
}
PAGE_BOILERPLATE_FRAGMENTS = {
    "from wikipedia, the free encyclopedia",
}
WINDOWS_LIVE_EXTRACTION_BUDGET_SECONDS = 0.9
_INLINE_CITATION_RE = re.compile(r"\[(?:\d+|[A-Za-z]+)(?:\s*,\s*(?:\d+|[A-Za-z]+))*\]")
_PARAGRAPH_BREAK_MIN_CHARS = 350


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


def _strip_inline_citations(text: str) -> str:
    cleaned = _INLINE_CITATION_RE.sub("", text)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    return cleaned


def _paragraph_chunks(text: str) -> list[str]:
    paragraphs = []
    for chunk in re.split(r"(?:\r?\n\s*){2,}", _strip_inline_citations(text)):
        normalized = _normalize_text(chunk)
        if normalized:
            paragraphs.append(normalized)
    return paragraphs


def _ends_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", text))


def _should_start_new_paragraph(current: str, next_part: str) -> bool:
    return bool(current and len(current) >= _PARAGRAPH_BREAK_MIN_CHARS and _ends_sentence(current))


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


def _strong_shell_token_count(tokens: list[str]) -> int:
    return len({token for token in tokens if token in STRONG_BROWSER_SHELL_TOKENS})


def evaluate_candidate(candidate: ScoredTextCandidate) -> WindowsLiveExtractionResult:
    display_text = "\n\n".join(_paragraph_chunks(candidate.text))
    text = _normalize_text(display_text)
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
    strong_shell_count = _strong_shell_token_count(tokens)

    if candidate.source_hint in {"focused_element", "full_window", "uia_pane", "uia_edit", "uia_control"} and strong_shell_count >= 3:
        return WindowsLiveExtractionResult(
            text=None,
            source=candidate.source_hint,
            error="candidate text rejected by heuristics",
            is_useful=False,
            quality_score=0.0,
        )

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
            text=display_text or text,
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


def _looks_like_browser_chrome_candidate(text: str, app_name: str, window_title: str) -> bool:
    normalized_text = _normalize_text(text).lower()
    normalized_title = _normalize_text(window_title).lower()
    normalized_app = (app_name or "").strip().lower()

    if normalized_title and normalized_text == normalized_title:
        return True

    browser_brand_tokens = {"google chrome", "microsoft edge", "brave", "chrome", "msedge"}
    if normalized_app:
        browser_brand_tokens.add(normalized_app)

    if any(token in normalized_text for token in browser_brand_tokens) and len(normalized_text) < 180:
        return True

    return False


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


def _merge_candidate_text(parts: list[str]) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    current = ""
    for part in parts:
        for paragraph in _paragraph_chunks(part):
            normalized = _normalize_text(paragraph)
            if not normalized or normalized in seen:
                continue
            if normalized.lower() in PAGE_BOILERPLATE_FRAGMENTS:
                continue
            seen.add(normalized)
            if current and not _should_start_new_paragraph(current, paragraph):
                current = f"{current} {paragraph}"
                continue
            if current:
                merged.append(current)
            current = paragraph
    if current:
        merged.append(current)
    return "\n\n".join(merged)


def _aggregate_useful_candidates(candidates: list[WindowsLiveExtractionResult]) -> Optional[WindowsLiveExtractionResult]:
    if len(candidates) < 2:
        return None

    merged_text = _merge_candidate_text([candidate.text or "" for candidate in candidates])
    if not merged_text:
        return None

    source = next(
        (candidate.source for candidate in candidates if candidate.source and candidate.source.startswith("uia_document")),
        candidates[0].source or "uia_control",
    )
    quality = max(candidate.quality_score for candidate in candidates)
    return WindowsLiveExtractionResult(
        text=merged_text,
        source=source,
        error=None,
        is_useful=True,
        quality_score=max(quality, 0.7),
    )


def extract_windows_live_tab_text(
    url: str,
    app_name: str,
    window_target: Optional[int] = None,
) -> WindowsLiveExtractionResult:
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
    useful_candidates: list[WindowsLiveExtractionResult] = []
    window_title = ""
    try:
        window_title = window.window_text() or ""
    except Exception:
        window_title = ""

    controls = _collect_candidate_controls(window)
    start = time.monotonic()

    for index, control in enumerate(controls):
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

        if _looks_like_browser_chrome_candidate(raw_text, app_name, window_title):
            continue

        candidate = ScoredTextCandidate(
            text=raw_text,
            source_hint=_control_source_hint(control),
            score=float(index),
        )
        evaluated = evaluate_candidate(candidate)
        if evaluated.is_useful:
            useful_candidates.append(evaluated)
            if not best_result or evaluated.quality_score > best_result.quality_score:
                best_result = evaluated

    aggregated_result = _aggregate_useful_candidates(useful_candidates)
    if aggregated_result and (
        not best_result
        or len(aggregated_result.text or "") > max(len(best_result.text or "") + 40, int(len(best_result.text or "") * 1.5))
    ):
        return aggregated_result

    if best_result:
        return best_result

    return WindowsLiveExtractionResult(
        text=None,
        source="live_tab",
        error="No suitable candidate control found",
        is_useful=False,
        quality_score=0.0,
    )
