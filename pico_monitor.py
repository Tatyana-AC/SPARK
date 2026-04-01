"""
SPARK Pico real-time status monitor.

Polls the Pico's HID state (upload session + response buffer) every tick and
tails the Jetson bridge log over SSH in a background thread, printing a live
dashboard that shows exactly where a summarize request is in the pipeline.

Usage (from repo root):
    python pico_monitor.py
    python pico_monitor.py --poll-ms 100
    python pico_monitor.py --no-jetson
"""

import argparse
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# HID constants (must match host_pc/raw_hid.py)
# ---------------------------------------------------------------------------

SPARK_VID = 0xC4C4
SPARK_PID = 0x5350
RAW_USAGE_PAGE = 0xFF60
RAW_USAGE_ID = 0x61
RAW_REPORT_ID = 0x04
REPORT_SIZE = 32

CMD_GET_INFO = 0x01
CMD_GET_RESPONSE_INFO = 0x20

RESPONSE_FLAG_COMPLETE = 0x01
RESPONSE_FLAG_ACTIVE = 0x02


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _u16(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def _u32(data, offset):
    return (
        data[offset]
        | (data[offset + 1] << 8)
        | (data[offset + 2] << 16)
        | (data[offset + 3] << 24)
    )


@dataclass
class PicoState:
    connected: bool = False
    # GET_INFO fields
    protocol_version: int = 0
    chunk_payload_size: int = 0
    max_upload_bytes: int = 0
    max_chunk_count: int = 0
    capabilities: int = 0
    upload_active: bool = False
    active_message_id: int = 0
    # GET_RESPONSE_INFO fields
    response_len: int = 0
    response_chunk_count: int = 0
    response_complete: bool = False
    response_active: bool = False
    # Errors
    error: str = ""


# ---------------------------------------------------------------------------
# HID poller
# ---------------------------------------------------------------------------

class HIDPoller:
    """Polls the Pico HID state in a way that coexists with the host app.

    The host app continuously polls GET_RESPONSE_INFO at 8 Hz, so our writes
    and their reads interleave on the same endpoint.  When we send a request
    the reply might be consumed by the host app, or we might read a reply
    intended for the host.  Strategy:

    - Use short read timeouts (120 ms) so a missed reply is cheap.
    - After writing a command, drain reads until we get the matching reply
      or timeout — silently discard replies meant for the host.
    - Carry forward the last known good state for any field we fail to refresh.
    - Track consecutive misses and only report an error after several in a row.
    """

    MAX_RETRIES_PER_CMD = 3
    READ_TIMEOUT_MS = 120
    MISS_THRESHOLD = 8  # consecutive full-poll misses before showing error

    def __init__(self):
        try:
            import hid
        except ImportError:
            print("ERROR: hidapi not installed. Run: pip install hidapi", file=sys.stderr)
            sys.exit(1)
        self._hid = hid
        self._device = None
        self._last_good = PicoState()
        self._consecutive_misses = 0

    def _find_path(self):
        devices = self._hid.enumerate(SPARK_VID, SPARK_PID)
        matches = [
            d for d in devices
            if d.get("usage_page") == RAW_USAGE_PAGE and d.get("usage") == RAW_USAGE_ID
        ]
        if matches:
            return matches[0]["path"]
        if devices:
            return devices[0]["path"]
        return None

    def _open(self):
        if self._device is not None:
            return True
        path = self._find_path()
        if path is None:
            return False
        try:
            self._device = self._hid.device()
            self._device.open_path(path)
            self._device.set_nonblocking(False)
            return True
        except Exception:
            self._device = None
            return False

    def _close(self):
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def _write(self, report):
        payload = bytes([RAW_REPORT_ID]) + report
        self._device.write(payload)

    def _read(self, timeout_ms=None):
        if timeout_ms is None:
            timeout_ms = self.READ_TIMEOUT_MS
        data = self._device.read(REPORT_SIZE + 1, timeout_ms)
        if not data:
            return None
        report = bytes(data)
        if len(report) == REPORT_SIZE + 1 and report[0] == RAW_REPORT_ID:
            report = report[1:]
        if len(report) != REPORT_SIZE:
            return None
        return report

    def _send_and_match(self, command_byte):
        """Send a command and read replies until we get one whose first byte
        matches *command_byte*, or exhaust retries.  Returns the matching
        report or None."""
        for _ in range(self.MAX_RETRIES_PER_CMD):
            req = bytearray(REPORT_SIZE)
            req[0] = command_byte
            try:
                self._write(bytes(req))
            except Exception:
                self._close()
                return None

            # Drain up to a few reads looking for our reply
            for _ in range(4):
                reply = self._read()
                if reply is None:
                    break
                if reply[0] == command_byte:
                    return reply
                # Not ours — host app reply; discard and try again
        return None

    def poll(self) -> PicoState:
        state = PicoState()
        try:
            if not self._open():
                state.error = "device not found"
                return state
            state.connected = True

            got_info = False
            got_resp = False

            # GET_INFO
            info_reply = self._send_and_match(CMD_GET_INFO)
            if info_reply is not None:
                state.protocol_version = _u16(info_reply, 1)
                state.chunk_payload_size = info_reply[3]
                state.max_upload_bytes = _u32(info_reply, 4)
                state.max_chunk_count = _u16(info_reply, 8)
                state.capabilities = info_reply[10]
                state.upload_active = bool(info_reply[11])
                state.active_message_id = _u16(info_reply, 12)
                got_info = True
            else:
                # Carry forward last known values
                state.upload_active = self._last_good.upload_active
                state.active_message_id = self._last_good.active_message_id

            # GET_RESPONSE_INFO
            resp_reply = self._send_and_match(CMD_GET_RESPONSE_INFO)
            if resp_reply is not None:
                state.response_len = _u32(resp_reply, 1)
                state.response_chunk_count = _u16(resp_reply, 5)
                flags = resp_reply[7]
                state.response_complete = bool(flags & RESPONSE_FLAG_COMPLETE)
                state.response_active = bool(flags & RESPONSE_FLAG_ACTIVE)
                got_resp = True
            else:
                state.response_len = self._last_good.response_len
                state.response_chunk_count = self._last_good.response_chunk_count
                state.response_complete = self._last_good.response_complete
                state.response_active = self._last_good.response_active

            if got_info and got_resp:
                self._consecutive_misses = 0
                self._last_good = state
            elif got_info or got_resp:
                self._consecutive_misses = 0
                self._last_good = state
                which = "GET_RESPONSE_INFO" if not got_resp else "GET_INFO"
                state.error = f"(stale {which} — host app contention)"
            else:
                self._consecutive_misses += 1
                if self._consecutive_misses >= self.MISS_THRESHOLD:
                    state.error = f"HID contention — {self._consecutive_misses} consecutive misses"
                else:
                    state.error = "(missed — host app contention, using cached)"

        except Exception as exc:
            self._close()
            state.error = f"{type(exc).__name__}: {exc}"

        return state


# ---------------------------------------------------------------------------
# Jetson bridge log tailer (SSH)
# ---------------------------------------------------------------------------

class JetsonLogTailer:
    """Tails the Jetson bridge log via SSH in a background thread."""

    def __init__(self, host, user, log_path, max_lines=8):
        self._host = host
        self._user = user
        self._log_path = log_path
        self._lines = deque(maxlen=max_lines)
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._process = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._process is not None:
            try:
                self._process.kill()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)

    def get_lines(self):
        with self._lock:
            return list(self._lines)

    def _run(self):
        target = f"{self._user}@{self._host}"
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "ServerAliveInterval=10",
            target,
            f"tail -n 5 -f {self._log_path}",
        ]
        while self._running:
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=1,
                    text=True,
                )
                for line in self._process.stdout:
                    if not self._running:
                        break
                    stripped = line.rstrip()
                    if stripped:
                        with self._lock:
                            self._lines.append(stripped)
                self._process.wait()
            except Exception:
                pass
            if self._running:
                time.sleep(2)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def format_state(state: PicoState, jetson_lines: list, elapsed: float) -> str:
    """Build a multi-line dashboard string."""
    lines = []
    lines.append(f"{'=' * 72}")
    lines.append(f" SPARK Pico Monitor  |  {time.strftime('%H:%M:%S')}  |  uptime {elapsed:.0f}s")
    lines.append(f"{'=' * 72}")

    if not state.connected:
        lines.append(f"  PICO:  DISCONNECTED  ({state.error})")
        lines.append("")
    else:
        # Upload state
        upload_label = "ACTIVE" if state.upload_active else "idle"
        lines.append(f"  PICO UPLOAD:     {upload_label:<10}  msg_id={state.active_message_id}")

        # Response state — this is the key indicator
        if state.response_active:
            resp_label = "STREAMING"
        elif state.response_complete:
            resp_label = "COMPLETE"
        elif state.response_len > 0:
            resp_label = "PARTIAL"
        else:
            resp_label = "empty"

        lines.append(
            f"  PICO RESPONSE:   {resp_label:<10}  "
            f"len={state.response_len}  chunks={state.response_chunk_count}  "
            f"complete={state.response_complete}  active={state.response_active}"
        )

        if state.error:
            lines.append(f"  PICO ERROR:      {state.error}")

        lines.append("")

    # Jetson bridge log
    lines.append(f"  JETSON BRIDGE LOG (last {len(jetson_lines)} lines):")
    if jetson_lines:
        for jl in jetson_lines:
            # Truncate long lines for readability
            display = jl if len(jl) <= 90 else jl[:87] + "..."
            lines.append(f"    {display}")
    else:
        lines.append("    (no log lines yet)")

    lines.append(f"{'=' * 72}")
    return "\n".join(lines)


