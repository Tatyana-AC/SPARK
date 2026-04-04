from runtime_runner import run_with_diagnostics


UART_BAUDRATE = 115200
BUTTON_POLL_SLEEP_S = 0.002
CDC_RELAY_SLICE_BYTES = 64
ERROR_LOG_PATH = "runtime_error.txt"
STARTUP_TRACE_PATH = "startup_trace.txt"
UART_DIAG_LOG_PATH = "uart_diag.txt"
LCD_DEBUG_CHECKPOINT = "after_press_time"
LCD_SKIP_PALETTE_WRITE = True
# Dynamic highlight group mutation crashes the integrated runtime on real hardware.
LCD_SKIP_HIGHLIGHT_UPDATE = False
LCD_SKIP_HIGHLIGHT_CLEAR = True
CDC_DEBUG_HEARTBEAT_S = 2.0
BUTTON_EVENT_DEBUG_ENABLED = False

jetson_transport = None
_last_response_signature = None
_last_cdc_debug_status = "never"
_last_loop_checkpoint = "startup"


def _prepare_upload_result(app_command, text, *, AppCommand, StatusCode):
    global jetson_transport
    global _last_cdc_debug_status
    global _last_loop_checkpoint

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
        "response_text": (
            f"PICO ECHO: {text}\n"
            f"CDC DEBUG: {_last_cdc_debug_status}\n"
            f"LOOP CHECKPOINT: {_last_loop_checkpoint}"
        ),
        "app_command": int(app_command),
    }


def _find_custom_hid_device(usb_hid, raw_usage_page, raw_usage_id):
    for device in usb_hid.devices:
        if device.usage_page == raw_usage_page and device.usage == raw_usage_id:
            return device
    raise RuntimeError("SPARK custom HID device not enabled")


def _record_uart_diag(event):
    try:
        with open(UART_DIAG_LOG_PATH, "a") as handle:
            handle.write(f"{event}\n")
    except OSError:
        return


def _send_button_debug(message):
    global _last_cdc_debug_status

    try:
        from pico.pico_debug import dbg
    except ImportError:
        try:
            from pico_debug import dbg
        except ImportError:
            _last_cdc_debug_status = "import:fail"
            return

    result = dbg(message)
    if result is None:
        result = "unknown"
    _last_cdc_debug_status = f"{message}|{result}"


def _drain_button_events(buttons, lcd_ui, now):
    while True:
        event = buttons.events.get()
        if event is None:
            return
        if not event.pressed:
            continue
        index = event.key_number
        if BUTTON_EVENT_DEBUG_ENABLED:
            _send_button_debug(f"PB{index + 1} pressed")
        lcd_ui.handle_press(index, now=now)
        if BUTTON_EVENT_DEBUG_ENABLED:
            _send_button_debug(f"PB{index + 1} done")


def _drain_hid_reports(custom_hid, protocol_handler, raw_report_id):
    while True:
        report = custom_hid.get_last_received_report(raw_report_id)
        if report is None:
            return
        reply = protocol_handler.handle_report(report)
        if reply is not None:
            custom_hid.send_report(reply, raw_report_id)


def _configure_runtime(supervisor, record_step):
    supervisor.runtime.autoreload = False
    record_step("autoreload disabled")


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


def _run_main_loop_iteration(
    *,
    now,
    last_debug_heartbeat,
    serial_bridge,
    buttons,
    lcd_ui,
    jetson_transport,
    protocol_handler,
    custom_hid,
    raw_report_id,
    time_sleep,
):
    global _last_loop_checkpoint

    if (now - last_debug_heartbeat) >= CDC_DEBUG_HEARTBEAT_S:
        _send_button_debug("heartbeat")
        last_debug_heartbeat = now
        _last_loop_checkpoint = "after_heartbeat"

    serial_bridge.relay_once(max_chunk_size=CDC_RELAY_SLICE_BYTES)
    _last_loop_checkpoint = "after_serial_bridge"
    _drain_button_events(buttons, lcd_ui, now)
    _last_loop_checkpoint = "after_button_events"
    jetson_transport.poll(max_chunk_size=CDC_RELAY_SLICE_BYTES)
    _last_loop_checkpoint = "after_transport_poll"
    _sync_response_state(protocol_handler, jetson_transport)
    _last_loop_checkpoint = "after_response_sync"
    _drain_hid_reports(custom_hid, protocol_handler, raw_report_id)
    _last_loop_checkpoint = "after_hid_drain"
    lcd_ui.tick(now=now)
    _last_loop_checkpoint = "after_lcd_tick"
    time_sleep(BUTTON_POLL_SLEEP_S)
    _last_loop_checkpoint = "after_sleep"
    return last_debug_heartbeat


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

    _configure_runtime(supervisor, record_step)

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

    uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0, receiver_buffer_size=256)
    record_step("uart ready")

    buttons = keypad.Keys(button_pins, value_when_pressed=False, pull=True)
    record_step("buttons ready")

    serial_bridge = SerialBridge(usb_cdc.data, uart)
    jetson_transport = JetsonTransport(
        uart,
        max_request_retries=0,
        debug_hook=lambda event: _record_uart_diag(repr(event)),
    )
    record_step("transport ready")

    lcd_ui = initialize_lcd_ui(
        debug_hook=_send_button_debug,
        debug_checkpoint=LCD_DEBUG_CHECKPOINT,
        skip_palette_write=LCD_SKIP_PALETTE_WRITE,
        skip_highlight_update=LCD_SKIP_HIGHLIGHT_UPDATE,
        skip_highlight_clear=LCD_SKIP_HIGHLIGHT_CLEAR,
    )
    record_step("lcd ready")
    last_debug_heartbeat = 0.0

    while True:
        now = time.monotonic()
        last_debug_heartbeat = _run_main_loop_iteration(
            now=now,
            last_debug_heartbeat=last_debug_heartbeat,
            serial_bridge=serial_bridge,
            buttons=buttons,
            lcd_ui=lcd_ui,
            jetson_transport=jetson_transport,
            protocol_handler=protocol_handler,
            custom_hid=custom_hid,
            raw_report_id=RAW_REPORT_ID,
            time_sleep=time.sleep,
        )


run_with_diagnostics(
    _main,
    error_log_path=ERROR_LOG_PATH,
    trace_log_path=STARTUP_TRACE_PATH,
)
