# Release Output Markdown And Copy Design

## User Requirements

- Render LLM Markdown output more properly in the release output panel: from the user's question about displaying Markdown output.
- Preserve reliable copy-paste behavior from the release output panel: from the user's report that manual copy-paste can make SPARK and the paste target unresponsive.
- Place the Copy button on the left side of the panel with the existing suggested-action buttons: from the user's request after trying the first Markdown rendering version.

## Agent Design Decisions

- Keep one release output display, but treat it as a rendered Markdown reading surface: serves Markdown output rendering while avoiding a larger UI redesign.
- Store the raw output text separately from the rendered widget contents: serves reliable copy-paste by preserving the exact text that should be copied.
- Add an explicit Copy Output action that writes raw plain text to the clipboard: serves reliable copy-paste by avoiding rich-text clipboard serialization from manual selection.
- Continue using `QTextEdit` for the display because PyQt can render Markdown there with `setMarkdown(...)`: serves Markdown output rendering without adding a web view dependency.
- Use the existing left-column `ActionButton` component for Copy Output instead of a compact release-output header button: serves the requested placement and keeps the button visually consistent with the three existing suggested actions.

## Behavior

The release output panel should render final and streaming LLM output as Markdown. The visible text should remain selectable for inspection, but the intended copy path is the Copy Output button in the left-side suggested actions area. That button copies the raw output string currently represented by the panel, not the rich-text or HTML representation.

Empty fallback messages remain plain text. Release echo output still displays in the same panel and is copied as plain text through the same button.

## Testing

Tests should verify user-facing behavior:

- Markdown content is passed to the release output renderer through the helper path.
- The Copy button copies the stored raw output text, including Markdown syntax.
- The Copy button appears with the left-side suggested-action buttons.
- Existing plain-text release output flows still expose the expected plain text through `toPlainText()`.
