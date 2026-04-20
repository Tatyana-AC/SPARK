try:
    from pico.button_layout import button_definition, debug_label
except ImportError:
    from button_layout import button_definition, debug_label


try:
    from pico.bridge_app import RuntimeStatus
except ImportError:
    from bridge_app import RuntimeStatus


class BridgeRuntime:
    STICKY_DEBUG_WINDOW_S = 10.0
    MAX_DEBUG_EVENTS = 16

    def __init__(
        self,
        *,
        serial_bridge,
        jetson_transport,
        protocol_handler,
        custom_hid,
        raw_report_id,
        button_input,
        button_press_handler=None,
        debug_sender=None,
        time_sleep,
        ui=None,
        relay_chunk_size=64,
        button_poll_sleep_s=0.002,
        heartbeat_interval_s=5.0,
        max_hid_reports_per_tick=4,
    ):
        self._serial_bridge = serial_bridge
        self._jetson_transport = jetson_transport
        self._protocol_handler = protocol_handler
        self._custom_hid = custom_hid
        self._raw_report_id = raw_report_id
        self._button_input = button_input
        self._button_press_handler = button_press_handler
        self._debug_sender = debug_sender or (lambda message: None)
        self._time_sleep = time_sleep
        self._ui = ui
        self._relay_chunk_size = relay_chunk_size
        self._button_poll_sleep_s = button_poll_sleep_s
        self._heartbeat_interval_s = heartbeat_interval_s
        self._max_hid_reports_per_tick = int(max_hid_reports_per_tick)
        self._last_response_signature = None
        self._last_debug_heartbeat = 0.0
        self._last_cdc_debug_status = "never"
        self._last_loop_checkpoint = "startup"
        self._last_runtime_now = 0.0
        self._sticky_debug_status = None
        self._sticky_debug_until = 0.0
        self._debug_events = []

        attach_debug_sender = getattr(self._ui, "set_debug_sender", None)
        if attach_debug_sender is not None:
            attach_debug_sender(self._emit_debug)

    def current_status(self):
        transport = self._jetson_transport
        if transport is None:
            request_active = False
            response_length = 0
            response_complete = False
        else:
            request_active = bool(transport.request_active)
            response_length = int(transport.response_len)
            response_complete = bool(transport.response_complete)

        debug_status = self._last_cdc_debug_status
        if self._sticky_debug_status is not None and self._last_runtime_now <= self._sticky_debug_until:
            debug_status = self._sticky_debug_status

        return RuntimeStatus(
            cdc_debug_status=debug_status,
            loop_checkpoint=self._last_loop_checkpoint,
            request_active=request_active,
            response_length=response_length,
            response_complete=response_complete,
        )

    def attach_protocol_status_provider(self):
        set_provider = getattr(self._protocol_handler, "set_runtime_status_provider", None)
        if set_provider is None:
            set_debug_provider = None
        else:
            set_provider(self.current_status)
            set_debug_provider = getattr(self._protocol_handler, "set_debug_event_provider", None)

        if set_debug_provider is not None:
            set_debug_provider(self.pop_debug_event)

    def pop_debug_event(self):
        if not self._debug_events:
            return None
        return self._debug_events.pop(0)

    def run_once(self, *, now):
        self._last_runtime_now = now
        self._jetson_transport.poll(max_chunk_size=self._relay_chunk_size)
        self._last_loop_checkpoint = "after_transport_poll"

        self._sync_response_state()
        self._last_loop_checkpoint = "after_response_sync"

        if (now - self._last_debug_heartbeat) >= self._heartbeat_interval_s:
            self._emit_debug("heartbeat")
            self._last_debug_heartbeat = now
            self._last_loop_checkpoint = "after_heartbeat"

        if not self._jetson_transport.request_active:
            self._serial_bridge.relay_once(max_chunk_size=self._relay_chunk_size)
        self._last_loop_checkpoint = "after_serial_bridge"

        self._drain_hid_reports()
        self._last_loop_checkpoint = "after_hid_drain"

        for button_event in self._button_input.drain_pressed_events():
            self._emit_debug(debug_label("button", button_event.index))
            if button_definition(button_event.index) is None:
                break
            if self._ui is not None:
                self._last_loop_checkpoint = f"before_ui_press:{button_event.index}"
                self._emit_debug(debug_label("pre_press", button_event.index))
                self._ui.handle_press(button_event.index, now=now)
                self._emit_debug(debug_label("post_press", button_event.index))
                self._last_loop_checkpoint = f"after_ui_press:{button_event.index}"
            if button_event.index == 0 and self._button_press_handler is not None:
                self._button_press_handler(button_event.index)
            break
        self._last_loop_checkpoint = "after_button_events"

        if self._ui is not None:
            self._last_loop_checkpoint = "before_ui_tick"
            self._ui.tick(now=now)
        self._last_loop_checkpoint = "after_ui_tick"

        self._time_sleep(self._button_poll_sleep_s)
        self._last_loop_checkpoint = "after_sleep"

    def run_forever(self, *, time_module):
        while True:
            self.run_once(now=time_module.monotonic())

    def _emit_debug(self, message):
        result = self._debug_sender(message)
        if result is None:
            result = "unknown"
        if result == "import:fail":
            self._last_cdc_debug_status = result
            return
        status_text = f"{message}|{result}"
        self._last_cdc_debug_status = status_text
        self._debug_events.append(message)
        if len(self._debug_events) > self.MAX_DEBUG_EVENTS:
            self._debug_events = self._debug_events[-self.MAX_DEBUG_EVENTS :]
        if message != "heartbeat":
            self._sticky_debug_status = status_text
            self._sticky_debug_until = self._last_runtime_now + self.STICKY_DEBUG_WINDOW_S

    def _sync_response_state(self):
        transport = self._jetson_transport
        signature = (
            transport.response_len,
            transport.response_complete,
            transport.request_active,
        )
        if signature == self._last_response_signature:
            return

        self._protocol_handler.update_response_state(
            transport.response_bytes,
            complete=transport.response_complete,
            active=transport.request_active,
        )
        self._last_response_signature = signature

    def _drain_hid_reports(self):
        for _ in range(self._max_hid_reports_per_tick):
            report = self._custom_hid.get_last_received_report(self._raw_report_id)
            if report is None:
                return
            reply = self._protocol_handler.handle_report(report)
            if reply is not None:
                self._custom_hid.send_report(reply, self._raw_report_id)
