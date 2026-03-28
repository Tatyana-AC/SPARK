import time
import traceback

import board
import busio
import keypad
import supervisor
import usb_cdc
import usb_hid

try:
    from pico.jetson_transport import JetsonTransport
    from pico.serial_bridge import SerialBridge
    from pico.upload_protocol import AppCommand, StatusCode, UploadProtocolHandler
    from pico.usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE
except ImportError:
    from jetson_transport import JetsonTransport
    from serial_bridge import SerialBridge
    from upload_protocol import AppCommand, StatusCode, UploadProtocolHandler
    from usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE


UART_BAUDRATE = 115200
BUTTON_PINS = (board.GP14, board.GP15, board.GP16, board.GP17)
BUTTON_POLL_SLEEP_S = 0.002
CDC_RELAY_SLICE_BYTES = 64


jetson_transport = None
_last_response_signature = None
ERROR_LOG_PATH = "runtime_error.txt"


def _prepare_upload_result(app_command, text):
    if app_command == AppCommand.FEATURE_1:
        try:
            if jetson_transport is None:
                return {
                    "status_code": StatusCode.INTERNAL_ERROR,
                    "detail": "uart unavailable",
                    "accepted_count": 0,
                    "skipped_count": 0,
                }
            if jetson_transport.request_active:
                return {
                    "status_code": StatusCode.BUSY,
                    "detail": "busy",
                    "accepted_count": 0,
                    "skipped_count": 0,
                }

            try:
                payload = text.encode("utf-8")
            except Exception as exc:
                return {
                    "status_code": StatusCode.INTERNAL_ERROR,
                    "detail": f"encode:{type(exc).__name__}"[:18],
                    "accepted_count": 0,
                    "skipped_count": 0,
                }

            try:
                jetson_transport.start_request(payload)
            except Exception as exc:
                return {
                    "status_code": StatusCode.INTERNAL_ERROR,
                    "detail": f"start:{type(exc).__name__}"[:18],
                    "accepted_count": 0,
                    "skipped_count": 0,
                }
            return {
                "accepted_text": text,
                "accepted_count": len(text),
                "skipped_count": 0,
                "detail": "forwarded",
                "response_text": "",
                "response_active": True,
                "response_complete": False,
                "app_command": int(app_command),
            }
        except Exception as exc:
            return {
                "status_code": StatusCode.INTERNAL_ERROR,
                "detail": f"outer:{type(exc).__name__}"[:18],
                "accepted_count": 0,
                "skipped_count": 0,
            }

    return {
        "accepted_text": text,
        "accepted_count": len(text),
        "skipped_count": 0,
        "detail": "accepted",
        "response_text": f"PICO ECHO: {text}",
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


def _sync_response_state(protocol_handler, transport):
    global _last_response_signature

    signature = (
        transport.response_len,
        transport.response_complete,
        transport.request_active,
    )
    if signature == _last_response_signature:
        return

    protocol_handler.update_response_state(
        transport.response_bytes,
        complete=transport.response_complete,
        active=transport.request_active,
    )
    _last_response_signature = signature


# Allow CircuitPython to restart the runtime automatically when files on
# CIRCUITPY change. USB setup still lives in boot.py and still needs a reboot.
supervisor.runtime.autoreload = True

try:
    with open(ERROR_LOG_PATH, "w") as handle:
        handle.write("")
except OSError:
    pass

protocol_handler = UploadProtocolHandler(text_preparer=_prepare_upload_result)
custom_hid = _find_custom_hid_device()
uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0)
buttons = keypad.Keys(BUTTON_PINS, value_when_pressed=False, pull=True)
serial_bridge = SerialBridge(usb_cdc.data, uart)
jetson_transport = JetsonTransport(uart)

try:
    while True:
        serial_bridge.relay_once(max_chunk_size=CDC_RELAY_SLICE_BYTES)
        _drain_button_events(buttons, serial_bridge)
        jetson_transport.poll(max_chunk_size=CDC_RELAY_SLICE_BYTES)
        _sync_response_state(protocol_handler, jetson_transport)
        _drain_hid_reports(custom_hid, protocol_handler)

        time.sleep(BUTTON_POLL_SLEEP_S)
except Exception as exc:
    try:
        with open(ERROR_LOG_PATH, "w") as handle:
            handle.write("Unhandled exception in code.py\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=handle)
    except OSError:
        pass
    raise
