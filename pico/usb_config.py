SPARK_VID = 0xC4C4
SPARK_PID = 0x5350
RAW_USAGE_PAGE = 0xFF60
RAW_USAGE_ID = 0x61
REPORT_SIZE = 32
RAW_REPORT_ID = 4


# Vendor-defined HID interface with one 32-byte input report and one 32-byte
# output report. The host uses this for the upload/control protocol.
CUSTOM_HID_REPORT_DESCRIPTOR = bytes(
    (
        0x06, 0x60, 0xFF,  # Usage Page (Vendor 0xFF60)
        0x09, 0x61,        # Usage (0x61)
        0xA1, 0x01,        # Collection (Application)
        0x85, RAW_REPORT_ID,  # Report ID
        0x15, 0x00,        # Logical Minimum (0)
        0x26, 0xFF, 0x00,  # Logical Maximum (255)
        0x75, 0x08,        # Report Size (8 bits)
        0x95, REPORT_SIZE, # Report Count (32 bytes)
        0x09, 0x62,        # Usage (0x62)
        0x81, 0x02,        # Input (Data,Var,Abs)
        0x95, REPORT_SIZE, # Report Count (32 bytes)
        0x09, 0x63,        # Usage (0x63)
        0x91, 0x02,        # Output (Data,Var,Abs)
        0xC0,              # End Collection
    )
)


def build_custom_hid_device(usb_hid):
    return usb_hid.Device(
        report_descriptor=CUSTOM_HID_REPORT_DESCRIPTOR,
        usage_page=RAW_USAGE_PAGE,
        usage=RAW_USAGE_ID,
        report_ids=(RAW_REPORT_ID,),
        in_report_lengths=(REPORT_SIZE,),
        out_report_lengths=(REPORT_SIZE,),
    )
