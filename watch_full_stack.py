import argparse
from collections import deque
from dataclasses import dataclass
import logging
import os
import re
from pathlib import Path
import subprocess
import sys
import time

from app_log_contract import APP_LOG_FILE_FORMAT


PICO_DEBUG_LOGGER_NAME = "pico.debug"

DEFAULT_APP_LOG = r"logs\spark_app_v2.log"
DEFAULT_BRIDGE_LOG = r"Z:\demo\pico_bridge\bridge.log"
DEFAULT_LLM_LOG = r"Z:\demo\llama_demo\server.log"
DEFAULT_REMOTE_BRIDGE_LOG = "/mnt/usb_drive/demo/pico_bridge/bridge.log"
DEFAULT_REMOTE_LLM_LOG = "/mnt/usb_drive/demo/llama_demo/server.log"
DEFAULT_SSH_TARGET = "192.168.55.1"
WINDOWS_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

AVAILABILITY_PRESENT = "present"
AVAILABILITY_MISSING = "missing"
AVAILABILITY_UNKNOWN = "unknown"

COMPONENT_APP_PROCESS = "app-process"
COMPONENT_APP_LOG = "app-log"
COMPONENT_JETSON_BRIDGE_PROCESS = "jetson-bridge-process"
COMPONENT_JETSON_BRIDGE_LOG = "jetson-bridge-log"
COMPONENT_JETSON_LLAMA_PROCESS = "jetson-llama-process"
COMPONENT_JETSON_LLM_LOG = "jetson-llm-log"

MAJOR_COMPONENT_APP = "app"
MAJOR_COMPONENT_JETSON_BRIDGE = "jetson-bridge"
MAJOR_COMPONENT_JETSON_LLM = "jetson-llm"

_EXPECTATION_FLAG_BY_MAJOR_COMPONENT = {
    MAJOR_COMPONENT_APP: "expect_app",
    MAJOR_COMPONENT_JETSON_BRIDGE: "expect_jetson_bridge",
    MAJOR_COMPONENT_JETSON_LLM: "expect_jetson_llm",
}

_MAJOR_COMPONENT_BY_CHECKED_COMPONENT = {
    COMPONENT_APP_PROCESS: MAJOR_COMPONENT_APP,
    COMPONENT_APP_LOG: MAJOR_COMPONENT_APP,
    COMPONENT_JETSON_BRIDGE_PROCESS: MAJOR_COMPONENT_JETSON_BRIDGE,
    COMPONENT_JETSON_BRIDGE_LOG: MAJOR_COMPONENT_JETSON_BRIDGE,
    COMPONENT_JETSON_LLAMA_PROCESS: MAJOR_COMPONENT_JETSON_LLM,
    COMPONENT_JETSON_LLM_LOG: MAJOR_COMPONENT_JETSON_LLM,
}

_LEVEL_NAME_PATTERN = "|".join(
    re.escape(level_name)
    for level_name in sorted(logging.getLevelNamesMapping(), key=len, reverse=True)
    if level_name.isupper()
)

_FORMAT_FIELD_PATTERNS = {
    "asctime": r"(?P<asctime>.+?)",
    "name": r"(?P<name>\S+)",
    "levelname": rf"(?P<levelname>{_LEVEL_NAME_PATTERN})",
    "message": r"(?P<message>.*)",
}


def _build_app_log_line_regex():
    pattern = re.escape(APP_LOG_FILE_FORMAT)
    for field_name, field_pattern in _FORMAT_FIELD_PATTERNS.items():
        pattern = pattern.replace(re.escape(f"%({field_name})s"), field_pattern)
    return re.compile(f"^{pattern}$")


_APP_LOG_LINE_RE = _build_app_log_line_regex()
_BRIDGE_LOG_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[[A-Z]+\] ")


@dataclass(frozen=True)
class LogEvent:
    source: str
    message: str


@dataclass(frozen=True)
class RenderEvent:
    kind: str
    label: str
    message: str


@dataclass(frozen=True)
class HealthCheckResult:
    component_name: str
    label: str
    availability: str
    status: str
    match_count: int = 0
    matches: tuple[str, ...] = ()
    ssh_target: str | None = None
    ssh_error_detail: str | None = None


@dataclass(frozen=True)
class StateTransition:
    kind: str
    label: str


@dataclass
class _TrackedState:
    availability: str = AVAILABILITY_PRESENT
    startup_catchup_complete: bool = False
    startup_catchup_completed_at: float | None = None
    last_event_at: float | None = None
    quiet: bool = False


