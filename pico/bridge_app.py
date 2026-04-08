try:
    from pico.upload_protocol import AppCommand, StatusCode
except ImportError:
    from upload_protocol import AppCommand, StatusCode


SUMMARIZE_COMMAND_TEXT = '{"command": "summarize"}'


class RuntimeStatus:
    def __init__(
        self,
        *,
        cdc_debug_status="never",
        loop_checkpoint="startup",
        request_active=False,
        response_length=0,
        response_complete=False,
    ):
        self.cdc_debug_status = cdc_debug_status
        self.loop_checkpoint = loop_checkpoint
        self.request_active = request_active
        self.response_length = response_length
        self.response_complete = response_complete


class BridgeApp:
    def __init__(self, *, jetson_transport, runtime_status):
        self._jetson_transport = jetson_transport
        self._runtime_status = runtime_status

    def prepare_upload_result(self, app_command, text):
        status = self._runtime_status()

        if app_command == AppCommand.FEATURE_1:
            return self._prepare_feature_1(text, status)

        return {
            "accepted_text": text,
            "accepted_count": len(text),
            "skipped_count": 0,
            "detail": "accepted",
            "response_text": (
                f"PICO ECHO: {text}\n"
                f"CDC DEBUG: {status.cdc_debug_status}\n"
                f"LOOP CHECKPOINT: {status.loop_checkpoint}"
            ),
            "app_command": int(app_command),
        }

    def _prepare_feature_1(self, text, status):
        return self._forward_request_text(text, status)

    def _forward_request_text(self, text, status):
        try:
            if self._jetson_transport is None:
                return {
                    "status_code": StatusCode.INTERNAL_ERROR,
                    "detail": "uart unavailable",
                    "accepted_count": 0,
                    "skipped_count": 0,
                }
            if status.request_active:
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
                self._jetson_transport.start_request(payload)
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
                "app_command": int(AppCommand.FEATURE_1),
            }
        except Exception as exc:
            return {
                "status_code": StatusCode.INTERNAL_ERROR,
                "detail": f"outer:{type(exc).__name__}"[:18],
                "accepted_count": 0,
                "skipped_count": 0,
            }

    def handle_button_press(self, index):
        if index != 0:
            return None

        return self._forward_request_text(
            SUMMARIZE_COMMAND_TEXT,
            self._runtime_status(),
        )


def build_text_preparer(*, jetson_transport, runtime_status):
    return BridgeApp(jetson_transport=jetson_transport, runtime_status=runtime_status).prepare_upload_result


def build_button_press_handler(*, jetson_transport, runtime_status):
    return BridgeApp(jetson_transport=jetson_transport, runtime_status=runtime_status).handle_button_press
