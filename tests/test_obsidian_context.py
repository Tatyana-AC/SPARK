import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from host_pc.accessibility.macos_provider import MacOSAccessibilityProvider
from host_pc.obsidian_context import resolve_obsidian_note_text


class ObsidianContextTests(unittest.TestCase):
    def test_resolves_markdown_body_when_accessibility_only_returns_title(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "2023-2024"
            vault.mkdir()
            (vault / ".obsidian").mkdir()
            note = vault / "East India Company note.md"
            note.write_text(
                '**1. The "Too Big to Fail" Problem**\n\n'
                "By 1772, the EIC was in a massive financial hole.\n\n"
                "- **The Bengal Famine:** Drastically reduced their revenue from India.\n",
                encoding="utf-8",
            )

            text = resolve_obsidian_note_text(
                app_name="Obsidian",
                window_title="Obsidian",
                window_text=(
                    "East India Company note - 2023-2024 - Obsidian 1.12.7\n"
                    "East India Company note - 2023-2024 - Obsidian 1.12.7"
                ),
                search_roots=[root],
            )

        self.assertIsNotNone(text)
        self.assertIn("Too Big to Fail", text)
        self.assertIn("Bengal Famine", text)
        self.assertNotIn("Obsidian 1.12.7", text)

    def test_returns_none_for_non_obsidian_apps(self):
        text = resolve_obsidian_note_text(
            app_name="Notes",
            window_title="Notes",
            window_text="East India Company note - 2023-2024 - Obsidian 1.12.7",
            search_roots=[],
        )

        self.assertIsNone(text)

    def test_macos_provider_uses_obsidian_note_body_for_title_only_window_text(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "2023-2024"
            vault.mkdir()
            (vault / ".obsidian").mkdir()
            (vault / "East India Company note.md").write_text(
                "The Tea Act kept the three-pence Townshend duty.",
                encoding="utf-8",
            )

            provider = MacOSAccessibilityProvider.__new__(MacOSAccessibilityProvider)
            provider.nsworkspace = mock.Mock()
            workspace = mock.Mock()
            workspace.activeApplication.return_value = {
                "NSApplicationName": "Obsidian",
                "NSApplicationProcessIdentifier": 123,
            }
            provider.nsworkspace.sharedWorkspace.return_value = workspace
            provider.ax_create_app = mock.Mock(return_value=object())
            focused_window = object()
            provider.ax_copy_attr = mock.Mock(
                side_effect=[
                    (0, focused_window),
                ]
            )

            def fake_extract(_element, text_parts, depth=0):
                text_parts.extend(
                    [
                        "East India Company note - 2023-2024 - Obsidian 1.12.7",
                        "East India Company note - 2023-2024 - Obsidian 1.12.7",
                    ]
                )

            provider._extract_text_recursive = fake_extract

            with mock.patch(
                "host_pc.accessibility.macos_provider.resolve_obsidian_note_text",
                wraps=lambda **kwargs: resolve_obsidian_note_text(
                    **kwargs,
                    search_roots=[root],
                ),
            ):
                text = provider.get_window_text()

        self.assertEqual(text, "The Tea Act kept the three-pence Townshend duty.")


if __name__ == "__main__":
    unittest.main()