def clear_screen():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def run_monitor(poll_ms, jetson_host, jetson_user, jetson_log_path, use_jetson):
    poller = HIDPoller()
    tailer = None

    if use_jetson:
        tailer = JetsonLogTailer(jetson_host, jetson_user, jetson_log_path)
        tailer.start()

    poll_interval = poll_ms / 1000.0
    start_time = time.monotonic()

    # Track state transitions for logging
    prev_response_len = -1
    prev_response_active = None
    prev_response_complete = None
    prev_upload_active = None

    event_log = deque(maxlen=20)

    print("SPARK Pico Monitor starting... (Ctrl+C to stop)")
    print(f"  Poll interval: {poll_ms}ms")
    print(f"  Jetson SSH: {'enabled' if use_jetson else 'disabled'}")
    print()

    try:
        while True:
            state = poller.poll()
            elapsed = time.monotonic() - start_time
            jetson_lines = tailer.get_lines() if tailer else []

            # Detect state transitions and log them
            ts = time.strftime("%H:%M:%S")
            if state.connected:
                if prev_upload_active is not None and state.upload_active != prev_upload_active:
                    if state.upload_active:
                        event_log.append(f"[{ts}] UPLOAD started  msg_id={state.active_message_id}")
                    else:
                        event_log.append(f"[{ts}] UPLOAD ended")

                if prev_response_active is not None and state.response_active != prev_response_active:
                    if state.response_active:
                        event_log.append(f"[{ts}] RESPONSE streaming started")
                    else:
                        event_log.append(f"[{ts}] RESPONSE streaming stopped")

                if prev_response_complete is not None and state.response_complete != prev_response_complete:
                    if state.response_complete:
                        event_log.append(
                            f"[{ts}] RESPONSE complete  len={state.response_len}"
                        )

                if state.response_len != prev_response_len and state.response_len > 0:
                    event_log.append(f"[{ts}] RESPONSE len changed: {prev_response_len} -> {state.response_len}")

                prev_upload_active = state.upload_active
                prev_response_active = state.response_active
                prev_response_complete = state.response_complete
                prev_response_len = state.response_len

            # Render
            clear_screen()
            print(format_state(state, jetson_lines, elapsed))

            if event_log:
                print("\n  STATE TRANSITIONS:")
                for ev in event_log:
                    print(f"    {ev}")

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        if tailer:
            tailer.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SPARK Pico real-time status monitor")
    parser.add_argument(
        "--poll-ms", type=int, default=200,
        help="HID poll interval in milliseconds (default: 200)",
    )
    parser.add_argument(
        "--jetson-host", default="192.168.55.1",
        help="Jetson SSH host (default: 192.168.55.1)",
    )
    parser.add_argument(
        "--jetson-user", default="sidac",
        help="Jetson SSH user (default: sidac)",
    )
    parser.add_argument(
        "--jetson-log",
        default="/mnt/usb_drive/demo/pico_bridge/bridge.log",
        help="Remote path to bridge.log on Jetson",
    )
    parser.add_argument(
        "--no-jetson", action="store_true",
        help="Disable Jetson SSH log tailing",
    )
    args = parser.parse_args()

    run_monitor(
        poll_ms=args.poll_ms,
        jetson_host=args.jetson_host,
        jetson_user=args.jetson_user,
        jetson_log_path=args.jetson_log,
        use_jetson=not args.no_jetson,
    )


if __name__ == "__main__":
    main()
