#!/usr/bin/env bash

set -euo pipefail

shopt -s nullglob

JETSON_HOST="192.168.55.1"
JETSON_USER="sidac"
JETSON_REMOTE_PATH="/mnt/usb_drive"
JETSON_SSH_CONNECT_TIMEOUT_SECONDS=10
BRIDGE_SETTLE_SECONDS=10
SKIP_SMOKE_TEST=0
SKIP_APP_LAUNCH=0
HEADLESS_APP_LAUNCH=0
DRY_RUN=0
REPO_PYTHON=""
LAST_SSH_CHECK_ERROR=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

JETSON_BRIDGE_DEPLOY_FILES=(
  "db_manager.py"
  "pico_llm_bridge.py"
  "protocol.py"
  "receiver.py"
  "requirements.txt"
  "run_bridge.sh"
)

write_section() {
  local title="$1"
  printf "\n== %s ==\n" "$title"
}

write_status() {
  local label="$1"
  local value="$2"
  printf "%-24s %s\n" "${label}:" "$value"
}

die() {
  printf "ERROR: %s\n" "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: setup_spark_macos.sh [options]

Options:
  --jetson-host <host>
  --jetson-user <user>
  --jetson-remote-path <path>
  --jetson-ssh-connect-timeout-seconds <seconds>
  --bridge-settle-seconds <seconds>
  --skip-smoke-test
  --skip-app-launch
  --headless-app-launch
  --dry-run
  -h, --help
EOF
}

quote_args() {
  local quoted=()
  local part
  for part in "$@"; do
    printf -v part '%q' "$part"
    quoted+=("$part")
  done
  printf '%s' "${quoted[*]}"
}

print_dry_run() {
  write_status "DRY-RUN" "$(quote_args "$@")"
}

run_cmd() {
  if (( DRY_RUN )); then
    print_dry_run "$@"
    return 0
  fi
  "$@"
}

python_run_with_timeout() {
  local timeout_seconds="$1"
  shift
  if (( DRY_RUN )); then
    print_dry_run "$@"
    return 0
  fi

  python3 - "$timeout_seconds" "$@" <<'PY'
import subprocess
import sys

timeout = int(sys.argv[1])
command = sys.argv[2:]

try:
    completed = subprocess.run(command, timeout=timeout, check=False)
except subprocess.TimeoutExpired:
    print(f"Timed out after {timeout} second(s): {' '.join(command)}", file=sys.stderr)
    raise SystemExit(124)

raise SystemExit(completed.returncode)
PY
}

apple_script_escape() {
  python3 - "$1" <<'PY'
import sys

print(sys.argv[1].replace("\\", "\\\\").replace('"', '\\"'))
PY
}

git_common_repo_root() {
  local common_git_dir
  if ! common_git_dir="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    return 1
  fi

  common_git_dir="${common_git_dir//$'\r'/}"
  common_git_dir="${common_git_dir//$'\n'/}"
  if [[ -z "$common_git_dir" ]]; then
    return 1
  fi

  dirname "$common_git_dir"
}

repo_virtualenv_root() {
  local common_root
  if common_root="$(git_common_repo_root)"; then
    printf '%s\n' "$common_root"
    return 0
  fi

  printf '%s\n' "$REPO_ROOT"
}

repo_virtualenv_python_path() {
  printf '%s/.venv/bin/python\n' "$(repo_virtualenv_root)"
}

requirements_stamp_path() {
  printf '%s/.venv/requirements.sha256\n' "$(repo_virtualenv_root)"
}

requirements_fingerprint() {
  local requirements_path="$REPO_ROOT/requirements.txt"
  [[ -f "$requirements_path" ]] || die "Could not find requirements.txt at $requirements_path."
  shasum -a 256 "$requirements_path" | awk '{print $1}'
}