class StateTracker:
    def __init__(self, *, quiet_after_seconds):
        self._quiet_after_seconds = quiet_after_seconds
        self._states = {}
        self._shared_ssh_states = {}

    def _state_for(self, label):
        return self._states.setdefault(label, _TrackedState())

    def update_availability(self, label, availability):
        state = self._state_for(label)
        previous_availability = state.availability
        if previous_availability == availability:
            return []

        state.availability = availability
        if availability == AVAILABILITY_MISSING:
            state.last_event_at = None
            state.quiet = False
            return [StateTransition(kind="missing", label=label)]

        if previous_availability == AVAILABILITY_MISSING and availability == AVAILABILITY_PRESENT:
            return [StateTransition(kind="recovered", label=label)]

        if availability != AVAILABILITY_PRESENT:
            state.quiet = False

        return []

    def mark_startup_catchup_complete(self, label, *, now):
        state = self._state_for(label)
        state.startup_catchup_complete = True
        state.startup_catchup_completed_at = now

    def record_event(self, label, *, now):
        state = self._state_for(label)
        state.last_event_at = now
        if not state.quiet:
            return []

        state.quiet = False
        return [StateTransition(kind="active-again", label=label)]

    def poll(self, *, now):
        transitions = []
        for label, state in self._states.items():
            if state.quiet:
                continue
            if state.availability != AVAILABILITY_PRESENT:
                continue
            if not state.startup_catchup_complete or state.last_event_at is None:
                continue

            quiet_reference_at = state.last_event_at
            if (
                state.startup_catchup_completed_at is not None
                and state.startup_catchup_completed_at > quiet_reference_at
            ):
                quiet_reference_at = state.startup_catchup_completed_at

            if now - quiet_reference_at < self._quiet_after_seconds:
                continue

            state.quiet = True
            transitions.append(StateTransition(kind="quiet", label=label))

        return transitions

    def update_shared_ssh_availability(self, target, availability):
        previous_availability = self._shared_ssh_states.get(target)
        self._shared_ssh_states[target] = availability
        return previous_availability


def _file_identity(stat_result):
    return stat_result.st_dev, stat_result.st_ino


def _watcher_platform(platform=None):
    return platform or sys.platform


def default_bridge_log_path(*, platform=None):
    if _watcher_platform(platform).startswith("win"):
        return DEFAULT_BRIDGE_LOG
    return DEFAULT_REMOTE_BRIDGE_LOG


def default_llm_log_path(*, platform=None):
    if _watcher_platform(platform).startswith("win"):
        return DEFAULT_LLM_LOG
    return DEFAULT_REMOTE_LLM_LOG


def should_use_ssh_log_source(path, *, platform=None):
    if _watcher_platform(platform).startswith("win"):
        return False
    return str(path).startswith("/mnt/")


class FileTailSource:
    _FINGERPRINT_BYTES = 64

    def __init__(self, path, *, source_label, mapper=None):
        self._path = Path(path)
        self._source_label = source_label
        self._mapper = mapper or self._default_mapper
        self._identity = None
        self._position = None
        self._tail_fingerprint = b""

    @property
    def source_label(self):
        return self._source_label

    def _clear_state(self):
        self._identity = None
        self._position = None
        self._tail_fingerprint = b""

    def _default_mapper(self, line):
        return LogEvent(source=self._source_label, message=line)

    def _read_tail_fingerprint(self, handle, end_position):
        start_position = max(0, end_position - self._FINGERPRINT_BYTES)
        handle.seek(start_position)
        return handle.read(end_position - start_position)

    def _set_to_eof(self, identity):
        try:
            with self._path.open("rb") as handle:
                handle.seek(0, 2)
                eof_position = handle.tell()
                tail_fingerprint = self._read_tail_fingerprint(handle, eof_position)
        except OSError:
            self._clear_state()
            return False

        self._identity = identity
        self._position = eof_position
        self._tail_fingerprint = tail_fingerprint
        return True

    def _normalize_event(self, mapped_value):
        if mapped_value is None:
            return None
        if isinstance(mapped_value, LogEvent):
            return mapped_value
        source, message = mapped_value
        return LogEvent(source=source, message=message)

    def _map_chunk(self, chunk):
        events = []
        for line in chunk.decode("utf-8", errors="replace").splitlines():
            event = self._normalize_event(self._mapper(line))
            if event is not None:
                events.append(event)
        return events

    def poll(self):
        try:
            stat_result = self._path.stat()
        except OSError:
            self._clear_state()
            return []

        identity = _file_identity(stat_result)
        if self._identity is None or self._position is None:
            self._set_to_eof(identity)
            return []

        if identity != self._identity:
            self._set_to_eof(identity)
            return []

        try:
            with self._path.open("rb") as handle:
                if stat_result.st_size < self._position:
                    self._position = 0
                elif self._position > 0:
                    current_tail = self._read_tail_fingerprint(handle, self._position)
                    if current_tail != self._tail_fingerprint:
                        self._position = 0

                if stat_result.st_size == self._position:
                    self._tail_fingerprint = self._read_tail_fingerprint(handle, self._position)
                    return []

                handle.seek(self._position)
                chunk = handle.read()
                self._position += len(chunk)
                self._tail_fingerprint = self._read_tail_fingerprint(handle, self._position)
        except OSError:
            self._clear_state()
            return []

        return self._map_chunk(chunk)


