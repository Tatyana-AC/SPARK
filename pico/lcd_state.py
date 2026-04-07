DEFAULT_HIGHLIGHT_SEC = 0.4


class LcdStateChange:
    __slots__ = ("previous_active", "active_index", "visible_changed")

    def __init__(self, *, previous_active, active_index, visible_changed):
        self.previous_active = previous_active
        self.active_index = active_index
        self.visible_changed = visible_changed


class LcdState:
    def __init__(self, *, highlight_sec=DEFAULT_HIGHLIGHT_SEC):
        self.highlight_sec = highlight_sec
        self.active_index = None
        self.press_time = 0.0
        self.highlight_expires_at = None

    def press(self, index, *, now):
        previous_active = self.active_index
        self.active_index = index
        self.press_time = now
        self.highlight_expires_at = now + self.highlight_sec
        return LcdStateChange(
            previous_active=previous_active,
            active_index=self.active_index,
            visible_changed=previous_active != index,
        )

    def tick(self, *, now):
        previous_active = self.active_index
        if previous_active is None:
            return LcdStateChange(previous_active=None, active_index=None, visible_changed=False)
        if now <= self.highlight_expires_at:
            return LcdStateChange(
                previous_active=previous_active,
                active_index=previous_active,
                visible_changed=False,
            )

        self.active_index = None
        self.highlight_expires_at = None
        return LcdStateChange(previous_active=previous_active, active_index=None, visible_changed=True)
