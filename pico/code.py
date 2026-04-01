from runtime_runner import run_with_diagnostics


UART_BAUDRATE = 115200
BUTTON_POLL_SLEEP_S = 0.002
CDC_RELAY_SLICE_BYTES = 64
ERROR_LOG_PATH = "runtime_error.txt"
STARTUP_TRACE_PATH = "startup_trace.txt"

jetson_transport = None
_last_response_signature = None


def _prepare_upload_result(app_command, text, *, AppCommand, StatusCode):
    global jetson_transport

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


def _find_custom_hid_device(usb_hid, raw_usage_page, raw_usage_id):
    for device in usb_hid.devices:
        if device.usage_page == raw_usage_page and device.usage == raw_usage_id:
            return device
    raise RuntimeError("SPARK custom HID device not enabled")


def _drain_button_events(buttons, lcd_ui, now):
    while True:
        event = buttons.events.get()
        if event is None:
            return
        if event.pressed:
            lcd_ui.handle_press(event.key_number, now=now)


def _drain_hid_reports(custom_hid, protocol_handler, raw_report_id):
    while True:
        report = custom_hid.get_last_received_report(raw_report_id)
        if report is None:
            return
        reply = protocol_handler.handle_report(report)
        if reply is not None:
            custom_hid.send_report(reply, raw_report_id)


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


def _main(record_step):
    global jetson_transport

    import time
    import board
    import busio
    import keypad
    import supervisor
    import usb_cdc
    import usb_hid

    record_step("core imports ready")

    try:
        from pico.lcd_ui import initialize_lcd_ui
        from pico.pin_config import BUTTON_PIN_NUMBERS
        from pico.jetson_transport import JetsonTransport
        from pico.serial_bridge import SerialBridge
        from pico.upload_protocol import AppCommand, StatusCode, UploadProtocolHandler
        from pico.usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE
    except ImportError:
        from lcd_ui import initialize_lcd_ui
        from pin_config import BUTTON_PIN_NUMBERS
        from jetson_transport import JetsonTransport
        from serial_bridge import SerialBridge
        from upload_protocol import AppCommand, StatusCode, UploadProtocolHandler
        from usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE

    record_step("spark modules ready")

    supervisor.runtime.autoreload = True
    record_step("autoreload enabled")

    button_pins = tuple(getattr(board, f"GP{pin}") for pin in BUTTON_PIN_NUMBERS)
    protocol_handler = UploadProtocolHandler(
        text_preparer=lambda app_command, text: _prepare_upload_result(
            app_command,
            text,
            AppCommand=AppCommand,
            StatusCode=StatusCode,
        )
    )
    record_step("protocol handler ready")

    custom_hid = _find_custom_hid_device(usb_hid, RAW_USAGE_PAGE, RAW_USAGE_ID)
    record_step("custom hid ready")

    uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0)
    record_step("uart ready")

    buttons = keypad.Keys(button_pins, value_when_pressed=False, pull=True)
    record_step("buttons ready")

    serial_bridge = SerialBridge(usb_cdc.data, uart)
    jetson_transport = JetsonTransport(uart, max_request_retries=0)
    record_step("transport ready")

    lcd_ui = initialize_lcd_ui()
    record_step("lcd ready")

    while True:
        now = time.monotonic()
        serial_bridge.relay_once(max_chunk_size=CDC_RELAY_SLICE_BYTES)
        _drain_button_events(buttons, lcd_ui, now)
        jetson_transport.poll(max_chunk_size=CDC_RELAY_SLICE_BYTES)
        _sync_response_state(protocol_handler, jetson_transport)
        _drain_hid_reports(custom_hid, protocol_handler, RAW_REPORT_ID)
        lcd_ui.tick(now=now)
        time.sleep(BUTTON_POLL_SLEEP_S)


run_with_diagnostics(
    _main,
    error_log_path=ERROR_LOG_PATH,
    trace_log_path=STARTUP_TRACE_PATH,
)
