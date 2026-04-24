import types
import unittest
from unittest import mock


class BridgeAppTests(unittest.TestCase):
    def _make_runtime_status(self, *, request_active=False):
        from pico.bridge_app import RuntimeStatus

        return lambda: RuntimeStatus(
            cdc_debug_status="heartbeat|sent:27",
            loop_checkpoint="after_response_sync",
            request_active=request_active,
            response_length=0,
            response_complete=False,
        )

    def test_feature_1_forwards_lightweight_summarize_command_unchanged(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand
        from host_pc.summarize_stream import build_summarize_command

        payload = build_summarize_command()
        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_response_sync",
                request_active=False,
                response_length=0,
                response_complete=False,
            ),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_1, payload)

        transport.start_request.assert_called_once_with(payload.encode("utf-8"))
        self.assertEqual(
            result,
            {
                "accepted_text": payload,
                "accepted_count": len(payload),
                "skipped_count": 0,
                "detail": "forwarded",
                "response_text": "",
                "response_active": True,
                "response_complete": False,
                "app_command": int(AppCommand.FEATURE_1),
            },
        )

    def test_feature_1_forwards_inline_context_payload_unchanged(self):
        from pico.bridge_app import BridgeApp
        from pico.upload_protocol import AppCommand
        from host_pc.summarize_stream import build_summary_request

        payload = build_summary_request(
            app_name="Chrome",
            window_title="ChatGPT - OpenAI",
            window_text="Visible context to summarize.",
        )
        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=self._make_runtime_status(),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_1, payload)

        transport.start_request.assert_called_once_with(payload.encode("utf-8"))
        self.assertEqual(result["accepted_text"], payload)
        self.assertEqual(result["accepted_count"], len(payload))
        self.assertEqual(result["detail"], "forwarded")

    def test_button_0_uses_session_synthesis_payload(self):
        from pico.bridge_app import BridgeApp
        from pico.upload_protocol import AppCommand
        from host_pc.summarize_stream import build_synthesize_session_request

        payload = build_synthesize_session_request()
        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=self._make_runtime_status(),
        )

        result = app.handle_button_press(0)

        transport.start_request.assert_called_once_with(payload.encode("utf-8"))
        self.assertEqual(result["accepted_text"], payload)
        self.assertEqual(result["app_command"], int(AppCommand.FEATURE_1))

    def test_button_0_skips_when_transport_is_busy(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand, StatusCode

        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_response_sync",
                request_active=True,
                response_length=14,
                response_complete=False,
            ),
        )

        result = app.handle_button_press(0)

        transport.start_request.assert_not_called()
        self.assertEqual(
            result,
            {
                "status_code": StatusCode.BUSY,
                "detail": "busy",
                "accepted_count": 0,
                "skipped_count": 0,
            },
        )

    def test_feature_1_returns_uart_unavailable_when_transport_missing(self):
        from pico.bridge_app import BridgeApp
        from pico.upload_protocol import AppCommand, StatusCode

        app = BridgeApp(
            jetson_transport=None,
            runtime_status=self._make_runtime_status(),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_1, "text")

        self.assertEqual(
            result,
            {
                "status_code": StatusCode.INTERNAL_ERROR,
                "detail": "uart unavailable",
                "accepted_count": 0,
                "skipped_count": 0,
            },
        )

    def test_feature_1_returns_encode_failure_shape(self):
        from pico.bridge_app import BridgeApp
        from pico.upload_protocol import AppCommand, StatusCode

        class BadText:
            def encode(self, encoding):
                raise ValueError("boom")

        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=self._make_runtime_status(),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_1, BadText())

        transport.start_request.assert_not_called()
        self.assertEqual(
            result,
            {
                "status_code": StatusCode.INTERNAL_ERROR,
                "detail": "encode:ValueError",
                "accepted_count": 0,
                "skipped_count": 0,
            },
        )

    def test_feature_1_returns_start_failure_shape(self):
        from pico.bridge_app import BridgeApp
        from pico.upload_protocol import AppCommand, StatusCode

        transport = types.SimpleNamespace(start_request=mock.Mock(side_effect=ValueError("boom")))
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=self._make_runtime_status(),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_1, "text")

        self.assertEqual(
            result,
            {
                "status_code": StatusCode.INTERNAL_ERROR,
                "detail": "start:ValueError",
                "accepted_count": 0,
                "skipped_count": 0,
            },
        )

    def test_feature_1_returns_outer_failure_shape(self):
        from pico.bridge_app import BridgeApp
        from pico.upload_protocol import AppCommand, StatusCode

        class BadStatus:
            @property
            def request_active(self):
                raise ValueError("boom")

        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: BadStatus(),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_1, "text")

        transport.start_request.assert_not_called()
        self.assertEqual(
            result,
            {
                "status_code": StatusCode.INTERNAL_ERROR,
                "detail": "outer:ValueError",
                "accepted_count": 0,
                "skipped_count": 0,
            },
        )

    def test_button_start_failure_is_contained_to_result(self):
        from pico.bridge_app import BridgeApp
        from pico.upload_protocol import StatusCode

        transport = types.SimpleNamespace(start_request=mock.Mock(side_effect=ValueError("boom")))
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=self._make_runtime_status(),
        )

        result = app.handle_button_press(0)

        self.assertEqual(
            result,
            {
                "status_code": StatusCode.INTERNAL_ERROR,
                "detail": "start:ValueError",
                "accepted_count": 0,
                "skipped_count": 0,
            },
        )

    def test_feature_1_returns_busy_while_button_started_request_is_active(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand, StatusCode

        transport = types.SimpleNamespace(request_active=False)

        def start_request(_payload):
            transport.request_active = True

        transport.start_request = mock.Mock(side_effect=start_request)
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_response_sync",
                request_active=transport.request_active,
                response_length=0,
                response_complete=False,
            ),
        )

        button_result = app.handle_button_press(0)
        host_result = app.prepare_upload_result(AppCommand.FEATURE_1, "text")

        self.assertEqual(button_result["detail"], "forwarded")
        self.assertEqual(
            host_result,
            {
                "status_code": StatusCode.BUSY,
                "detail": "busy",
                "accepted_count": 0,
                "skipped_count": 0,
            },
        )
        self.assertEqual(transport.start_request.call_count, 1)

    def test_echo_response_formats_runtime_status_text(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand

        app = BridgeApp(
            jetson_transport=types.SimpleNamespace(start_request=mock.Mock()),
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_button_events",
                request_active=False,
                response_length=0,
                response_complete=True,
            ),
        )

        result = app.prepare_upload_result(AppCommand.SUBMIT_TEXT, "probe")

        self.assertEqual(
            result,
            {
                "accepted_text": "probe",
                "accepted_count": len("probe"),
                "skipped_count": 0,
                "detail": "accepted",
                "response_text": "PICO ECHO: probe\nCDC DEBUG: heartbeat|sent:27\nLOOP CHECKPOINT: after_button_events",
                "app_command": int(AppCommand.SUBMIT_TEXT),
            },
        )

    def test_feature_2_forwards_reformat_payload_unchanged(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand
        from host_pc.summarize_stream import build_reformat_request

        payload = build_reformat_request(selected_text="Reformat this")
        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_response_sync",
                request_active=False,
                response_length=0,
                response_complete=False,
            ),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_2, payload)

        transport.start_request.assert_called_once_with(payload.encode("utf-8"))
        self.assertEqual(
            result,
            {
                "accepted_text": payload,
                "accepted_count": len(payload),
                "skipped_count": 0,
                "detail": "forwarded",
                "response_text": "",
                "response_active": True,
                "response_complete": False,
                "app_command": int(AppCommand.FEATURE_2),
            },
        )

    def test_feature_2_forwards_when_command_byte_order_is_swapped(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand
        from host_pc.summarize_stream import build_reformat_request

        payload = build_reformat_request(selected_text="Reformat this")
        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_response_sync",
                request_active=False,
                response_length=0,
                response_complete=False,
            ),
        )

        swapped_feature_2 = ((int(AppCommand.FEATURE_2) & 0x00FF) << 8) | (
            (int(AppCommand.FEATURE_2) & 0xFF00) >> 8
        )
        result = app.prepare_upload_result(swapped_feature_2, payload)

        transport.start_request.assert_called_once_with(payload.encode("utf-8"))
        self.assertEqual(
            result,
            {
                "accepted_text": payload,
                "accepted_count": len(payload),
                "skipped_count": 0,
                "detail": "forwarded",
                "response_text": "",
                "response_active": True,
                "response_complete": False,
                "app_command": int(AppCommand.FEATURE_2),
            },
        )

    def test_feature_4_forwards_respond_payload_unchanged(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand
        from host_pc.summarize_stream import build_respond_request

        payload = build_respond_request("Continue the draft from here")
        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_response_sync",
                request_active=False,
                response_length=0,
                response_complete=False,
            ),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_4, payload)

        transport.start_request.assert_called_once_with(payload.encode("utf-8"))
        self.assertEqual(
            result,
            {
                "accepted_text": payload,
                "accepted_count": len(payload),
                "skipped_count": 0,
                "detail": "forwarded",
                "response_text": "",
                "response_active": True,
                "response_complete": False,
                "app_command": int(AppCommand.FEATURE_4),
            },
        )

    def test_feature_3_forwards_keyword_search_payload_unchanged(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand
        from host_pc.summarize_stream import build_keyword_search_request

        payload = build_keyword_search_request("irrational")
        transport = types.SimpleNamespace(start_request=mock.Mock())
        app = BridgeApp(
            jetson_transport=transport,
            runtime_status=lambda: RuntimeStatus(
                cdc_debug_status="heartbeat|sent:27",
                loop_checkpoint="after_response_sync",
                request_active=False,
                response_length=0,
                response_complete=False,
            ),
        )

        result = app.prepare_upload_result(AppCommand.FEATURE_3, payload)

        transport.start_request.assert_called_once_with(payload.encode("utf-8"))
        self.assertEqual(
            result,
            {
                "accepted_text": payload,
                "accepted_count": len(payload),
                "skipped_count": 0,
                "detail": "forwarded",
                "response_text": "",
                "response_active": True,
                "response_complete": False,
                "app_command": int(AppCommand.FEATURE_3),
            },
        )


if __name__ == "__main__":
    unittest.main()
