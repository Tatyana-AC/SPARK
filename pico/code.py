from runtime_runner import run_with_diagnostics


UART_BAUDRATE = 115200
BUTTON_POLL_SLEEP_S = 0.002
CDC_RELAY_SLICE_BYTES = 64
ERROR_LOG_PATH = "runtime_error.txt"
STARTUP_TRACE_PATH = "startup_trace.txt"
UART_DIAG_LOG_PATH = "uart_diag.txt"
CDC_DEBUG_HEARTBEAT_S = 2.0


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
        from pico.bridge_app import build_text_preparer
        from pico.bridge_runtime import BridgeRuntime
        from pico.button_input import build_button_input
        from pico.jetson_transport import JetsonTransport
        from pico.lcd_ui import initialize_lcd_ui
        from pico.serial_bridge import SerialBridge
        from pico.upload_protocol import UploadProtocolHandler
        from pico.usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE
    except ImportError:
        from bridge_app import build_text_preparer
        from bridge_runtime import BridgeRuntime
        from button_input import build_button_input
        from jetson_transport import JetsonTransport
        from lcd_ui import initialize_lcd_ui
        from serial_bridge import SerialBridge
        from upload_protocol import UploadProtocolHandler
        from usb_config import RAW_REPORT_ID, RAW_USAGE_ID, RAW_USAGE_PAGE

    record_step("spark modules ready")

    _configure_runtime(supervisor, record_step)

    custom_hid = _find_custom_hid_device(usb_hid, RAW_USAGE_PAGE, RAW_USAGE_ID)
    record_step("custom hid ready")

    uart = busio.UART(board.GP0, board.GP1, baudrate=UART_BAUDRATE, timeout=0, receiver_buffer_size=256)
    record_step("uart ready")

    serial_bridge = SerialBridge(usb_cdc.data, uart)
    jetson_transport = JetsonTransport(
        uart,
        max_request_retries=0,
        debug_hook=lambda event: _record_uart_diag(repr(event)),
    )
    record_step("transport ready")
    runtime = None
    protocol_handler = UploadProtocolHandler(
        text_preparer=build_text_preparer(
            jetson_transport=jetson_transport,
            runtime_status=lambda: runtime.current_status(),
        )
    )
    record_step("protocol handler ready")
    ui = initialize_lcd_ui(mode="bridge")
    record_step("lcd ui ready")
    button_input = build_button_input()
    record_step("button input ready")
    runtime = BridgeRuntime(
        serial_bridge=serial_bridge,
        jetson_transport=jetson_transport,
        protocol_handler=protocol_handler,
        custom_hid=custom_hid,
        raw_report_id=RAW_REPORT_ID,
        button_input=button_input,
        ui=ui,
        debug_sender=_send_button_debug,
        time_sleep=time.sleep,
        relay_chunk_size=CDC_RELAY_SLICE_BYTES,
        button_poll_sleep_s=BUTTON_POLL_SLEEP_S,
        heartbeat_interval_s=CDC_DEBUG_HEARTBEAT_S,
    )
    record_step("bridge runtime ready")
    runtime.run_forever(time_module=time)


run_with_diagnostics(
    _main,
    error_log_path=ERROR_LOG_PATH,
    trace_log_path=STARTUP_TRACE_PATH,
)
