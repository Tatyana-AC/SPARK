import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock


class PicoBootTests(unittest.TestCase):
    def _load_boot_module(self, module_overrides):
        module_name = f"_test_pico_boot_{uuid.uuid4().hex}"
        module_path = Path(__file__).resolve().parents[1] / "pico" / "boot.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)

        with mock.patch.dict(sys.modules, module_overrides, clear=False):
            assert spec.loader is not None
            spec.loader.exec_module(module)
        return module

    def test_boot_enables_only_data_cdc(self):
        enable_calls = []
        fake_supervisor = types.SimpleNamespace(set_usb_identification=lambda **_kwargs: None)
        fake_usb_cdc = types.SimpleNamespace(enable=lambda **kwargs: enable_calls.append(kwargs))
        fake_usb_hid = types.SimpleNamespace(devices=())

        def _enable_usb_hid(devices):
            fake_usb_hid.devices = tuple(devices)

        fake_usb_hid.disable = lambda: None
        fake_usb_hid.enable = _enable_usb_hid
        fake_usb_midi = types.SimpleNamespace(disable=lambda: None)
        fake_usb_config = types.SimpleNamespace(
            SPARK_PID=0x5350,
            SPARK_VID=0xC4C4,
            build_custom_hid_device=lambda _usb_hid: types.SimpleNamespace(usage_page=0xFF60, usage=0x61),
        )

        self._load_boot_module(
            {
                "supervisor": fake_supervisor,
                "usb_cdc": fake_usb_cdc,
                "usb_hid": fake_usb_hid,
                "usb_midi": fake_usb_midi,
                "pico.usb_config": fake_usb_config,
                "usb_config": fake_usb_config,
            }
        )

        self.assertEqual(enable_calls, [{"console": False, "data": True}])


if __name__ == "__main__":
    unittest.main()
