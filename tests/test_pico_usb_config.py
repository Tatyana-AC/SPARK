import unittest

from pico import usb_config


class FakeDeviceFactory:
    KEYBOARD = object()

    def __init__(self):
        self.last_kwargs = None

    def Device(self, **kwargs):
        self.last_kwargs = kwargs
        return kwargs


class UsbConfigTests(unittest.TestCase):
    def test_build_custom_hid_device_supplies_report_ids_and_lengths(self):
        fake_usb_hid = FakeDeviceFactory()

        device = usb_config.build_custom_hid_device(fake_usb_hid)

        self.assertEqual(device["usage_page"], usb_config.RAW_USAGE_PAGE)
        self.assertEqual(device["usage"], usb_config.RAW_USAGE_ID)
        self.assertEqual(device["report_ids"], (usb_config.RAW_REPORT_ID,))
        self.assertEqual(device["in_report_lengths"], (usb_config.REPORT_SIZE,))
        self.assertEqual(device["out_report_lengths"], (usb_config.REPORT_SIZE,))
        self.assertEqual(device["report_descriptor"], usb_config.CUSTOM_HID_REPORT_DESCRIPTOR)

    def test_descriptor_contains_matching_report_id_item(self):
        descriptor = usb_config.CUSTOM_HID_REPORT_DESCRIPTOR
        self.assertIn(bytes((0x85, usb_config.RAW_REPORT_ID)), descriptor)


if __name__ == "__main__":
    unittest.main()