ensure_repo_virtualenv() {
  local venv_root
  local venv_python
  local bootstrap_python

  venv_root="$(repo_virtualenv_root)"
  venv_python="$(repo_virtualenv_python_path)"

  if [[ -x "$venv_python" ]]; then
    write_status "Python env" "Using existing virtualenv at $venv_root/.venv"
    REPO_PYTHON="$venv_python"
    return 0
  fi

  bootstrap_python="$(command -v python3 || true)"
  [[ -n "$bootstrap_python" ]] || die "Could not find a bootstrap Python interpreter. Install Python 3 and ensure python3 is on PATH."

  write_status "Python env" "Creating virtualenv at $venv_root/.venv"
  python_run_with_timeout 180 "$bootstrap_python" -m venv "$venv_root/.venv"
  REPO_PYTHON="$venv_python"
}

test_repo_requirements_current() {
  local python_exe="$1"
  local stamp_path
  local current_fingerprint
  local recorded_fingerprint

  stamp_path="$(requirements_stamp_path)"
  [[ -f "$stamp_path" ]] || return 1

  current_fingerprint="$(requirements_fingerprint)"
  recorded_fingerprint="$(tr -d '\r\n' <"$stamp_path")"
  [[ "$recorded_fingerprint" == "$current_fingerprint" ]] || return 1

  "$python_exe" - <<'PY' >/dev/null 2>&1
import AppKit  # noqa: F401
import PyQt6  # noqa: F401
import Quartz  # noqa: F401
import hid  # noqa: F401
import requests  # noqa: F401
import serial  # noqa: F401
PY
}

ensure_repo_requirements_installed() {
  local python_exe="$1"
  local requirements_path="$REPO_ROOT/requirements.txt"
  local stamp_path
  local fingerprint

  if test_repo_requirements_current "$python_exe"; then
    write_status "Python deps" "requirements.txt already satisfied"
    return 0
  fi

  write_status "Python deps" "Installing requirements.txt into the repo virtualenv"
  python_run_with_timeout 300 "$python_exe" -m pip install --upgrade pip
  python_run_with_timeout 900 "$python_exe" -m pip install -r "$requirements_path"

  stamp_path="$(requirements_stamp_path)"
  fingerprint="$(requirements_fingerprint)"
  mkdir -p "$(dirname "$stamp_path")"
  if (( DRY_RUN )); then
    write_status "Python deps" "DRY-RUN: would record requirements fingerprint at $stamp_path"
  else
    printf '%s' "$fingerprint" >"$stamp_path"
  fi
}

initialize_repo_python_environment() {
  ensure_repo_virtualenv
  ensure_repo_requirements_installed "$REPO_PYTHON"
}

check_accessibility_permissions() {
  local python_exe="$1"
  local rc

  if (( DRY_RUN )); then
    write_status "Accessibility" "DRY-RUN: would verify AX permissions for $python_exe"
    return 0
  fi

  set +e
  "$python_exe" - <<'PY'
import sys

try:
    from ApplicationServices import AXIsProcessTrusted
except Exception:
    try:
        import Quartz
    except Exception as exc:
        print(f"IMPORT_ERROR:{exc}")
        raise SystemExit(2)
    AXIsProcessTrusted = getattr(Quartz, "AXIsProcessTrusted", None)
    if AXIsProcessTrusted is None:
        print("IMPORT_ERROR:AXIsProcessTrusted is unavailable")
        raise SystemExit(2)

raise SystemExit(0 if AXIsProcessTrusted() else 1)
PY
  rc=$?
  set -e

  case "$rc" in
    0)
      write_status "Accessibility" "Accessibility permissions already granted"
      ;;
    1)
      open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" >/dev/null 2>&1 || true
      die "Accessibility permission is required on macOS. Add $python_exe in System Settings -> Privacy & Security -> Accessibility, then rerun setup_spark_macos.sh."
      ;;
    2)
      die "Could not import macOS accessibility frameworks from $python_exe. Re-run after requirements finish installing."
      ;;
    *)
      die "Unexpected accessibility check failure (exit code $rc)."
      ;;
  esac
}

ssh_base_args() {
  printf '%s\n' "-o" "BatchMode=yes" "-o" "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS"
}

test_jetson_ssh_batch_mode() {
  local target="$JETSON_USER@$JETSON_HOST"
  local output
  local rc
  if (( DRY_RUN )); then
    print_dry_run ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" "$target" "exit 0"
    return 0
  fi

  set +e
  output="$(ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" "$target" "exit 0" 2>&1)"
  rc=$?
  set -e

  LAST_SSH_CHECK_ERROR="$output"
  return "$rc"
}