class SshTailSource:
    def __init__(self, path, *, target, source_label, mapper=None, runner=None, tail_lines=200):
        self._path = path
        self._target = target
        self._source_label = source_label
        self._mapper = mapper or self._default_mapper
        self._runner = runner or _default_subprocess_runner
        self._tail_lines = tail_lines
        self._previous_lines = None

    @property
    def source_label(self):
        return self._source_label

    def _default_mapper(self, line):
        return LogEvent(source=self._source_label, message=line)

    def _normalize_event(self, mapped_value):
        if mapped_value is None:
            return None
        if isinstance(mapped_value, LogEvent):
            return mapped_value
        source, message = mapped_value
        return LogEvent(source=source, message=message)

    def _map_lines(self, lines):
        events = []
        for line in lines:
            event = self._normalize_event(self._mapper(line))
            if event is not None:
                events.append(event)
        return events

    def _fetch_lines(self):
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "ServerAliveInterval=10",
            self._target,
            "tail",
            "-n",
            str(self._tail_lines),
            self._path,
        ]
        completed = self._runner(command)
        if completed.returncode != 0:
            return None
        return (completed.stdout or "").splitlines()

    @staticmethod
    def _overlap_size(previous_lines, current_lines):
        max_overlap = min(len(previous_lines), len(current_lines))
        for overlap in range(max_overlap, 0, -1):
            if previous_lines[-overlap:] == current_lines[:overlap]:
                return overlap
        return 0

    def poll(self):
        lines = self._fetch_lines()
        if lines is None:
            return []

        if self._previous_lines is None:
            self._previous_lines = tuple(lines)
            return []

        overlap = self._overlap_size(self._previous_lines, lines)
        self._previous_lines = tuple(lines)
        if overlap == 0:
            return []
        return self._map_lines(lines[overlap:])


def _looks_like_app_log_asctime(asctime):
    return any(character.isdigit() for character in asctime)


def map_app_log_line(line):
    normalized_line = line.rstrip("\r\n")
    match = _APP_LOG_LINE_RE.match(normalized_line)
    if match is None:
        return "APP", normalized_line
    if not _looks_like_app_log_asctime(match.group("asctime")):
        return "APP", normalized_line

    source = "PICO" if match.group("name") == PICO_DEBUG_LOGGER_NAME else "APP"
    message = match.group("message")
    if source == "PICO" and message.startswith("[PICO] "):
        message = message[len("[PICO] "):]
    return source, message


def update_app_serial_status_line(current_line, message):
    if not message.startswith("SerialSender:"):
        return current_line

    detail = message[len("SerialSender:"):].strip()
    lowered = detail.lower()

    if lowered.startswith("connected on "):
        return f"APP CDC: connected | {detail[len('connected on '):]}"
    if lowered.startswith("write error - "):
        return f"APP CDC: error | {detail[len('write error - '):].lower()}"
    if lowered.startswith("read error - "):
        return f"APP CDC: error | {detail[len('read error - '):].lower()}"
    if lowered.startswith("open failed - "):
        return f"APP CDC: unavailable | {detail[len('open failed - '):].lower()}"
    if lowered == "no pico port found":
        return "APP CDC: unavailable | no pico port found"
    if lowered in {"closed", "paused and port released"}:
        return f"APP CDC: closed | {lowered}"
    if lowered == "resumed":
        return "APP CDC: reconnecting | resumed"
    return current_line


class AppLogSource(FileTailSource):
    def __init__(self, path):
        super().__init__(path, source_label="APP", mapper=self._map_line)
        self.serial_status_line = None
        self._bootstrap_serial_status()

    def _bootstrap_serial_status(self):
        try:
            lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        except OSError:
            return
        for line in lines:
            event = map_app_log_line(line)
            if event is None:
                continue
            source, message = event
            if source == "APP":
                self.serial_status_line = update_app_serial_status_line(self.serial_status_line, message)

    def _map_line(self, line):
        event = map_app_log_line(line)
        if event is None:
            return None
        source, message = event
        if source == "APP":
            self.serial_status_line = update_app_serial_status_line(self.serial_status_line, message)
        return LogEvent(source=source, message=message)


def _strip_bridge_log_prefix(line):
    normalized_line = line.rstrip("\r\n")
    return _BRIDGE_LOG_PREFIX_RE.sub("", normalized_line)


def map_bridge_log_line(line):
    message = _strip_bridge_log_prefix(line)

    if message.startswith("Handling summarize request:"):
        return LogEvent(source="JETSON-BRIDGE", message="summarize request started")

    if message.startswith("Summarize request completed"):
        return LogEvent(source="JETSON-BRIDGE", message="summarize request finished")

    if (
        message.startswith("[UART OUT] summarize_response")
        or message.startswith("[UART OUT] summarize_chunk")
        or message.startswith("[UART OUT] summarize_done")
    ):
        return None

    return LogEvent(source="JETSON-BRIDGE", message=message)


def map_llm_log_line(line):
    message = line.rstrip("\r\n")
    lowercase_message = message.lower()

    if "processing task, is_child = 0" in message:
        return LogEvent(source="JETSON-LLM", message="request received")

    if "done request: post /v1/chat/completions" in lowercase_message:
        return LogEvent(source="JETSON-LLM", message="output generation finished")

    if "error" in lowercase_message or "failed" in lowercase_message or "exception" in lowercase_message:
        return LogEvent(source="JETSON-LLM", message=message)

    return None


def _nonempty_output_lines(output):
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def _first_command_token(command_line):
    match = re.match(r'^\s*(?:"([^"]+)"|(\S+))', command_line)
    if match is None:
        return ""
    return match.group(1) or match.group(2) or ""


