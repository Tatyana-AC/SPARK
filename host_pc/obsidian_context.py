"""
Obsidian-specific context recovery helpers for macOS accessibility gaps.

Obsidian is an Electron app, and on macOS its accessibility tree can expose
only the window/title chrome while the active Markdown editor body is missing.
When that happens, recover the active note from the local vault file.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

_OBSIDIAN_APP_RE = re.compile(r"\bobsidian\b", re.IGNORECASE)
_OBSIDIAN_SUFFIX_RE = re.compile(r"\s+-\s+Obsidian(?:\s+\d+(?:\.\d+)*)?\s*$", re.IGNORECASE)


def _default_search_roots() -> tuple[Path, ...]:
    home = Path.home()
    roots = [
        home / "Documents",
        home / "Desktop",
        home / "Library" / "Mobile Documents",
    ]
    return tuple(root for root in roots if root.exists())


def _clean_title_line(value: str) -> str:
    return _OBSIDIAN_SUFFIX_RE.sub("", value.strip()).strip()


def _title_and_vault_candidates(window_title: str | None, window_text: str | None) -> tuple[list[str], list[str]]:
    raw_lines = []
    if window_title:
        raw_lines.append(window_title)
    if window_text:
        raw_lines.extend(line for line in window_text.splitlines() if line.strip())

    note_titles: list[str] = []
    vault_names: list[str] = []
    seen_titles = set()
    seen_vaults = set()

    for raw_line in raw_lines:
        line = _clean_title_line(raw_line)
        if not line or line.lower() == "obsidian":
            continue

        parts = [part.strip() for part in line.split(" - ") if part.strip()]
        candidates = [line]
        if len(parts) >= 2:
            vault = parts[-1]
            if vault.lower() != "obsidian" and vault not in seen_vaults:
                vault_names.append(vault)
                seen_vaults.add(vault)
            candidates.append(" - ".join(parts[:-1]))

        for candidate in candidates:
            if candidate and candidate.lower() != "obsidian" and candidate not in seen_titles:
                note_titles.append(candidate)
                seen_titles.add(candidate)

    return note_titles, vault_names


@lru_cache(maxsize=1)
def _cached_default_vaults() -> tuple[Path, ...]:
    return tuple(_iter_obsidian_vaults(_default_search_roots()))


def _iter_obsidian_vaults(search_roots: Iterable[Path]) -> Iterable[Path]:
    for root in search_roots:
        root = Path(root).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        for current, dirs, _files in os.walk(root):
            current_path = Path(current)
            if ".obsidian" in dirs:
                yield current_path
                dirs[:] = [name for name in dirs if name != ".obsidian"]
                continue
            dirs[:] = [
                name
                for name in dirs
                if not name.startswith(".") and name not in {"node_modules", "__pycache__"}
            ]


def _find_note_file(
    note_titles: list[str],
    vault_names: list[str],
    *,
    search_roots: Iterable[Path] | None,
) -> Optional[Path]:
    if search_roots is None:
        vaults = list(_cached_default_vaults())
    else:
        vaults = list(_iter_obsidian_vaults(search_roots))

    preferred = []
    fallback = []
    normalized_vault_names = {name.casefold() for name in vault_names}
    for vault in vaults:
        if normalized_vault_names and vault.name.casefold() in normalized_vault_names:
            preferred.append(vault)
        else:
            fallback.append(vault)

    for vault in [*preferred, *fallback]:
        for title in note_titles:
            filename = f"{title}.md"
            matches = sorted(
                vault.rglob(filename),
                key=lambda path: (-path.stat().st_mtime, len(path.parts)),
            )
            if matches:
                return matches[0]

    return None


def resolve_obsidian_note_text(
    *,
    app_name: str | None,
    window_title: str | None,
    window_text: str | None,
    search_roots: Iterable[Path] | None = None,
) -> Optional[str]:
    """Return the active Obsidian note body when AX text is only title chrome."""

    if not _OBSIDIAN_APP_RE.search(app_name or ""):
        return None

    note_titles, vault_names = _title_and_vault_candidates(window_title, window_text)
    if not note_titles:
        return None

    note_file = _find_note_file(note_titles, vault_names, search_roots=search_roots)
    if note_file is None:
        return None

    try:
        note_text = note_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not note_text:
        return None

    raw_window_text = (window_text or "").strip()
    if len(note_text) <= len(raw_window_text) and note_text in raw_window_text:
        return None

    return note_text
