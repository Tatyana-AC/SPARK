import types
import unittest
from unittest import mock


class BridgeAppTests(unittest.TestCase):
    def test_feature_1_forwards_to_jetson_request_when_idle(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand

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

        result = app.prepare_upload_result(AppCommand.FEATURE_1, "summarize this")

        transport.start_request.assert_called_once_with(b"summarize this")
        self.assertEqual(
            result,
            {
                "accepted_text": "summarize this",
                "accepted_count": len("summarize this"),
                "skipped_count": 0,
                "detail": "forwarded",
                "response_text": "",
                "response_active": True,
                "response_complete": False,
                "app_command": int(AppCommand.FEATURE_1),
            },
        )

    def test_feature_1_returns_busy_when_request_active(self):
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

        result = app.prepare_upload_result(AppCommand.FEATURE_1, "summarize this")

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

    def test_feature_2_preserves_pre_extraction_echo_behavior(self):
        from pico.bridge_app import BridgeApp, RuntimeStatus
        from pico.upload_protocol import AppCommand

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

        result = app.prepare_upload_result(AppCommand.FEATURE_2, "future")

        transport.start_request.assert_not_called()
        self.assertEqual(
            result,
            {
                "accepted_text": "future",
                "accepted_count": len("future"),
                "skipped_count": 0,
                "detail": "accepted",
                "response_text": "PICO ECHO: future\nCDC DEBUG: heartbeat|sent:27\nLOOP CHECKPOINT: after_response_sync",
                "app_command": int(AppCommand.FEATURE_2),
            },
        )


if __name__ == "__main__":
    unittest.main()
