import types
import unittest


class BridgeRuntimeTests(unittest.TestCase):
    def test_bridge_runtime_forwards_pressed_button_to_lcd_ui(self):
        from pico.bridge_runtime import BridgeRuntime

        renderer_calls = []
        serial_bridge = types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None)
        jetson_transport = types.SimpleNamespace(
            poll=lambda *, max_chunk_size: None,
            request_active=False,
            response_len=0,
            response_complete=False,
            response_bytes=b"",
        )
        protocol_handler = types.SimpleNamespace(
            update_response_state=lambda response_bytes, *, complete, active: None,
            handle_report=lambda report: None,
        )
        custom_hid = types.SimpleNamespace(
            get_last_received_report=lambda raw_report_id: None,
            send_report=lambda reply, raw_report_id: None,
        )
        button_input = types.SimpleNamespace(
            drain_pressed_events=lambda: iter([types.SimpleNamespace(index=1), types.SimpleNamespace(index=3)])
        )

        class _FakeBridgeUi:
            def handle_press(self, index, *, now):
                renderer_calls.append(("pressed", index, now))

            def tick(self, *, now):
                renderer_calls.append(("tick", now))

        runtime = BridgeRuntime(
            serial_bridge=serial_bridge,
            jetson_transport=jetson_transport,
            protocol_handler=protocol_handler,
            custom_hid=custom_hid,
            raw_report_id=9,
            button_input=button_input,
            ui=_FakeBridgeUi(),
            time_sleep=lambda _: None,
            debug_sender=lambda message: "sent:9",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.5)

        self.assertEqual(
            renderer_calls,
            [
                ("pressed", 1, 1.5),
                ("tick", 1.5),
            ],
        )

    def test_bridge_runtime_button_zero_updates_ui_then_invokes_handler(self):
        from pico.bridge_runtime import BridgeRuntime

        call_log = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(
                drain_pressed_events=lambda: iter([types.SimpleNamespace(index=0)])
            ),
            ui=types.SimpleNamespace(
                handle_press=lambda index, *, now: call_log.append(("ui", index, now)),
                tick=lambda *, now: call_log.append(("tick", now)),
            ),
            button_press_handler=lambda index: call_log.append(("handler", index)) or {"detail": "forwarded"},
            time_sleep=lambda delay: call_log.append(("sleep", delay)),
            debug_sender=lambda message: call_log.append(("debug", message)) or "sent:9",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.5)

        self.assertEqual(
            call_log,
            [
                ("debug", "button:1"),
                ("debug", "pre_press:1"),
                ("ui", 0, 1.5),
                ("debug", "post_press:1"),
                ("handler", 0),
                ("tick", 1.5),
                ("sleep", 0.002),
            ],
        )

    def test_bridge_runtime_non_zero_button_does_not_invoke_handler(self):
        from pico.bridge_runtime import BridgeRuntime

        call_log = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(
                drain_pressed_events=lambda: iter([types.SimpleNamespace(index=3)])
            ),
            ui=types.SimpleNamespace(
                handle_press=lambda index, *, now: call_log.append(("ui", index, now)),
                tick=lambda *, now: call_log.append(("tick", now)),
            ),
            button_press_handler=lambda index: call_log.append(("handler", index)),
            time_sleep=lambda delay: call_log.append(("sleep", delay)),
            debug_sender=lambda message: call_log.append(("debug", message)) or "sent:9",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.5)

        self.assertEqual(
            call_log,
            [
                ("debug", "button:4"),
                ("debug", "pre_press:4"),
                ("ui", 3, 1.5),
                ("debug", "post_press:4"),
                ("tick", 1.5),
                ("sleep", 0.002),
            ],
        )

    def test_bridge_runtime_continues_after_button_handler_failure_result(self):
        from pico.bridge_runtime import BridgeRuntime

        call_log = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(
                drain_pressed_events=lambda: iter([types.SimpleNamespace(index=0)])
            ),
            ui=types.SimpleNamespace(
                handle_press=lambda index, *, now: call_log.append(("ui", index, now)),
                tick=lambda *, now: call_log.append(("tick", now)),
            ),
            button_press_handler=lambda index: call_log.append(("handler", index)) or {
                "status_code": 5,
                "detail": "busy",
                "accepted_count": 0,
                "skipped_count": 0,
            },
            time_sleep=lambda delay: call_log.append(("sleep", delay)),
            debug_sender=lambda message: call_log.append(("debug", message)) or "sent:9",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.5)

        self.assertEqual(
            call_log,
            [
                ("debug", "button:1"),
                ("debug", "pre_press:1"),
                ("ui", 0, 1.5),
                ("debug", "post_press:1"),
                ("handler", 0),
                ("tick", 1.5),
                ("sleep", 0.002),
            ],
        )
        self.assertEqual(runtime.current_status().loop_checkpoint, "after_sleep")

    def test_bridge_runtime_processes_at_most_one_button_event_per_run_with_handler(self):
        from pico.bridge_runtime import BridgeRuntime

        call_log = []
        pending_events = iter([types.SimpleNamespace(index=0), types.SimpleNamespace(index=0)])

        class _StatefulButtonInput:
            def drain_pressed_events(self):
                while True:
                    try:
                        yield next(pending_events)
                    except StopIteration:
                        return

        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=_StatefulButtonInput(),
            ui=types.SimpleNamespace(
                handle_press=lambda index, *, now: call_log.append(("ui", index, now)),
                tick=lambda *, now: call_log.append(("tick", now)),
            ),
            button_press_handler=lambda index: call_log.append(("handler", index)) or {"detail": "forwarded"},
            time_sleep=lambda delay: call_log.append(("sleep", delay)),
            debug_sender=lambda message: call_log.append(("debug", message)) or "sent:9",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.5)

        self.assertEqual(
            call_log,
            [
                ("debug", "button:1"),
                ("debug", "pre_press:1"),
                ("ui", 0, 1.5),
                ("debug", "post_press:1"),
                ("handler", 0),
                ("tick", 1.5),
                ("sleep", 0.002),
            ],
        )

        call_log.clear()
        runtime.run_once(now=1.6)

        self.assertEqual(
            call_log,
            [
                ("debug", "button:1"),
                ("debug", "pre_press:1"),
                ("ui", 0, 1.6),
                ("debug", "post_press:1"),
                ("handler", 0),
                ("tick", 1.6),
                ("sleep", 0.002),
            ],
        )

    def test_bridge_runtime_run_once_orders_services_correctly(self):
        from pico.bridge_runtime import BridgeRuntime

        call_log = []
        sleeps = []
        serial_bridge = types.SimpleNamespace(
            relay_once=lambda *, max_chunk_size: call_log.append(("serial", max_chunk_size))
        )
        jetson_transport = types.SimpleNamespace(
            poll=lambda *, max_chunk_size: call_log.append(("transport", max_chunk_size)),
            request_active=False,
            response_len=0,
            response_complete=False,
            response_bytes=b"",
        )
        protocol_handler = types.SimpleNamespace(
            update_response_state=lambda response_bytes, *, complete, active: call_log.append(
                ("sync", response_bytes, complete, active)
            ),
            handle_report=lambda report: call_log.append(("handle_report", report)) or None,
        )
        custom_hid = types.SimpleNamespace(
            get_last_received_report=lambda raw_report_id: call_log.append(("hid", raw_report_id)) or None,
            send_report=lambda reply, raw_report_id: call_log.append(("send_report", reply, raw_report_id)),
        )
        runtime = BridgeRuntime(
            serial_bridge=serial_bridge,
            jetson_transport=jetson_transport,
            protocol_handler=protocol_handler,
            custom_hid=custom_hid,
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter(())),
            time_sleep=sleeps.append,
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.0)

        self.assertEqual(
            call_log,
            [
                ("transport", 64),
                ("sync", b"", False, False),
                ("serial", 64),
                ("hid", 9),
            ],
        )
        self.assertEqual(sleeps, [0.002])
        self.assertEqual(runtime.current_status().loop_checkpoint, "after_sleep")

    def test_bridge_runtime_applies_auxiliary_slider_and_encoder_to_upper_lcd(self):
        from pico.bridge_runtime import BridgeRuntime

        ui_calls = []
        debug_calls = []
        aux_events = iter(
            [
                types.SimpleNamespace(slider_state=((1, True), (2, False), (3, True)), slider_position=2, scroll_delta=0),
                types.SimpleNamespace(slider_state=None, slider_position=None, scroll_delta=1),
            ]
        )

        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter(())),
            auxiliary_input=types.SimpleNamespace(poll_changes=lambda: next(aux_events)),
            ui=types.SimpleNamespace(
                set_upper_mode=lambda position: ui_calls.append(("mode", position)),
                scroll_upper_content=lambda delta: ui_calls.append(("scroll", delta)),
                tick=lambda *, now: ui_calls.append(("tick", now)),
            ),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_calls.append(message) or "sent:9",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.0)
        runtime.run_once(now=1.1)

        self.assertEqual(
            ui_calls,
            [
                ("mode", 2),
                ("tick", 1.0),
                ("scroll", 1),
                ("tick", 1.1),
            ],
        )
        self.assertEqual(debug_calls, ["slider_raw:1=H,2=L,3=H", "slider:2", "scroll:1"])

    def test_bridge_runtime_skips_serial_bridge_while_request_active(self):
        from pico.bridge_runtime import BridgeRuntime

        call_log = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(
                relay_once=lambda *, max_chunk_size: call_log.append(("serial", max_chunk_size))
            ),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: call_log.append(("transport", max_chunk_size)),
                request_active=True,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: call_log.append(
                    ("sync", active)
                ),
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: call_log.append(("hid", raw_report_id)) or None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter(())),
            time_sleep=lambda _: None,
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.0)

        self.assertEqual(
            call_log,
            [
                ("transport", 64),
                ("sync", True),
                ("hid", 9),
            ],
        )

    def test_bridge_runtime_limits_hid_reports_per_run(self):
        from pico.bridge_runtime import BridgeRuntime

        reports = [b"r1", b"r2", b"r3", b"r4", b"r5"]
        handled = []

        class _FakeCustomHid:
            def get_last_received_report(self, raw_report_id):
                if not reports:
                    return None
                return reports.pop(0)

            def send_report(self, reply, raw_report_id):
                return None

        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: handled.append(report) or None,
            ),
            custom_hid=_FakeCustomHid(),
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter(())),
            time_sleep=lambda _: None,
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.0)

        self.assertEqual(handled, [b"r1", b"r2", b"r3", b"r4"])
        self.assertEqual(reports, [b"r5"])

    def test_bridge_runtime_updates_loop_checkpoint_and_heartbeat(self):
        from pico.bridge_runtime import BridgeRuntime

        debug_messages = []
        serial_bridge = types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None)
        jetson_transport = types.SimpleNamespace(
            poll=lambda *, max_chunk_size: None,
            request_active=True,
            response_len=12,
            response_complete=False,
            response_bytes=b"payload-bytes",
        )
        protocol_handler = types.SimpleNamespace(
            update_response_state=lambda response_bytes, *, complete, active: None,
            handle_report=lambda report: None,
        )
        custom_hid = types.SimpleNamespace(
            get_last_received_report=lambda raw_report_id: None,
            send_report=lambda reply, raw_report_id: None,
        )
        runtime = BridgeRuntime(
            serial_bridge=serial_bridge,
            jetson_transport=jetson_transport,
            protocol_handler=protocol_handler,
            custom_hid=custom_hid,
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter(())),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_messages.append(message) or "sent:27",
        )

        runtime.run_once(now=5.0)

        status = runtime.current_status()
        self.assertEqual(debug_messages, ["heartbeat"])
        self.assertEqual(status.cdc_debug_status, "heartbeat|sent:27")
        self.assertEqual(status.loop_checkpoint, "after_sleep")
        self.assertTrue(status.request_active)
        self.assertEqual(status.response_length, 12)
        self.assertFalse(status.response_complete)

    def test_bridge_runtime_heartbeats_only_after_full_interval(self):
        from pico.bridge_runtime import BridgeRuntime

        debug_messages = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter(())),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_messages.append(message) or "sent:27",
            heartbeat_interval_s=5.0,
        )

        runtime.run_once(now=4.999)
        runtime.run_once(now=5.0)
        runtime.run_once(now=9.999)
        runtime.run_once(now=10.0)

        self.assertEqual(debug_messages, ["heartbeat", "heartbeat"])

    def test_bridge_runtime_preserves_import_fail_debug_status_without_prefix(self):
        from pico.bridge_runtime import BridgeRuntime

        debug_messages = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(
                drain_pressed_events=lambda: iter([types.SimpleNamespace(index=2)])
            ),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_messages.append(message) or "import:fail",
        )

        runtime.run_once(now=5.0)

        self.assertEqual(debug_messages, ["heartbeat", "button:3"])
        self.assertEqual(runtime.current_status().cdc_debug_status, "import:fail")

    def test_bridge_runtime_skips_invalid_indices_before_ui_calls(self):
        from pico.bridge_runtime import BridgeRuntime

        ui_calls = []
        handler_calls = []
        debug_messages = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(
                drain_pressed_events=lambda: iter([types.SimpleNamespace(index=99)])
            ),
            ui=types.SimpleNamespace(
                handle_press=lambda index, *, now: ui_calls.append((index, now)),
                tick=lambda *, now: None,
            ),
            button_press_handler=lambda index: handler_calls.append(index),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_messages.append(message) or "sent:31",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=2.0)

        self.assertEqual(ui_calls, [])
        self.assertEqual(handler_calls, [])
        self.assertEqual(debug_messages, ["button:?"])

    def test_bridge_runtime_processes_at_most_one_button_event_per_run(self):
        from pico.bridge_runtime import BridgeRuntime

        call_log = []
        serial_bridge = types.SimpleNamespace(
            relay_once=lambda *, max_chunk_size: call_log.append(("serial", max_chunk_size))
        )
        jetson_transport = types.SimpleNamespace(
            poll=lambda *, max_chunk_size: call_log.append(("transport", max_chunk_size)),
            request_active=False,
            response_len=0,
            response_complete=False,
            response_bytes=b"",
        )
        protocol_handler = types.SimpleNamespace(
            update_response_state=lambda response_bytes, *, complete, active: call_log.append(("sync", None)),
            handle_report=lambda report: None,
        )
        custom_hid = types.SimpleNamespace(
            get_last_received_report=lambda raw_report_id: call_log.append(("hid", raw_report_id)) or None,
            send_report=lambda reply, raw_report_id: None,
        )
        pending_events = iter([types.SimpleNamespace(index=1), types.SimpleNamespace(index=3)])

        class _StatefulButtonInput:
            def drain_pressed_events(self):
                while True:
                    try:
                        yield next(pending_events)
                    except StopIteration:
                        return

        button_input = _StatefulButtonInput()
        ui = types.SimpleNamespace(
            handle_press=lambda index, *, now: call_log.append(("ui", index, now)),
            tick=lambda *, now: call_log.append(("tick", now)),
        )
        runtime = BridgeRuntime(
            serial_bridge=serial_bridge,
            jetson_transport=jetson_transport,
            protocol_handler=protocol_handler,
            custom_hid=custom_hid,
            raw_report_id=9,
            button_input=button_input,
            ui=ui,
            time_sleep=lambda _: None,
            debug_sender=lambda message: call_log.append(("debug", message)) or "sent:9",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=1.5)

        self.assertEqual(
            call_log,
            [
                ("transport", 64),
                ("sync", None),
                ("serial", 64),
                ("hid", 9),
                ("debug", "button:2"),
                ("debug", "pre_press:2"),
                ("ui", 1, 1.5),
                ("debug", "post_press:2"),
                ("tick", 1.5),
            ],
        )
        self.assertEqual(runtime.current_status().loop_checkpoint, "after_sleep")

        call_log.clear()
        runtime.run_once(now=1.6)

        self.assertEqual(
            call_log,
            [
                ("transport", 64),
                ("serial", 64),
                ("hid", 9),
                ("debug", "button:4"),
                ("debug", "pre_press:4"),
                ("ui", 3, 1.6),
                ("debug", "post_press:4"),
                ("tick", 1.6),
            ],
        )

    def test_bridge_runtime_ticks_lcd_ui_each_loop(self):
        from pico.bridge_runtime import BridgeRuntime

        ui_calls = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter(())),
            ui=types.SimpleNamespace(
                handle_press=lambda index, *, now: ui_calls.append(("press", index, now)),
                tick=lambda *, now: ui_calls.append(("tick", now)),
            ),
            time_sleep=lambda _: None,
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=2.25)

        self.assertEqual(ui_calls, [("tick", 2.25)])

    def test_bridge_runtime_records_post_press_debug_stage_for_nonzero_button(self):
        from pico.bridge_runtime import BridgeRuntime

        debug_messages = []
        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter([types.SimpleNamespace(index=1)])),
            ui=types.SimpleNamespace(handle_press=lambda index, *, now: None, tick=lambda *, now: None),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_messages.append(message) or "sent:31",
            heartbeat_interval_s=99.0,
        )

        runtime.run_once(now=2.0)

        self.assertEqual(debug_messages[-1], "post_press:2")
        self.assertEqual(runtime.current_status().cdc_debug_status, "post_press:2|sent:31")

    def test_bridge_runtime_keeps_last_nonheartbeat_debug_status_through_heartbeat(self):
        from pico.bridge_runtime import BridgeRuntime

        debug_messages = []
        pending_events = iter([types.SimpleNamespace(index=1)])

        class _StatefulButtonInput:
            def drain_pressed_events(self):
                while True:
                    try:
                        yield next(pending_events)
                    except StopIteration:
                        return

        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=_StatefulButtonInput(),
            ui=types.SimpleNamespace(handle_press=lambda index, *, now: None, tick=lambda *, now: None),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_messages.append(message) or "sent:31",
            heartbeat_interval_s=5.0,
        )

        runtime.run_once(now=5.0)
        runtime.run_once(now=10.0)

        self.assertEqual(debug_messages, ["heartbeat", "button:2", "pre_press:2", "post_press:2", "heartbeat"])
        self.assertEqual(runtime.current_status().cdc_debug_status, "post_press:2|sent:31")

    def test_bridge_runtime_expires_sticky_debug_status_after_window(self):
        from pico.bridge_runtime import BridgeRuntime

        debug_messages = []
        pending_events = iter([types.SimpleNamespace(index=1)])

        class _StatefulButtonInput:
            def drain_pressed_events(self):
                while True:
                    try:
                        yield next(pending_events)
                    except StopIteration:
                        return

        runtime = BridgeRuntime(
            serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
            jetson_transport=types.SimpleNamespace(
                poll=lambda *, max_chunk_size: None,
                request_active=False,
                response_len=0,
                response_complete=False,
                response_bytes=b"",
            ),
            protocol_handler=types.SimpleNamespace(
                update_response_state=lambda response_bytes, *, complete, active: None,
                handle_report=lambda report: None,
            ),
            custom_hid=types.SimpleNamespace(
                get_last_received_report=lambda raw_report_id: None,
                send_report=lambda reply, raw_report_id: None,
            ),
            raw_report_id=9,
            button_input=_StatefulButtonInput(),
            ui=types.SimpleNamespace(handle_press=lambda index, *, now: None, tick=lambda *, now: None),
            time_sleep=lambda _: None,
            debug_sender=lambda message: debug_messages.append(message) or "sent:31",
            heartbeat_interval_s=5.0,
        )

        runtime.run_once(now=5.0)
        runtime.run_once(now=16.0)

        self.assertEqual(runtime.current_status().cdc_debug_status, "heartbeat|sent:31")


if __name__ == "__main__":
    unittest.main()
