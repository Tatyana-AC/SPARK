class ButtonDefinition:
    __slots__ = ("index", "physical_number", "name", "action_label")

    def __init__(self, index, physical_number, name, action_label):
        self.index = index
        self.physical_number = physical_number
        self.name = name
        self.action_label = action_label


BUTTON_DEFINITIONS = (
    ButtonDefinition(0, 1, "PB1", "SYNTHESIS"),
    ButtonDefinition(1, 2, "PB2", "REFORMAT"),
    ButtonDefinition(2, 3, "PB3", "SEARCH"),
    ButtonDefinition(3, 4, "PB4", "RESPOND"),
)

ACTIONS = tuple(button.action_label for button in BUTTON_DEFINITIONS)

_BUTTON_BY_INDEX = {button.index: button for button in BUTTON_DEFINITIONS}
_RUNTIME_ALIAS_BY_KIND = {
    "button": "button",
    "pre_press": "pre",
    "post_press": "post",
    "draw_press": "draw",
    "press_done": "done",
    "idle_prev": "idle",
    "render_press": "rpress",
    "render_press_done": "rdone",
}


def button_definition(index):
    return _BUTTON_BY_INDEX.get(index)


def _physical_text(index):
    button = button_definition(index)
    if button is None:
        return "?"
    return str(button.physical_number)


def debug_label(kind, index):
    return f"{kind}:{_physical_text(index)}"


def runtime_alias(kind, index):
    alias = _RUNTIME_ALIAS_BY_KIND.get(kind, kind)
    return f"{alias}:{_physical_text(index)}"


def runtime_label_alias(label):
    if ":" not in label:
        return label
    kind, physical_text = label.split(":", 1)
    alias = _RUNTIME_ALIAS_BY_KIND.get(kind, kind)
    return f"{alias}:{physical_text}"


def runtime_checkpoint_alias(checkpoint):
    if checkpoint.startswith("before_ui_press:"):
        return "ui_pre"
    if checkpoint.startswith("after_ui_press:"):
        return "ui_post"
    return checkpoint