def _looks_like_python_process(command_line):
    executable = _first_command_token(command_line)
    if not executable:
        return False
    executable_name = Path(executable).name.lower()
    return executable_name.startswith("python") or executable_name in {"py", "py.exe"}


def _process_snapshot_command():
    if sys.platform.startswith("win"):
        return [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine",
        ]
    return ["ps", "-ax", "-o", "command="]


def _default_subprocess_runner(command):
    return subprocess.run(command, capture_output=True, text=True, check=False)


def check_local_spark_app_process(command_output):
    matches = tuple(
        line
        for line in _nonempty_output_lines(command_output)
        if "spark_app_v2.py" in line.lower() and _looks_like_python_process(line)
    )
    match_count = len(matches)
    if match_count:
        return HealthCheckResult(
            component_name=COMPONENT_APP_PROCESS,
            label="APP",
            availability=AVAILABILITY_PRESENT,
            status=f"App process running ({match_count} matches)",
            match_count=match_count,
            matches=matches,
        )

    return HealthCheckResult(
        component_name=COMPONENT_APP_PROCESS,
        label="APP",
        availability=AVAILABILITY_MISSING,
        status="App process missing",
    )


def _check_local_app_process_result(*, runner=None):
    command_runner = runner or _default_subprocess_runner
    command = _process_snapshot_command()
    try:
        completed = command_runner(command)
    except OSError as exc:
        return HealthCheckResult(
            component_name=COMPONENT_APP_PROCESS,
            label="APP",
            availability=AVAILABILITY_UNKNOWN,
            status=f"App process check failed: {exc}",
        )

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        return HealthCheckResult(
            component_name=COMPONENT_APP_PROCESS,
            label="APP",
            availability=AVAILABILITY_UNKNOWN,
            status=f"App process check failed: {detail}",
        )

    return check_local_spark_app_process(completed.stdout or "")


def build_ssh_process_health_result(*, target, component_name, label, description, stdout, returncode, stderr):
    matches = _nonempty_output_lines(stdout)
    match_count = len(matches)
    if returncode == 0 and match_count:
        return HealthCheckResult(
            component_name=component_name,
            label=label,
            availability=AVAILABILITY_PRESENT,
            status=f"{description} running ({match_count} matches)",
            match_count=match_count,
            matches=matches,
            ssh_target=target,
        )

    if returncode == 1 and not matches:
        return HealthCheckResult(
            component_name=component_name,
            label=label,
            availability=AVAILABILITY_MISSING,
            status=f"{description} missing",
            ssh_target=target,
        )

    detail = (stderr or stdout or f"exit {returncode}").strip()
    return HealthCheckResult(
        component_name=component_name,
        label=label,
        availability=AVAILABILITY_UNKNOWN,
        status=f"{description} SSH check failed for {target}: {detail}",
        ssh_target=target,
        ssh_error_detail=detail,
    )


def check_ssh_process(*, target, pattern, component_name, label, description, runner=None):
    if runner is None:
        runner = _default_subprocess_runner

    command = ["ssh", target, "pgrep", "-af", pattern]
    try:
        completed = runner(command)
    except OSError as exc:
        return build_ssh_process_health_result(
            target=target,
            component_name=component_name,
            label=label,
            description=description,
            stdout="",
            returncode=-1,
            stderr=str(exc),
        )

    return build_ssh_process_health_result(
        target=target,
        component_name=component_name,
        label=label,
        description=description,
        stdout=completed.stdout or "",
        returncode=completed.returncode,
        stderr=completed.stderr or "",
    )


def check_ssh_readable_path(*, target, path, component_name, label, description, runner=None):
    if runner is None:
        runner = _default_subprocess_runner

    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", target, "test", "-r", path]
    try:
        completed = runner(command)
    except OSError as exc:
        return HealthCheckResult(
            component_name=component_name,
            label=label,
            availability=AVAILABILITY_UNKNOWN,
            status=f"{description} SSH check failed for {target}: {exc}",
            ssh_target=target,
            ssh_error_detail=str(exc),
        )

    if completed.returncode == 0:
        return HealthCheckResult(
            component_name=component_name,
            label=label,
            availability=AVAILABILITY_PRESENT,
            status=f"{description} readable via SSH: {path}",
            ssh_target=target,
        )

    if completed.returncode == 1:
        return HealthCheckResult(
            component_name=component_name,
            label=label,
            availability=AVAILABILITY_MISSING,
            status=f"{description} missing via SSH: {path}",
            ssh_target=target,
        )

    detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
    return HealthCheckResult(
        component_name=component_name,
        label=label,
        availability=AVAILABILITY_UNKNOWN,
        status=f"{description} SSH check failed for {target}: {detail}",
        ssh_target=target,
        ssh_error_detail=detail,
    )


def check_readable_path(path, *, component_name, label, description):
    target_path = Path(path)
    try:
        with target_path.open("rb") as handle:
            handle.read(1)
    except OSError:
        return HealthCheckResult(
            component_name=component_name,
            label=label,
            availability=AVAILABILITY_MISSING,
            status=f"{description} missing or unreadable: {target_path}",
        )

    return HealthCheckResult(
        component_name=component_name,
        label=label,
        availability=AVAILABILITY_PRESENT,
        status=f"{description} readable: {target_path}",
    )


