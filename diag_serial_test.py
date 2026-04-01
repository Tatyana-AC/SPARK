"""
Diagnostic: send a single CONTEXT_NEW packet to the Pico CDC serial port
and check if the Jetson bridge picks it up.

Usage: python diag_serial_test.py
"""
import sys
import time
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.protocol import build_context_new, _crc8, MAGIC, HEADER_SIZE, FOOTER_SIZE
import serial
from serial.tools import list_ports

SPARK_VID = 0xC4C4
SPARK_PID = 0x5350


def find_pico_cdc():
    for p in list_ports.comports():
        if p.vid == SPARK_VID and p.pid == SPARK_PID:
            return p.device
    return None


def main():
    port = find_pico_cdc()
    if not port:
        print("ERROR: Pico CDC port not found")
        return 1

    print(f"Found Pico CDC on {port}")

    # Build a small test context packet
    payload = {
        "app_name": "DiagTest",
        "window_title": "Serial Diag Test Window",
        "process_name": "diag_test.exe",
        "pid": 99999,
        "source": "full_window",
        "tab_title": None,
        "url": None,
        "text": "This is a diagnostic test to verify the CDC->UART->Jetson pipeline.",
        "timestamp": time.time(),
    }

    packet = build_context_new(payload)
    print(f"Built CONTEXT_NEW packet: {len(packet)} bytes")
    print(f"  Header bytes: {packet[:6].hex()}")
    print(f"  Magic: {packet[:2]}")
    print(f"  Type: 0x{packet[2]:02x}")
    import struct
    pkt_len = struct.unpack_from('<H', packet, 3)[0]
    print(f"  Payload length: {pkt_len}")
    print(f"  CRC: 0x{packet[-1]:02x}")

    # Verify our own packet parsing
    from core.protocol import PacketParser
    parsed = []
    def on_pkt(pkt):
        parsed.append(pkt)
    p = PacketParser(on_packet=on_pkt)
    p.feed(packet)
    if parsed:
        print(f"  Self-test: parsed OK, type={parsed[0].get('type')}, app={parsed[0].get('app_name')}")
    else:
        print("  Self-test: FAILED to parse our own packet!")
        return 1

    # Now send it over serial
    try:
        ser = serial.Serial(port, 115200, timeout=0.5)
        print(f"Opened {port} at 115200 baud")
    except Exception as e:
        print(f"ERROR opening serial: {e}")
        return 1

    # Check bridge.log line count before
    bridge_log = r"Z:\demo\pico_bridge\bridge.log"
    try:
        with open(bridge_log, 'r') as f:
            before_lines = sum(1 for _ in f)
        print(f"Bridge log has {before_lines} lines before send")
    except Exception as e:
        print(f"WARNING: Cannot read bridge log: {e}")
        before_lines = None

    # Send the packet
    print(f"Sending {len(packet)} bytes...")
    written = ser.write(packet)
    ser.flush()
    print(f"Wrote {written} bytes")

    # Wait for the Jetson bridge to process
    print("Waiting 3 seconds for Jetson bridge to process...")
    time.sleep(3)

    # Check bridge.log for new context events
    if before_lines is not None:
        try:
            with open(bridge_log, 'r') as f:
                all_lines = f.readlines()
            after_lines = len(all_lines)
            new_lines = all_lines[before_lines:]
            print(f"Bridge log has {after_lines} lines after send ({after_lines - before_lines} new)")
            context_events = [l for l in new_lines if 'CONTEXT' in l or 'context' in l.lower() and 'session' in l.lower()]
            if context_events:
                print("SUCCESS: Jetson bridge decoded our context packet!")
                for l in context_events:
                    print(f"  {l.strip()}")
            else:
                # Show last few new lines to see what happened
                print("PROBLEM: No context events in new log lines.")
                print("Last 10 new lines:")
                for l in new_lines[-10:]:
                    print(f"  {l.strip()}")
        except Exception as e:
            print(f"WARNING: Cannot read bridge log: {e}")

    # Also read back any data from the port
    time.sleep(0.5)
    response = ser.read(1024)
    if response:
        print(f"Received {len(response)} bytes back from Pico: {response[:50].hex()}...")
    else:
        print("No data received back from Pico")

    ser.close()
    print("Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
