def is_typable_ascii(char):
    codepoint = ord(char)
    return char in ("\n", "\r", "\t") or 0x20 <= codepoint <= 0x7E


def prepare_typeback_text(text):
    typed = []
    skipped_count = 0

    for char in text:
        if is_typable_ascii(char):
            typed.append(char)
        else:
            skipped_count += 1

    typed_text = "".join(typed)
    return {
        "typed_text": typed_text,
        "typable_count": len(typed_text),
        "skipped_count": skipped_count,
        "detail": "best-effort",
    }


class TypebackService:
    def __init__(self, keyboard_layout):
        self._keyboard_layout = keyboard_layout
        self._queue = []

    def has_pending(self):
        return bool(self._queue)

    def enqueue_text(self, text):
        if text:
            self._queue.extend(text)

    def step(self, max_chars=1):
        written = 0
        while self._queue and written < max_chars:
            char = self._queue.pop(0)
            self._keyboard_layout.write(char)
            written += 1
        return written