def select_expectation_mode(args):
    for flag_name in _EXPECTATION_FLAG_BY_MAJOR_COMPONENT.values():
        if getattr(args, flag_name, False):
            return "allowlist"
    return "all-major"


def evaluate_component_requirement(component_name, args):
    expectation_mode = select_expectation_mode(args)
    if expectation_mode == "all-major":
        return True
    major_component = _MAJOR_COMPONENT_BY_CHECKED_COMPONENT[component_name]
    return getattr(args, _EXPECTATION_FLAG_BY_MAJOR_COMPONENT[major_component], False)


def collect_health_check_results(args, *, local_runner=None, ssh_runner=None, platform=None):
    if should_use_ssh_log_source(args.bridge_log, platform=platform):
        bridge_log_result = check_ssh_readable_path(
            target=args.ssh_target,
            path=args.bridge_log,
            component_name=COMPONENT_JETSON_BRIDGE_LOG,
            label="JETSON-BRIDGE",
            description="Jetson bridge log",
            runner=ssh_runner,
        )
    else:
        bridge_log_result = check_readable_path(
            args.bridge_log,
            component_name=COMPONENT_JETSON_BRIDGE_LOG,
            label="JETSON-BRIDGE",
            description="Jetson bridge log",
        )

    if should_use_ssh_log_source(args.llm_log, platform=platform):
        llm_log_result = check_ssh_readable_path(
            target=args.ssh_target,
            path=args.llm_log,
            component_name=COMPONENT_JETSON_LLM_LOG,
            label="JETSON-LLM",
            description="Jetson llm log",
            runner=ssh_runner,
        )
    else:
        llm_log_result = check_readable_path(
            args.llm_log,
            component_name=COMPONENT_JETSON_LLM_LOG,
            label="JETSON-LLM",
            description="Jetson llm log",
        )

    return [
        _check_local_app_process_result(runner=local_runner),
        check_readable_path(
            args.app_log,
            component_name=COMPONENT_APP_LOG,
            label="APP",
            description="App log",
        ),
        check_ssh_process(
            target=args.ssh_target,
            pattern="pico_llm_bridge.py",
            component_name=COMPONENT_JETSON_BRIDGE_PROCESS,
            label="JETSON-BRIDGE",
            description="Jetson bridge process",
            runner=ssh_runner,
        ),
        bridge_log_result,
        check_ssh_process(
            target=args.ssh_target,
            pattern="llama-server",
            component_name=COMPONENT_JETSON_LLAMA_PROCESS,
            label="JETSON-LLM",
            description="Jetson llm process",
            runner=ssh_runner,
        ),
        llm_log_result,
    ]


_CHECK_WARNING_MESSAGES = {
    COMPONENT_APP_PROCESS: {"missing": "APP missing", "recovered": "APP recovered"},
    COMPONENT_APP_LOG: {"missing": "APP log missing", "recovered": "APP log recovered"},
    COMPONENT_JETSON_BRIDGE_PROCESS: {
        "missing": "JETSON bridge process missing",
        "recovered": "JETSON bridge process recovered",
    },
    COMPONENT_JETSON_BRIDGE_LOG: {
        "missing": "JETSON bridge log missing",
        "recovered": "JETSON bridge log recovered",
    },
    COMPONENT_JETSON_LLAMA_PROCESS: {
        "missing": "JETSON llm process missing",
        "recovered": "JETSON llm process recovered",
    },
    COMPONENT_JETSON_LLM_LOG: {
        "missing": "JETSON llm log missing",
        "recovered": "JETSON llm log recovered",
    },
}


def _build_transition_status(result, transition_kind):
    return _CHECK_WARNING_MESSAGES[result.component_name][transition_kind]


def _build_unknown_status(result):
    detail = result.ssh_error_detail or result.status
    return f"SSH check failed: {detail}"


def collect_health_warnings(result, *, tracker, args):
    if not evaluate_component_requirement(result.component_name, args):
        return []

    previous_state = tracker._states.get(result.component_name)
    previous_shared_ssh_availability = None
    previous_availability = None if previous_state is None else previous_state.availability
    transitions = tracker.update_availability(result.component_name, result.availability)
    if result.ssh_target is not None:
        previous_shared_ssh_availability = tracker.update_shared_ssh_availability(
            result.ssh_target,
            result.availability,
        )

    if result.availability == AVAILABILITY_UNKNOWN:
        if previous_shared_ssh_availability != AVAILABILITY_UNKNOWN or previous_availability != AVAILABILITY_UNKNOWN:
            return [_build_unknown_status(result)]
        return []

    if transitions:
        return [_build_transition_status(result, transitions[0].kind)]
    return []


def build_startup_summary_data(results, *, args):
    summary = []
    for result in results:
        summary.append(
            {
                "component_name": result.component_name,
                "label": result.label,
                "required": evaluate_component_requirement(result.component_name, args),
                "availability": result.availability,
                "status": result.status,
                "match_count": result.match_count,
            }
        )
    return summary


