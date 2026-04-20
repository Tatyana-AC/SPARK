"""
Diagnose and fix Jetson bridge: check process, deploy protocol.py, restart if needed.
"""
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import paramiko

JETSON_HOST = "192.168.55.1"
JETSON_USER = "sidac"
JETSON_PASS = "chengsida"
BRIDGE_DIR = None  # will be auto-detected


def ssh_exec(ssh, cmd, timeout=10):
    """Execute command over SSH and return stdout, stderr, exit_code."""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err, exit_code


def main():
    print("Connecting to Jetson...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(JETSON_HOST, username=JETSON_USER, password=JETSON_PASS, timeout=10)
    print("Connected!")

    # 0. Find bridge directory
    global BRIDGE_DIR
    candidates = [
        "/mnt/usb_drive/demo/pico_bridge",
        "/home/sidac/demo/pico_bridge",
        "/home/jetson/demo/pico_bridge",
    ]
    for c in candidates:
        out, _, rc = ssh_exec(ssh, f"test -d '{c}' && echo yes || echo no")
        if out == "yes":
            BRIDGE_DIR = c
            break
    if BRIDGE_DIR is None:
        # Try to find it
        out, _, _ = ssh_exec(ssh, "find / -name pico_llm_bridge.py -type f 2>/dev/null | head -3")
        print(f"Searching for bridge: {out}")
        if out:
            BRIDGE_DIR = os.path.dirname(out.split('\n')[0])
    
    if BRIDGE_DIR is None:
        print("ERROR: Cannot find bridge directory on Jetson!")
        ssh.close()
        return 1
    print(f"Bridge directory: {BRIDGE_DIR}")

    # 1. Check if bridge is running
    print("\n--- Bridge Process Status ---")
    out, err, rc = ssh_exec(ssh, "pgrep -af 'pico_llm_bridge.py'")
    if out:
        print(f"Bridge is running:\n  {out}")
    else:
        print("Bridge is NOT running!")

    # 2. Check if llama-server is running
    print("\n--- LLM Server Status ---")
    out, err, rc = ssh_exec(ssh, "pgrep -af 'llama-server'")
    if out:
        print(f"llama-server is running:\n  {out}")
    else:
        print("llama-server is NOT running!")

    # 3. Check protocol.py status
    print("\n--- Protocol Module Status ---")
    out, err, rc = ssh_exec(ssh, f"wc -c {BRIDGE_DIR}/protocol.py")
    print(f"protocol.py size: {out}")

    out, err, rc = ssh_exec(ssh, f"ls -la {BRIDGE_DIR}/__pycache__/protocol*.pyc 2>/dev/null || echo 'no cached .pyc'")
    print(f"Cached .pyc: {out}")

    # 4. Check if core/ module exists
    out, err, rc = ssh_exec(ssh, f"ls -la {BRIDGE_DIR}/core/ 2>/dev/null || echo 'no core/ directory'")
    print(f"core/ directory: {out}")

    # 5. Deploy the correct protocol.py from our host
    print("\n--- Deploying protocol.py ---")
    local_protocol = REPO_ROOT / "core" / "protocol.py"
    if not local_protocol.exists():
        print(f"ERROR: Cannot find local protocol.py at {local_protocol}")
        ssh.close()
        return 1

    sftp = ssh.open_sftp()
    remote_protocol = f"{BRIDGE_DIR}/protocol.py"
    sftp.put(str(local_protocol), remote_protocol)
    print(f"Deployed {local_protocol} -> {remote_protocol}")

    # Verify
    out, err, rc = ssh_exec(ssh, f"wc -c {remote_protocol}")
    print(f"New protocol.py size: {out}")

    # 6. Remove stale .pyc cache so Python loads the fresh source
    print("\n--- Clearing __pycache__ ---")
    out, err, rc = ssh_exec(ssh, f"rm -f {BRIDGE_DIR}/__pycache__/protocol*.pyc")
    print(f"Cleared protocol .pyc files")

    # 7. Restart the bridge
    print("\n--- Restarting Bridge ---")
    out, err, rc = ssh_exec(ssh, "pkill -f 'pico_llm_bridge.py' || true")
    print("Killed existing bridge process")
    time.sleep(2)

    # Start bridge using the same approach as setup_spark.ps1
    out, err, rc = ssh_exec(ssh, f"""
        sudo chmod 666 /dev/ttyTHS0 && \
        cd {BRIDGE_DIR} && \
        nohup bash -lc "cd '{BRIDGE_DIR}' && exec ./run_bridge.sh --verbose" >bridge.log 2>&1 < /dev/null &
    """)
    print(f"Started bridge: stdout={out}, stderr={err}, rc={rc}")

    time.sleep(4)

    # 8. Verify bridge is running
    print("\n--- Verifying ---")
    out, err, rc = ssh_exec(ssh, "pgrep -af 'pico_llm_bridge.py'")
    if out:
        print(f"Bridge is running:\n  {out}")
    else:
        print("WARNING: Bridge may not have started!")

    # Check new bridge log
    out, err, rc = ssh_exec(ssh, f"tail -20 {BRIDGE_DIR}/bridge.log")
    print(f"Bridge log tail:\n{out}")

    # 9. Check DB last session
    print("\n--- DB Status ---")
    out, err, rc = ssh_exec(ssh, f"""python3 -c "
import sqlite3, json
conn = sqlite3.connect('{BRIDGE_DIR}/jetson_spark.db')
conn.row_factory = sqlite3.Row
cur = conn.execute('SELECT * FROM sessions ORDER BY id DESC LIMIT 3')
for row in cur:
    print(dict(row))
conn.close()
" """)
    print(f"Last 3 DB sessions:\n{out}")
    if err:
        print(f"DB errors: {err}")

    sftp.close()
    ssh.close()
    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
