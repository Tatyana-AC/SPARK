import builtins
import importlib
import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest


def _load_module(name):
    spec = importlib.util.find_spec(name)
    assert spec is not None, f"missing module: {name}"
    return importlib.import_module(name)


def _load_module_from_path(module_name, file_name):
    module_path = Path(__file__).resolve().parents[1] / "pico" / file_name
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_lcd_state_imports_without_dataclasses_module():
    original_import = builtins.__import__

    def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dataclasses":
            raise ImportError("No module named 'dataclasses'")
        return original_import(name, globals, locals, fromlist, level)

    sys.modules.pop("pico.lcd_state", None)
    with mock.patch("builtins.__import__", side_effect=tracking_import):
        module = _load_module_from_path("_test_pico_lcd_state_no_dataclasses", "lcd_state.py")

    state = module.LcdState(highlight_sec=0.4)
    change = state.press(1, now=1.0)

    assert isinstance(change, module.LcdStateChange)
    assert change.active_index == 1


def test_press_sets_active_index_and_deadline():
    lcd_state = _load_module("pico.lcd_state")
    state = lcd_state.LcdState(highlight_sec=0.4)

    change = state.press(1, now=10.0)

    assert change.visible_changed is True
    assert change.previous_active is None
    assert change.active_index == 1
    assert state.active_index == 1
    assert state.press_time == 10.0
    assert state.highlight_expires_at == pytest.approx(10.4)


def test_same_cell_repress_refreshes_deadline():
    lcd_state = _load_module("pico.lcd_state")
    state = lcd_state.LcdState(highlight_sec=0.4)

    state.press(2, now=4.0)
    change = state.press(2, now=4.2)

    assert change.visible_changed is False
    assert change.previous_active == 2
    assert change.active_index == 2
    assert state.active_index == 2
    assert state.press_time == 4.2
    assert state.highlight_expires_at == pytest.approx(4.6)


def test_tick_clears_after_timeout():
    lcd_state = _load_module("pico.lcd_state")
    state = lcd_state.LcdState(highlight_sec=0.4)

    state.press(3, now=8.0)

    unchanged = state.tick(now=8.39)
    assert unchanged.visible_changed is False
    assert unchanged.previous_active == 3
    assert unchanged.active_index == 3
    assert state.active_index == 3

    change = state.tick(now=8.41)

    assert change.visible_changed is True
    assert change.previous_active == 3
    assert change.active_index is None
    assert state.active_index is None
    assert state.press_time == 8.0
    assert state.highlight_expires_at is None
