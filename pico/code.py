import time

import board
import busio
import keypad
import supervisor
import usb_cdc
import usb_hid

try:
    from pico.serial_bridge import SerialBridge
    from pico.upload_protocol import UploadProtocolHandler
    from pico.usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE
except ImportError:
    from serial_bridge import SerialBridge
    from upload_protocol import UploadProtocolHandler
    from usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE


UART_BAUDRATE = 115200
BUTTON_PINS = (board.GP14, board.GP15, board.GP16, board.GP17)
BUTTON_POLL_SLEEP_S = 0.002
CDC_RELAY_SLICE_BYTES = 64


def _prepare_upload_result(app_command, text):
    return {
        "accepted_text": text,
        "accepted_count": len(text),
        "skipped_count": 0,
        "detail": "accepted",
        "app_command": int(app_command),
    }


def _find_custom_hid_device():
    for device in usb_hid.devices:
        if device.usage_page == RAW_USAGE_PAGE and device.usage == RAW_USAGE_ID:
            return device
    raise RuntimeError("SPARK custom HID device not enabled")


def _drain_button_events(buttons, serial_bridge):
    while True:
        event = buttons.events.get()
        if event is None:
            return
        if event.pressed:
            serial_bridge.inject_button_press(event.key_number)


def _drain_hid_reports(custom_hid, protocol_handler):
    while True:
        report = custom_hid.get_last_received_report(RAW_REPORT_ID)
        if report is None:
            return
        reply = protocol_handler.handle_report(report)
        if reply is not None:
            custom_hid.send_report(reply, RAW_REPORT_ID)


supervisor.runtime.autoreload = False

protocol_handler = UploadProtocolHandler(text_preparer=_prepare_upload_result)
custom_hid = _find_custom_hid_device()
uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE)
buttons = keypad.Keys(BUTTON_PINS, value_when_pressed=False, pull=True)
serial_bridge = SerialBridge(usb_cdc.data, uart)

while True:
    serial_bridge.relay_once(max_chunk_size=CDC_RELAY_SLICE_BYTES)
    _drain_button_events(buttons, serial_bridge)
    _drain_hid_reports(custom_hid, protocol_handler)

    time.sleep(BUTTON_POLL_SLEEP_S)