assert_host_tooling_ready() {
  command -v ssh >/dev/null 2>&1 || die "OpenSSH client was not found on PATH."
  command -v rsync >/dev/null 2>&1 || die "rsync was not found on PATH."

  if (( !SKIP_APP_LAUNCH && !HEADLESS_APP_LAUNCH )); then
    command -v osascript >/dev/null 2>&1 || die "osascript was not found on PATH."
  fi

  if ! test_jetson_ssh_batch_mode; then
    if [[ -n "$LAST_SSH_CHECK_ERROR" ]]; then
      die "Batch-mode SSH authentication to $JETSON_USER@$JETSON_HOST failed: $LAST_SSH_CHECK_ERROR"
    fi
    die "Batch-mode SSH authentication to $JETSON_USER@$JETSON_HOST failed. Configure passwordless SSH before running setup_spark_macos.sh."
  fi

  write_status "SSH tooling" "ssh, rsync, and batch-mode auth are available"
}

get_pico_mount() {
  local candidate
  local matches=()

  if (( DRY_RUN )); then
    printf '%s\n' "/Volumes/CIRCUITPY"
    return 0
  fi

  if [[ -d "/Volumes/CIRCUITPY" ]]; then
    printf '%s\n' "/Volumes/CIRCUITPY"
    return 0
  fi

  for candidate in /Volumes/*; do
    [[ -d "$candidate" ]] || continue
    if [[ "$(basename "$candidate")" == "CIRCUITPY" ]]; then
      matches+=("$candidate")
      continue
    fi
    if [[ -f "$candidate/boot.py" && -f "$candidate/code.py" ]]; then
      matches+=("$candidate")
    fi
  done

  if (( ${#matches[@]} == 0 )); then
    return 1
  fi

  printf '%s\n' "${matches[0]}"
}

assert_pico_writable_mount() {
  local pico_mount="$1"

  if (( DRY_RUN )); then
    write_status "Pico mount mode" "DRY-RUN: would verify $pico_mount is mounted read-write"
    return 0
  fi

  local disk_info
  disk_info="$(diskutil info "$pico_mount" 2>/dev/null)" || die "Could not inspect Pico volume at $pico_mount."

  local volume_read_only
  local media_read_only
  volume_read_only="$(printf '%s\n' "$disk_info" | awk -F: '/Volume Read-Only/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')"
  media_read_only="$(printf '%s\n' "$disk_info" | awk -F: '/Media Read-Only/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')"

  if [[ "$volume_read_only" == Yes* || "$media_read_only" == Yes* ]]; then
    die "Pico volume $pico_mount is mounted read-only. Reconnect/reset the Pico so CIRCUITPY remounts read-write, then rerun setup_spark_macos.sh."
  fi

  write_status "Pico mount mode" "read-write"
}

test_jetson_remote_directory() {
  local remote_directory="$1"
  local target="$JETSON_USER@$JETSON_HOST"
  if (( DRY_RUN )); then
    print_dry_run ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" "$target" "test -d '$remote_directory'"
    return 0
  fi

  ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" "$target" "test -d '$remote_directory'" >/dev/null 2>&1
}

run_jetson_ssh_script() {
  local script_text="$1"
  local target="$JETSON_USER@$JETSON_HOST"

  if (( DRY_RUN )); then
    print_dry_run ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" "$target" "bash -s <<'REMOTE_SCRIPT' ... REMOTE_SCRIPT"
    return 0
  fi

  printf '%s\n' "$script_text" | ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" "$target" "bash -s"
}

sync_jetson_time() {
  local host_epoch
  local host_time_display
  local remote_script
  local output
  local rc
  local rtc_synced
  local rtc_failed

  host_epoch="$(date +%s)"
  host_time_display="$(date '+%Y-%m-%d %H:%M:%S %Z')"

  if (( DRY_RUN )); then
    write_status "Jetson time" "DRY-RUN: would sync to $host_time_display via sudo date -s @$host_epoch and hwclock --systohc"
    return 0
  fi

  remote_script=$(cat <<EOF
set -euo pipefail

if ! command -v sudo >/dev/null 2>&1; then
  echo "SUDO_MISSING"
  exit 1
fi

if ! sudo -n true >/dev/null 2>&1; then
  echo "SUDO_NOPASSWD_REQUIRED"
  exit 1
fi

sudo -n date -s "@$host_epoch" >/dev/null

rtc_synced=0
rtc_failed=0
for rtc in /dev/rtc /dev/rtc0 /dev/rtc1 /dev/rtc2 /dev/rtc3; do
  [ -e "\$rtc" ] || continue
  if sudo -n hwclock --rtc="\$rtc" --systohc >/dev/null 2>&1; then
    rtc_synced=\$((rtc_synced + 1))
  else
    rtc_failed=\$((rtc_failed + 1))
  fi
done

printf 'RTC_SYNCED=%s\n' "\$rtc_synced"
printf 'RTC_FAILED=%s\n' "\$rtc_failed"
timedatectl status | sed -n '1,8p' || true
EOF
)

  set +e
  output="$(run_jetson_ssh_script "$remote_script" 2>&1)"
  rc=$?
  set -e

  if (( rc != 0 )); then
    if [[ "$output" == *"SUDO_MISSING"* ]]; then
      die "Jetson time sync requires sudo on $JETSON_USER@$JETSON_HOST, but sudo was not found."
    fi
    if [[ "$output" == *"SUDO_NOPASSWD_REQUIRED"* ]]; then
      die "Jetson time sync requires passwordless sudo on $JETSON_USER@$JETSON_HOST."
    fi
    die "Jetson time sync failed: $output"
  fi

  rtc_synced="$(printf '%s\n' "$output" | awk -F= '/^RTC_SYNCED=/ {print $2; exit}')"
  rtc_failed="$(printf '%s\n' "$output" | awk -F= '/^RTC_FAILED=/ {print $2; exit}')"
  [[ -n "$rtc_synced" ]] || rtc_synced="0"
  [[ -n "$rtc_failed" ]] || rtc_failed="0"

  write_status "Jetson time" "Synced to host time ($host_time_display)"
  write_status "Jetson RTCs" "synced $rtc_synced, failed $rtc_failed"

  if printf '%s\n' "$output" | grep -Fq "System clock synchronized: no"; then
    write_status "Jetson NTP" "active but unsynchronized"
  fi
}

assert_jetson_writable_mount() {
  local remote_script
  remote_script=$(cat <<EOF
set -euo pipefail

while IFS=' ' read -r device mountpoint fstype options rest; do
    if [ "\$mountpoint" = "$JETSON_REMOTE_PATH" ]; then
        printf '%s\n' "\$options"
        exit 0
    fi
done </proc/mounts

exit 1
EOF
)

  if (( DRY_RUN )); then
    run_jetson_ssh_script "$remote_script"
    write_status "Jetson mount mode" "DRY-RUN: would verify $JETSON_REMOTE_PATH is mounted read-write"
    return 0
  fi

  local mount_options
  mount_options="$(run_jetson_ssh_script "$remote_script" | tail -n 1)"
  [[ -n "$mount_options" ]] || die "Could not determine mount options for Jetson path $JETSON_REMOTE_PATH."
  [[ "$mount_options" == *rw* ]] || die "Jetson remote path $JETSON_REMOTE_PATH is mounted read-only ($mount_options). Repair the Jetson storage and remount it read-write before running setup_spark_macos.sh again."
  write_status "Jetson mount mode" "$mount_options"
}

deploy_pico_firmware() {
  local python_exe="$1"
  local pico_mount="$2"
  local deploy_script="$REPO_ROOT/tools/pico/deploy_to_pico.py"

  [[ -f "$deploy_script" ]] || die "Could not find Pico deploy helper at $deploy_script."

  write_status "Pico deploy" "Deploying firmware to $pico_mount"
  python_run_with_timeout 180 "$python_exe" "$deploy_script" --target "$pico_mount"
}

sync_jetson_bridge_bundle() {
  local remote_target="$JETSON_USER@$JETSON_HOST:$JETSON_REMOTE_PATH/demo/pico_bridge/"
  local remote_shell
  local command=()
  local file

  remote_shell="$(quote_args ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS")"
  command=(rsync -a --checksum -e "$remote_shell")

  for file in "${JETSON_BRIDGE_DEPLOY_FILES[@]}"; do
    command+=("$REPO_ROOT/jetson/$file")
  done
  command+=("$remote_target")

  if (( DRY_RUN )); then
    print_dry_run "${command[@]}"
  else
    "${command[@]}"
  fi

  if (( DRY_RUN )); then
    print_dry_run ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" "$JETSON_USER@$JETSON_HOST" "chmod +x '$JETSON_REMOTE_PATH/demo/pico_bridge/run_bridge.sh'"
  else
    ssh -o BatchMode=yes -o "ConnectTimeout=$JETSON_SSH_CONNECT_TIMEOUT_SECONDS" \
      "$JETSON_USER@$JETSON_HOST" \
      "chmod +x '$JETSON_REMOTE_PATH/demo/pico_bridge/run_bridge.sh'"
  fi

  write_status "Jetson deploy" "Synced ${#JETSON_BRIDGE_DEPLOY_FILES[@]} file(s) to $remote_target"
}

start_jetson_services() {
  local remote_script
  remote_script=$(cat <<EOF
set -euo pipefail

ROOT_DIR='$JETSON_REMOTE_PATH/demo'
LLAMA_DIR="\$ROOT_DIR/llama_demo"
BRIDGE_DIR="\$ROOT_DIR/pico_bridge"
SERVER_LOG="\$LLAMA_DIR/server.log"
BRIDGE_LOG="\$BRIDGE_DIR/bridge.log"
MODEL_PATH="\$LLAMA_DIR/models/Qwen3.5-2B-Q4_K_M.gguf"
BIN_PATH="\$LLAMA_DIR/llama.cpp/build/bin/llama-server"

check_server() {
python3 - <<'PY'
import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen('http://127.0.0.1:8080/v1/models', timeout=3) as response:
        print(response.read().decode('utf-8', 'ignore'))
    raise SystemExit(0)
except urllib.error.HTTPError as exc:
    print(f"HTTP {exc.code}")
    raise SystemExit(2)
except Exception as exc:
    print(type(exc).__name__, exc)
    raise SystemExit(1)
PY
}

echo "Jetson host: \$(hostname)"
echo "Jetson user: \$(whoami)"
echo "Bridge dir: \$BRIDGE_DIR"

if pgrep -af '[l]lama-server' >/dev/null 2>&1; then
    echo "llama-server status: already running"
else
    echo "llama-server status: starting"
    nohup bash -lc "cd '\$LLAMA_DIR' && exec '\$BIN_PATH' -m '\$MODEL_PATH' -c 262144 -np 1 -ngl 40 -fit off --reasoning-budget 0 --port 8080 --host 0.0.0.0" >"\$SERVER_LOG" 2>&1 < /dev/null &
fi

server_ready=0
for attempt in \$(seq 1 90); do
    set +e
    server_output=\$(check_server 2>&1)
    server_rc=\$?
    set -e
    if [ "\$server_rc" -eq 0 ]; then
        server_ready=1
        echo "llama-server endpoint: ready"
        echo "\$server_output"
        break
    fi
    if [ "\$server_rc" -eq 2 ]; then
        echo "llama-server endpoint: loading (\$attempt/90)"
    else
        echo "llama-server endpoint: waiting (\$attempt/90) - \$server_output"
    fi
    sleep 2
done

if [ "\$server_ready" -ne 1 ]; then
    echo "llama-server failed to become ready"
    tail -n 80 "\$SERVER_LOG" || true
    exit 1
fi

sudo chmod 666 /dev/ttyTHS0

BRIDGE_COUNT=\$(pgrep -fc '[p]ico_llm_bridge.py' || true)

if [ "\${BRIDGE_COUNT:-0}" -eq 1 ]; then
    echo "bridge status: already running"
elif [ "\${BRIDGE_COUNT:-0}" -gt 1 ]; then
    echo "bridge status: found \$BRIDGE_COUNT running copies; restarting"
    pkill -f '[p]ico_llm_bridge.py' || true
    sleep 2
    nohup bash -lc "cd '\$BRIDGE_DIR' && exec ./run_bridge.sh" >"\$BRIDGE_LOG" 2>&1 < /dev/null &
else
    echo "bridge status: starting"
    nohup bash -lc "cd '\$BRIDGE_DIR' && exec ./run_bridge.sh" >"\$BRIDGE_LOG" 2>&1 < /dev/null &
fi

sleep 3

if ! pgrep -af '[p]ico_llm_bridge.py' >/dev/null 2>&1; then
    echo "bridge failed to start"
    echo "bridge log tail:"
    tail -n 20 "\$BRIDGE_LOG" || true
    exit 1
fi

FINAL_BRIDGE_COUNT=\$(pgrep -fc '[p]ico_llm_bridge.py' || true)
if [ "\${FINAL_BRIDGE_COUNT:-0}" -ne 1 ]; then
    echo "bridge failed to settle to a single process (count=\$FINAL_BRIDGE_COUNT)"
    echo "process status:"
    pgrep -af '[p]ico_llm_bridge.py' || true
    exit 1
fi

echo "process status:"
pgrep -af '[l]lama-server|[p]ico_llm_bridge.py' || true
echo "bridge log tail:"
tail -n 20 "\$BRIDGE_LOG" || true
EOF
)

  run_jetson_ssh_script "$remote_script"
}

restart_jetson_bridge() {
  local remote_script
  remote_script=$(cat <<EOF
set -euo pipefail

BRIDGE_DIR="$JETSON_REMOTE_PATH/demo/pico_bridge"
BRIDGE_LOG="\$BRIDGE_DIR/bridge.log"

pkill -f '[p]ico_llm_bridge.py' || true
sleep 2
cd "\$BRIDGE_DIR"
nohup bash -lc "cd '\$BRIDGE_DIR' && exec ./run_bridge.sh" >"\$BRIDGE_LOG" 2>&1 < /dev/null &
sleep 4
BRIDGE_COUNT=\$(pgrep -fc '[p]ico_llm_bridge.py' || true)
if [ "\${BRIDGE_COUNT:-0}" -ne 1 ]; then
    echo "bridge restart failed"
    echo "process status:"
    pgrep -af '[p]ico_llm_bridge.py' || true
    echo "bridge log tail:"
    tail -n 20 "\$BRIDGE_LOG" || true
    exit 1
fi
echo "bridge restart status:"
pgrep -af '[p]ico_llm_bridge.py' || true
echo "bridge log tail:"
tail -n 20 "\$BRIDGE_LOG" || true
EOF
)

  run_jetson_ssh_script "$remote_script"
}

wait_jetson_bridge_settle() {
  local seconds="$1"
  (( seconds > 0 )) || return 0
  write_status "Bridge settle" "Waiting $seconds second(s) for UART path to stabilize"
  if (( DRY_RUN )); then
    return 0
  fi
  sleep "$seconds"
}

invoke_smoke_test() {
  local python_exe="$1"

  if (( DRY_RUN )); then
    print_dry_run "$python_exe" "-" "<smoke test python script>"
    SMOKE_TEST_OUTPUT=""
    return 0
  fi

  local output
  set +e
  output="$(
    "$python_exe" - 2>&1 <<'PY'
import json
from host_pc.raw_hid import AppCommand, SparkHIDClient, SparkProtocolError
from host_pc.summarize_stream import build_test_summary_request

client = SparkHIDClient()
updates = []

def on_update(text: str) -> None:
    if updates and updates[-1] == text:
        return
    updates.append(text)
    print(f"[smoke] streamed chars: {len(text)}")

try:
    connected = client.is_connected()
    print(json.dumps({"connected": connected}))
    if not connected:
        raise SparkProtocolError("SPARK Pico Raw HID device is not connected.")

    info = client.get_info()
    print(
        json.dumps(
            {
                "protocol_version": info.protocol_version,
                "chunk_payload_size": info.chunk_payload_size,
                "max_upload_bytes": info.max_upload_bytes,
                "max_chunk_count": info.max_chunk_count,
                "capabilities": info.capabilities,
                "upload_active": info.upload_active,
                "active_message_id": info.active_message_id,
            },
            indent=2,
        )
    )

    ping = client.ping()
    print(
        json.dumps(
            {
                "ping_ok": ping.ok,
                "ping_code": ping.code.name,
                "ping_detail": ping.detail,
            },
            indent=2,
        )
    )
    if not ping.ok:
        raise SparkProtocolError(f"Ping failed: {ping}")

    response = client.stream_round_trip_text(
        AppCommand.FEATURE_1,
        build_test_summary_request(),
        on_update=on_update,
        timeout_ms=90000,
    )
    if response.lstrip().startswith("[ERROR]"):
        raise SparkProtocolError(f"Smoke summarize returned error payload: {response}")
    print(
        json.dumps(
            {
                "smoke_ok": True,
                "update_count": len(updates),
                "response_preview": response[:400],
                "response_length": len(response),
            },
            indent=2,
        )
    )
except Exception as exc:
    print(json.dumps({"smoke_ok": False, "error": str(exc)}, indent=2))
    raise
finally:
    client.close()
PY
  )"
  local rc=$?
  set -e

  printf '%s\n' "$output"
  SMOKE_TEST_OUTPUT="$output"
  return "$rc"
}

run_smoke_test_with_recovery() {
  local python_exe="$1"

  write_section "Smoke Test"
  if invoke_smoke_test "$python_exe"; then
    return 0
  fi

  if [[ "$SMOKE_TEST_OUTPUT" != *"status=BUSY"* &&
        "$SMOKE_TEST_OUTPUT" != *"Timed out waiting for streamed device response"* &&
        "$SMOKE_TEST_OUTPUT" != *"Smoke summarize returned error payload"* ]]; then
    die "Smoke test failed."
  fi

  write_status "Smoke recovery" "Detected busy or stuck summarize state; retrying after Jetson bridge restart"
  write_section "Bridge Recovery"
  restart_jetson_bridge
  wait_jetson_bridge_settle "$BRIDGE_SETTLE_SECONDS"

  write_section "Smoke Test Retry"
  invoke_smoke_test "$python_exe" || die "Smoke test failed after Jetson bridge restart retry. If the Pico HID interface is wedged, do a physical Pico reset before retrying setup."
}

matching_process_ids() {
  local pattern="$1"
  pgrep -f "$pattern" || true
}

stop_matching_processes() {
  local label="$1"
  local pattern="$2"
  local ids
  ids="$(matching_process_ids "$pattern")"
  [[ -n "$ids" ]] || return 0

  write_status "$label" "Stopping existing process(es): $(echo "$ids" | tr '\n' ',' | sed 's/,$//')"
  if (( DRY_RUN )); then
    return 0
  fi

  pkill -f "$pattern" || true
  sleep 2
  pkill -9 -f "$pattern" || true
  sleep 1
}

launch_in_terminal() {
  local command_text="$1"
  local escaped
  escaped="$(apple_script_escape "$command_text")"

  if (( DRY_RUN )); then
    print_dry_run osascript -e "tell application \"Terminal\" to do script \"$command_text\""
    return 0
  fi

  osascript <<EOF >/dev/null
tell application "Terminal"
  activate
  do script "$escaped"
end tell
EOF
}

start_spark_app() {
  local python_exe="$1"
  local script_path="$REPO_ROOT/spark_app_v2.py"
  local command_text

  stop_matching_processes "App status" "spark_app_v2\\.py"

  if (( HEADLESS_APP_LAUNCH )); then
    mkdir -p "$REPO_ROOT/logs"
    if (( DRY_RUN )); then
      print_dry_run nohup "$python_exe" "$script_path" ">" "$REPO_ROOT/logs/spark_app_v2.launch.log" "2>&1" "&"
    else
      nohup "$python_exe" "$script_path" >"$REPO_ROOT/logs/spark_app_v2.launch.log" 2>&1 &
    fi
    write_status "App status" "spark_app_v2.py launched"
    return 0
  fi

  command_text="cd $(quote_args "$REPO_ROOT"); $(quote_args "$python_exe" "$script_path")"
  launch_in_terminal "$command_text"
  write_status "App status" "spark_app_v2.py launched in Terminal"
}

start_full_stack_watcher() {
  local python_exe="$1"
  local watcher_path="$REPO_ROOT/tools/monitoring/watch_full_stack.py"
  local command_text

  stop_matching_processes "Watcher status" "watch_full_stack\\.py"
  command_text="cd $(quote_args "$REPO_ROOT"); $(quote_args "$python_exe" "$watcher_path")"
  launch_in_terminal "$command_text"
  write_status "Watcher status" "tools/monitoring/watch_full_stack.py launched in Terminal"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --jetson-host)
        JETSON_HOST="$2"
        shift 2
        ;;
      --jetson-user)
        JETSON_USER="$2"
        shift 2
        ;;
      --jetson-remote-path)
        JETSON_REMOTE_PATH="$2"
        shift 2
        ;;
      --jetson-ssh-connect-timeout-seconds)
        JETSON_SSH_CONNECT_TIMEOUT_SECONDS="$2"
        shift 2
        ;;
      --bridge-settle-seconds)
        BRIDGE_SETTLE_SECONDS="$2"
        shift 2
        ;;
      --skip-smoke-test)
        SKIP_SMOKE_TEST=1
        shift
        ;;
      --skip-app-launch)
        SKIP_APP_LAUNCH=1
        shift
        ;;
      --headless-app-launch)
        HEADLESS_APP_LAUNCH=1
        shift
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        usage >&2
        die "Unknown argument: $1"
        ;;
    esac
  done
}

invoke_setup_spark() {
  local python_exe
  local pico_mount

  cd "$REPO_ROOT"

  write_section "Environment"
  initialize_repo_python_environment
  python_exe="$REPO_PYTHON"
  write_status "Repo root" "$REPO_ROOT"
  write_status "Python" "$python_exe"
  write_status "Jetson SSH" "$JETSON_USER@$JETSON_HOST"
  check_accessibility_permissions "$python_exe"
  assert_host_tooling_ready

  write_section "Drive Detection"
  if ! pico_mount="$(get_pico_mount)"; then
    die "Could not find a mounted CIRCUITPY volume for the Pico."
  fi
  write_status "Pico volume" "$pico_mount"
  assert_pico_writable_mount "$pico_mount"
  if (( DRY_RUN )); then
    write_status "Pico code.py" "DRY-RUN"
    write_status "Pico boot.py" "DRY-RUN"
  else
    write_status "Pico code.py" "$( [[ -f "$pico_mount/code.py" ]] && printf 'true' || printf 'false' )"
    write_status "Pico boot.py" "$( [[ -f "$pico_mount/boot.py" ]] && printf 'true' || printf 'false' )"
  fi

  local bridge_exists="false"
  local llama_exists="false"
  if test_jetson_remote_directory "$JETSON_REMOTE_PATH/demo/pico_bridge"; then
    bridge_exists="true"
  fi
  if test_jetson_remote_directory "$JETSON_REMOTE_PATH/demo/llama_demo"; then
    llama_exists="true"
  fi

  write_status "Bridge folder" "$bridge_exists"
  write_status "LLM folder" "$llama_exists"

  [[ "$bridge_exists" == "true" ]] || die "Jetson bridge folder was not found."
  [[ "$llama_exists" == "true" ]] || die "Jetson llama folder was not found."

  assert_jetson_writable_mount
  write_section "Jetson Clock"
  sync_jetson_time

  write_section "Deployment"
  deploy_pico_firmware "$python_exe" "$pico_mount"
  sync_jetson_bridge_bundle

  write_section "Cleanup"
  stop_matching_processes "App status" "spark_app_v2\\.py"
  stop_matching_processes "Watcher status" "watch_full_stack\\.py"

  write_section "Jetson Services"
  start_jetson_services
  wait_jetson_bridge_settle "$BRIDGE_SETTLE_SECONDS"

  if (( !SKIP_SMOKE_TEST )); then
    run_smoke_test_with_recovery "$python_exe"
  fi

  if (( !SKIP_APP_LAUNCH )); then
    write_section "Launch App"
    start_spark_app "$python_exe"
    start_full_stack_watcher "$python_exe"
  fi

  write_section "Done"
  write_status "Result" "Setup complete"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  parse_args "$@"
  invoke_setup_spark
fi