def render_startup_summary(summary_data):
    lines = ["Startup summary:"]
    for item in summary_data:
        requirement = "required" if item["required"] else "optional"
        lines.append(f"- {requirement} {item['component_name']}: {item['status']}")
    return "\n".join(lines)


_SOURCE_TRANSITION_MESSAGES = {
    "APP": {"quiet": "APP quiet", "active-again": "APP active again"},
    "PICO": {"quiet": "PICO quiet", "active-again": "PICO active again"},
    "JETSON-BRIDGE": {
        "quiet": "JETSON-BRIDGE quiet",
        "active-again": "JETSON-BRIDGE active again",
    },
    "JETSON-LLM": {"quiet": "JETSON-LLM quiet", "active-again": "JETSON-LLM active again"},
}

_COMPONENT_DISPLAY_NAMES = {
    COMPONENT_APP_PROCESS: "APP process",
    COMPONENT_APP_LOG: "APP log",
    COMPONENT_JETSON_BRIDGE_PROCESS: "JETSON bridge process",
    COMPONENT_JETSON_BRIDGE_LOG: "JETSON bridge log",
    COMPONENT_JETSON_LLAMA_PROCESS: "JETSON llm process",
    COMPONENT_JETSON_LLM_LOG: "JETSON llm log",
}


def _pico_response_label(state):
    if state.response_active:
        return "STREAMING"
    if state.response_complete:
        return "COMPLETE"
    if state.response_len > 0:
        return "PARTIAL"
    return "empty"


def build_pico_status_line(state):
    if state is None:
        return "PICO HID: unknown | poll unavailable"
    if not state.connected:
        detail = state.error or "device not found"
        return f"PICO HID: missing | {detail}"

    upload_label = "ACTIVE" if state.upload_active else "idle"
    line = (
        f"PICO HID: present | upload={upload_label} msg_id={state.active_message_id} "
        f"response={_pico_response_label(state)} len={state.response_len} chunks={state.response_chunk_count}"
    )
    runtime_status_text = getattr(state, "runtime_status_text", "") or ""
    if runtime_status_text:
        line += f" | debug={runtime_status_text}"
    if state.error:
        line += f" | {state.error}"
    return line


def _source_transition_message(transition):
    messages = _SOURCE_TRANSITION_MESSAGES.get(transition.label)
    if messages is None:
        return f"{transition.label} {transition.kind}"
    return messages[transition.kind]


def render_watch_event(event, *, out, now_text=None):
    timestamp = now_text or time.strftime("%H:%M:%S")
    if event.kind == "log":
        print(f"[{timestamp}] [{event.label}] {event.message}", file=out, flush=True)
        return
    if event.kind == "check":
        print(f"[{timestamp}] [CHECK] {event.message}", file=out, flush=True)
        return
    raise ValueError(f"unsupported render event kind: {event.kind!r}")


def format_watch_event(event, *, now_text=None):
    out = []
    class _Capture:
        def write(self, text):
            out.append(text)
        def flush(self):
            pass
    render_watch_event(event, out=_Capture(), now_text=now_text)
    return "".join(out).rstrip("\n")


def _render_component_line(result):
    display_name = _COMPONENT_DISPLAY_NAMES.get(result.component_name, result.component_name)
    if result.availability == AVAILABILITY_PRESENT:
        state = "present"
    elif result.availability == AVAILABILITY_MISSING:
        state = "missing"
    else:
        state = "unknown"
    return f"{display_name}: {state} | {result.status}"


def build_component_lines(results, *, pico_state=None, app_serial_status_line=None):
    lines = []
    if pico_state is not None:
        lines.append(build_pico_status_line(pico_state))
    if app_serial_status_line:
        lines.append(app_serial_status_line)
    lines.extend(_render_component_line(result) for result in results)
    return lines


def build_pico_poller(*, app_running=False):
    if app_running:
        return None
    try:
        from pico_monitor import HIDPoller
    except Exception:
        return None

    try:
        return HIDPoller()
    except SystemExit:
        return None
    except Exception:
        return None


def poll_pico_state(pico_poller):
    if pico_poller is None:
        return None
    try:
        return pico_poller.poll()
    except Exception:
        return None


def _append_pico_runtime_events(
    rendered_events,
    *,
    previous_text,
    previous_emitted_at,
    pico_state,
    now,
    heartbeat_interval_s=5.0,
):
    runtime_text = ""
    if pico_state is not None:
        runtime_text = getattr(pico_state, "runtime_status_text", "") or ""

    if not runtime_text:
        return runtime_text, previous_emitted_at

    runtime_message = runtime_text.split("|", 1)[0]
    should_emit = runtime_text != previous_text
    if runtime_message == "heartbeat" and previous_emitted_at is not None:
        if (now - previous_emitted_at) >= heartbeat_interval_s:
            should_emit = True

    if should_emit:
        rendered_events.append(RenderEvent(kind="log", label="PICO", message=runtime_message))
        return runtime_text, now
    return runtime_text, previous_emitted_at


