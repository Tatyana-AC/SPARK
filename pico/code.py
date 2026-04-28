from runtime_runner import run_with_diagnostics


UART_BAUDRATE = 115200
BUTTON_POLL_SLEEP_S = 0.002
CDC_RELAY_SLICE_BYTES = 64
ERROR_LOG_PATH = "runtime_error.txt"
STARTUP_TRACE_PATH = "startup_trace.txt"
UART_DIAG_LOG_PATH = "uart_diag.txt"
CDC_DEBUG_HEARTBEAT_S = 5.0


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
    try:
        from pico.pico_debug import dbg
    except ImportError:
        try:
            from pico_debug import dbg
        except ImportError:
            return "import:fail"

    result = dbg(message)
    if result is None:
        result = "unknown"
    return result


def _make_transport_debug_hook(*, status_sender):
    def _hook(event):
        _record_uart_diag(repr(event))
        return None

    return _hook


def _make_lcd_text_preparer(*, base_preparer, ui_provider, app_command_class):
    release_command = int(app_command_class.LCD_RELEASE_OUTPUT)
    history_command = int(app_command_class.LCD_SESSION_HISTORY)

    def _prepare(app_command, text):
        command_code = int(app_command)
        ui = ui_provider()
        if command_code == release_command:
            ui.set_upper_content("release", text)
            return {
                "accepted_text": text,
                "accepted_count": len(text),
                "skipped_count": 0,
                "detail": "lcd release",
                "response_text": "",
            }
        if command_code == history_command:
            ui.set_upper_content("history", text)
            return {
                "accepted_text": text,
                "accepted_count": len(text),
                "skipped_count": 0,
                "detail": "lcd history",
                "response_text": "",
            }
        return base_preparer(app_command, text)

    return _prepare


def _configure_runtime(supervisor, record_step):
    supervisor.runtime.autoreload = False
    record_step("autoreload disabled")


def _main(record_step):
    import time
    import board
    import busio
    import supervisor
    import usb_cdc
    import usb_hid

    record_step("core imports ready")

    try:
        from pico.bridge_app import build_button_press_handler, build_text_preparer
        from pico.bridge_runtime import BridgeRuntime
        from pico.button_input import build_button_input
        try:
            from pico.button_input import build_auxiliary_input
        except ImportError:
            build_auxiliary_input = lambda: None
        from pico.jetson_transport import JetsonTransport
        from pico.lcd_ui import initialize_lcd_ui
        from pico.serial_bridge import SerialBridge
        from pico.upload_protocol import UploadProtocolHandler
        try:
            from pico.upload_protocol import AppCommand
        except ImportError:
            AppCommand = type("AppCommand", (), {"LCD_RELEASE_OUTPUT": 0x0201, "LCD_SESSION_HISTORY": 0x0202})
        from pico.usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE
    except ImportError:
        from bridge_app import build_button_press_handler, build_text_preparer
        from bridge_runtime import BridgeRuntime
        from button_input import build_button_input
        try:
            from button_input import build_auxiliary_input
        except ImportError:
            build_auxiliary_input = lambda: None
        from jetson_transport import JetsonTransport
        from lcd_ui import initialize_lcd_ui
        from serial_bridge import SerialBridge
        from upload_protocol import UploadProtocolHandler
        try:
            from upload_protocol import AppCommand
        except ImportError:
            AppCommand = type("AppCommand", (), {"LCD_RELEASE_OUTPUT": 0x0201, "LCD_SESSION_HISTORY": 0x0202})
        from usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE

    record_step("spark modules ready")

    _configure_runtime(supervisor, record_step)

    custom_hid = _find_custom_hid_device(usb_hid, RAW_USAGE_PAGE, RAW_USAGE_ID)
    record_step("custom hid ready")

    uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0, receiver_buffer_size=1024)
    record_step("uart ready")

    serial_bridge = SerialBridge(usb_cdc.data, uart)
    jetson_transport = JetsonTransport(
        uart,
        max_request_retries=1,
        debug_hook=_make_transport_debug_hook(status_sender=_send_button_debug),
        status_sender=_send_button_debug,
    )
    record_step("transport ready")
    runtime = None
    ui = None
    button_press_handler = build_button_press_handler(
        jetson_transport=jetson_transport,
        runtime_status=lambda: runtime.current_status(),
    )
    base_text_preparer = build_text_preparer(
        jetson_transport=jetson_transport,
        runtime_status=lambda: runtime.current_status(),
    )
    protocol_handler = UploadProtocolHandler(
        text_preparer=_make_lcd_text_preparer(
            base_preparer=base_text_preparer,
            ui_provider=lambda: ui,
            app_command_class=AppCommand,
        )
    )
    record_step("protocol handler ready")
    ui = initialize_lcd_ui(mode="bridge")
    record_step("lcd ui ready")
    button_input = build_button_input()
    record_step("button input ready")
    auxiliary_input = build_auxiliary_input()
    record_step("auxiliary input ready")
    runtime = BridgeRuntime(
        serial_bridge=serial_bridge,
        jetson_transport=jetson_transport,
        protocol_handler=protocol_handler,
        custom_hid=custom_hid,
        raw_report_id=RAW_REPORT_ID,
        button_input=button_input,
        auxiliary_input=auxiliary_input,
        button_press_handler=button_press_handler,
        ui=ui,
        debug_sender=_send_button_debug,
        time_sleep=time.sleep,
        relay_chunk_size=CDC_RELAY_SLICE_BYTES,
        button_poll_sleep_s=BUTTON_POLL_SLEEP_S,
        heartbeat_interval_s=CDC_DEBUG_HEARTBEAT_S,
    )
    attach_protocol_status_provider = getattr(runtime, "attach_protocol_status_provider", None)
    if attach_protocol_status_provider is not None:
        attach_protocol_status_provider()
    record_step("bridge runtime ready")
    runtime.run_forever(time_module=time)


run_with_diagnostics(
    _main,
    error_log_path=ERROR_LOG_PATH,
    trace_log_path=STARTUP_TRACE_PATH,
)
