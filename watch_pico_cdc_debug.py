import argparse
import sys
import time

import serial
from serial.tools import list_ports

from pico.protocol import PKT_DEBUG, PacketParser


PICO_VID = 0xC4C4
PICO_PID = 0x5350


def select_port(ports, explicit_port=None):
    if explicit_port:
        return explicit_port

    matches = [port.device for port in ports if port.vid == PICO_VID and port.pid == PICO_PID]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError(f"Multiple Pico CDC ports found: {', '.join(matches)}")
    raise RuntimeError("Could not find Pico CDC port (VID 0xC4C4 PID 0x5350)")


def build_parser():
    parser = argparse.ArgumentParser(description="Watch Pico CDC debug packets")
    parser.add_argument("--port", help="Override auto-detected Pico CDC port")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.0,
        help="Stop after N seconds; default 0 runs until Ctrl+C",
    )
    parser.add_argument(
        "--all-packets",
        action="store_true",
        help="Print non-debug packets too",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    port = select_port(list(list_ports.comports()), explicit_port=args.port)
    state = {"packet_count": 0, "raw_bytes": 0}

    def on_packet(pkt):
        state["packet_count"] += 1
        ts = time.strftime("%H:%M:%S")
        if pkt.get("type") == PKT_DEBUG:
            print(f"[{ts}] DEBUG {pkt.get('msg', '')}", flush=True)
            return
        if args.all_packets:
            print(f"[{ts}] PKT {pkt}", flush=True)

    packet_parser = PacketParser(on_packet=on_packet)
    deadline = time.time() + args.seconds if args.seconds > 0 else None

    print(f"Monitoring {port} at {args.baud} baud. Press Ctrl+C to stop.", flush=True)
    try:
        with serial.Serial(port, args.baud, timeout=0.1) as handle:
            while True:
                if deadline is not None and time.time() >= deadline:
                    break
                chunk = handle.read(256)
                if not chunk:
                    continue
                state["raw_bytes"] += len(chunk)
                packet_parser.feed(chunk)
    except KeyboardInterrupt:
        print("Stopped by user.", flush=True)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        f"Finished. packets={state['packet_count']} raw_bytes={state['raw_bytes']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
