"""
Diagnostic: Test if Pico relays CDC serial data to Jetson UART.

This script:
1. Starts a UART listener on the Jetson via SSH
2. Sends a CONTEXT_NEW packet from host to Pico CDC (COM11)
3. Checks if the packet arrives on the Jetson UART

Prerequisite: Bridge must be stopped (this script does NOT kill it).
"""
import paramiko
import serial
import time
import sys
import os
import json
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from core.protocol import build_context_new

JETSON_HOST = "192.168.55.1"
JETSON_USER = "sidac"
JETSON_PASS = "chengsida"
PICO_CDC_PORT = "COM11"
PICO_BAUD = 115200

JETSON_LISTENER_SCRIPT = r"""
import serial, time, json
ser = serial.Serial('/dev/ttyTHS0', 115200, timeout=0.5)
start = time.time()
total = 0
hex_chunks = []
while time.time() - start < 8:
    data = ser.read(256)
    if data:
        total += len(data)
        hex_chunks.append(data.hex())
        elapsed = time.time() - start
ser.close()
result = {
    "total_bytes": total,
    "num_chunks": len(hex_chunks),
    "hex_chunks": hex_chunks,
}
print(json.dumps(result))
"""


def main():
    # Connect SSH
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(JETSON_HOST, username=JETSON_USER, password=JETSON_PASS, timeout=5)
    print("[OK] SSH connected")

    # Verify bridge is NOT running
    stdin, stdout, stderr = ssh.exec_command(
        "ps aux | grep pico_llm_bridge | grep -v grep"
    )
    procs = stdout.read().decode().strip()
    if procs:
        print(f"[WARN] Bridge is running! Output may be consumed by it.")
        print(f"  {procs}")
    else:
        print("[OK] Bridge is not running")

    # Start listener (script already deployed to /tmp/uart_listener.py)
    print("[...] Starting UART listener on Jetson (8 sec window)...")
    cmd = "python3 /tmp/uart_listener.py"
    stdin_j, stdout_j, stderr_j = ssh.exec_command(cmd)

    # Wait for listener to start
    time.sleep(1.5)

    # Build test packet
    payload = {
        "app_name": "RelayTest4",
        "window_title": "CDC-to-UART Relay Test",
        "process_name": "relay_test.exe",
        "pid": 66666,
        "source": "full_window",
        "tab_title": None,
        "url": None,
        "text": "This packet should arrive on the Jetson UART if the Pico relay works.",
        "timestamp": time.time(),
    }
    packet = build_context_new(payload)
    print(f"[OK] Built CONTEXT_NEW packet: {len(packet)} bytes")
    print(f"     First 20 bytes hex: {packet[:20].hex()}")

    # Send to Pico CDC
    try:
        ser = serial.Serial(PICO_CDC_PORT, PICO_BAUD, timeout=0.5)
        print(f"[OK] Opened {PICO_CDC_PORT}")
    except Exception as e:
        print(f"[FAIL] Cannot open {PICO_CDC_PORT}: {e}")
        ssh.close()
        return 1

    written = ser.write(packet)
    ser.flush()
    print(f"[OK] Sent {written} bytes to Pico CDC")

    # Read back any data from Pico
    time.sleep(0.5)
    back = ser.read(4096)
    if back:
        print(f"[INFO] Got {len(back)} bytes back from Pico: {back[:100].hex()}")
    else:
        print("[INFO] No data back from Pico CDC")
    ser.close()

    # Wait for Jetson listener to finish
    print("[...] Waiting for Jetson UART listener to complete...")
    raw_out = stdout_j.read().decode("utf-8", errors="replace")
    raw_err = stderr_j.read().decode("utf-8", errors="replace")

    if raw_err.strip():
        print(f"[WARN] Jetson stderr: {raw_err[:300]}")

    # Parse result
    try:
        result = json.loads(raw_out.strip())
    except (json.JSONDecodeError, ValueError):
        print(f"[FAIL] Could not parse Jetson output: {repr(raw_out[:300])}")
        ssh.close()
        return 1

    total = result["total_bytes"]
    num_chunks = result["num_chunks"]
    hex_chunks = result["hex_chunks"]

    print(f"\n=== RESULT ===")
    print(f"Jetson UART received: {total} bytes in {num_chunks} chunks")

    if total == 0:
        print("[FAIL] NO DATA arrived on Jetson UART!")
        print("  -> The Pico is NOT relaying CDC data to UART")
        print("  -> Possible causes:")
        print("     1. usb_cdc.data.in_waiting always returns 0")
        print("     2. _uart.write() silently fails (OSError swallowed)")
        print("     3. UART TX pin hardware issue")
    else:
        combined = bytes.fromhex("".join(hex_chunks))
        sp_count = combined.count(b"SP")
        print(f"SP magic markers found: {sp_count}")
        print(f"First 100 bytes hex: {combined[:100].hex()}")

        # Check if our packet is in there
        if packet[:6] in combined:
            print("[SUCCESS] Our CONTEXT_NEW packet header found in UART data!")
        elif b"SP" in combined:
            print("[PARTIAL] SP magic found but full header not matched")
        else:
            print("[FAIL] Data received but no valid SPARK protocol packets")
            print(f"  Data as text: {repr(combined[:200].decode('utf-8', errors='replace'))}")

    ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