def build_dashboard_frame(*, component_lines, log_lines, now_text=None):
    timestamp = now_text or time.strftime("%H:%M:%S")
    lines = []
    lines.append(f"SPARK Full Stack Watcher  {timestamp}")
    lines.append("=" * 72)
    lines.append("Status")
    if component_lines:
        lines.extend(component_lines)
    else:
        lines.append("(no component status yet)")
    lines.append("")
    lines.append("Recent Log")
    if log_lines:
        lines.extend(log_lines)
    else:
        lines.append("(no log lines yet)")
    return "\n".join(lines)


class DashboardRenderer:
    def __init__(self, *, out, interactive, redraw=None):
        self._out = out
        self._interactive = interactive
        self._redraw = redraw

    def render(self, frame):
        if self._interactive:
            if self._redraw is not None:
                self._redraw(frame)
                return
            self._out.write("\x1b[H\x1b[J")
            self._out.write(frame)
            self._out.flush()
            return
        print(frame, file=self._out, flush=True)


def redraw_windows_console(frame, stream):
    import ctypes
    import msvcrt

    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        stream.write(frame)
        stream.flush()
        return

    fd = stream.fileno()
    kernel32 = ctypes.windll.kernel32
    handle = msvcrt.get_osfhandle(fd)

    class COORD(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [
            ("Left", ctypes.c_short),
            ("Top", ctypes.c_short),
            ("Right", ctypes.c_short),
            ("Bottom", ctypes.c_short),
        ]

    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [
            ("dwSize", COORD),
            ("dwCursorPosition", COORD),
            ("wAttributes", ctypes.c_ushort),
            ("srWindow", SMALL_RECT),
            ("dwMaximumWindowSize", COORD),
        ]

    info = CONSOLE_SCREEN_BUFFER_INFO()
    if not kernel32.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
        stream.write(frame)
        stream.flush()
        return

    home = COORD(0, 0)
    written = ctypes.c_uint()
    cells = info.dwSize.X * info.dwSize.Y
    kernel32.FillConsoleOutputCharacterW(handle, ctypes.c_wchar(" "), cells, home, ctypes.byref(written))
    kernel32.FillConsoleOutputAttribute(handle, info.wAttributes, cells, home, ctypes.byref(written))
    kernel32.SetConsoleCursorPosition(handle, home)
    stream.write(frame)
    stream.flush()


def build_dashboard_renderer(out):
    interactive = should_use_interactive_dashboard(out)
    redraw = None
    if interactive and os.name == "nt":
        redraw = lambda frame: redraw_windows_console(frame, out)
    return DashboardRenderer(out=out, interactive=interactive, redraw=redraw)


def enable_windows_virtual_terminal(stream):
    if os.name != "nt":
        return True

    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        return False

    try:
        fd = stream.fileno()
    except OSError:
        return False

    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(fd)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & WINDOWS_ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(
            kernel32.SetConsoleMode(
                handle,
                mode.value | WINDOWS_ENABLE_VIRTUAL_TERMINAL_PROCESSING,
            )
        )
    except Exception:
        return False


def should_use_interactive_dashboard(out, *, os_name=None, enable_vt=None):
    return False


def build_default_sources(args, *, platform=None):
    app_source = AppLogSource(args.app_log)
    if should_use_ssh_log_source(args.bridge_log, platform=platform):
        bridge_source = SshTailSource(
            args.bridge_log,
            target=args.ssh_target,
            source_label="JETSON-BRIDGE",
            mapper=map_bridge_log_line,
        )
    else:
        bridge_source = FileTailSource(args.bridge_log, source_label="JETSON-BRIDGE", mapper=map_bridge_log_line)

    if should_use_ssh_log_source(args.llm_log, platform=platform):
        llm_source = SshTailSource(
            args.llm_log,
            target=args.ssh_target,
            source_label="JETSON-LLM",
            mapper=map_llm_log_line,
        )
    else:
        llm_source = FileTailSource(args.llm_log, source_label="JETSON-LLM", mapper=map_llm_log_line)

    return [
        app_source,
        bridge_source,
        llm_source,
    ]


def get_app_serial_status_line(sources):
    for source in sources:
        status_line = getattr(source, "serial_status_line", None)
        if status_line:
            return status_line
    return None


def app_process_running(results):
    for result in results:
        if result.component_name == COMPONENT_APP_PROCESS and result.availability == AVAILABILITY_PRESENT:
            return True
    return False


def _source_label_from_source(source):
    return getattr(source, "source_label", getattr(source, "_source_label", None))


def _apply_initial_health_state(results, *, tracker):
    for result in results:
        tracker.update_availability(result.component_name, result.availability)
        if result.ssh_target is not None:
            tracker.update_shared_ssh_availability(result.ssh_target, result.availability)


def _poll_source_events(source, *, tracker, now):
    rendered = []
    for event in source.poll():
        rendered.append(RenderEvent(kind="log", label=event.source, message=event.message))
        for transition in tracker.record_event(event.source, now=now):
            rendered.append(
                RenderEvent(kind="check", label=transition.label, message=_source_transition_message(transition))
            )
    return rendered


def build_parser(*, platform=None):
    default_bridge_log = default_bridge_log_path(platform=platform)
    default_llm_log = default_llm_log_path(platform=platform)
    parser = argparse.ArgumentParser(description="Watch SPARK host, Pico, and Jetson logs in one stream")
    parser.add_argument("--quiet-seconds", type=float, default=30.0, help="Warn after this many quiet seconds")
    parser.add_argument("--check-interval", type=float, default=1.0, help="Run health checks this often in seconds")
    parser.add_argument("--app-log", default=DEFAULT_APP_LOG, help=f"Host app log path (default: {DEFAULT_APP_LOG})")
    parser.add_argument("--bridge-log", default=default_bridge_log, help=f"Jetson bridge log path (default: {default_bridge_log})")
    parser.add_argument("--llm-log", default=default_llm_log, help=f"Jetson llama log path (default: {default_llm_log})")
    parser.add_argument("--ssh-target", default=DEFAULT_SSH_TARGET, help=f"Jetson SSH target (default: {DEFAULT_SSH_TARGET})")
    parser.add_argument("--expect-app", action="store_true", help="When any expect flag is used, require app checks")
    parser.add_argument("--expect-jetson-bridge", action="store_true", help="When any expect flag is used, require Jetson bridge checks")
    parser.add_argument("--expect-jetson-llm", action="store_true", help="When any expect flag is used, require Jetson llama checks")
    return parser


def run_watch_loop(
    args,
    *,
    out=None,
    sources=None,
    health_check_runner=None,
    pico_poller=None,
    monotonic=None,
    sleep_fn=None,
    max_iterations=None,
):
    if out is None:
        out = sys.stdout
    if monotonic is None:
        monotonic = time.monotonic
    if sleep_fn is None:
        sleep_fn = time.sleep
    if sources is None:
        sources = build_default_sources(args)
    if health_check_runner is None:
        health_check_runner = collect_health_check_results
    renderer = build_dashboard_renderer(out)
    interactive = renderer._interactive

    tracker = StateTracker(quiet_after_seconds=args.quiet_seconds)
    startup_now = monotonic()
    startup_results = health_check_runner(args)
    if pico_poller is None:
        pico_poller = build_pico_poller(app_running=app_process_running(startup_results))
    latest_health_results = startup_results
    latest_pico_state = poll_pico_state(pico_poller)
    latest_app_serial_status_line = get_app_serial_status_line(sources)
    last_pico_runtime_text = ""
    last_pico_runtime_emitted_at = None
    if latest_pico_state is not None:
        last_pico_runtime_text = getattr(latest_pico_state, "runtime_status_text", "") or ""
    _apply_initial_health_state(startup_results, tracker=tracker)
    log_lines = deque(maxlen=40)
    if not interactive:
        print(render_startup_summary(build_startup_summary_data(startup_results, args=args)), file=out, flush=True)

    for source in sources:
        source.poll()
        source_label = _source_label_from_source(source)
        if source_label is not None:
            tracker.mark_startup_catchup_complete(source_label, now=startup_now)

    iteration_count = 0
    last_health_check_at = startup_now
    sleep_seconds = min(args.check_interval, 0.25) if args.check_interval > 0 else 0.25

    while True:
        if max_iterations is not None and iteration_count >= max_iterations:
            break

        now = monotonic()
        rendered_events = []

        for source in sources:
            rendered_events.extend(_poll_source_events(source, tracker=tracker, now=now))

        if now - last_health_check_at >= args.check_interval:
            latest_health_results = health_check_runner(args)
            latest_pico_state = poll_pico_state(pico_poller)
            latest_app_serial_status_line = get_app_serial_status_line(sources)
            last_pico_runtime_text, last_pico_runtime_emitted_at = _append_pico_runtime_events(
                rendered_events,
                previous_text=last_pico_runtime_text,
                previous_emitted_at=last_pico_runtime_emitted_at,
                pico_state=latest_pico_state,
                now=now,
            )
            for result in latest_health_results:
                for message in collect_health_warnings(result, tracker=tracker, args=args):
                    rendered_events.append(RenderEvent(kind="check", label=result.label, message=message))
            last_health_check_at = now

        for transition in tracker.poll(now=now):
            rendered_events.append(RenderEvent(kind="check", label=transition.label, message=_source_transition_message(transition)))

        if interactive:
            now_text = time.strftime("%H:%M:%S")
            for event in rendered_events:
                log_lines.append(format_watch_event(event, now_text=now_text))
            frame = build_dashboard_frame(
                component_lines=build_component_lines(
                    latest_health_results,
                    pico_state=latest_pico_state,
                    app_serial_status_line=latest_app_serial_status_line,
                ),
                log_lines=list(log_lines),
                now_text=now_text,
            )
            renderer.render(frame)
        else:
            latest_pico_state = poll_pico_state(pico_poller)
            latest_app_serial_status_line = get_app_serial_status_line(sources)
            last_pico_runtime_text, last_pico_runtime_emitted_at = _append_pico_runtime_events(
                rendered_events,
                previous_text=last_pico_runtime_text,
                previous_emitted_at=last_pico_runtime_emitted_at,
                pico_state=latest_pico_state,
                now=now,
            )
            for event in rendered_events:
                render_watch_event(event, out=out)

        iteration_count += 1
        if max_iterations is not None and iteration_count >= max_iterations:
            break
        sleep_fn(sleep_seconds)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run_watch_loop(args)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
