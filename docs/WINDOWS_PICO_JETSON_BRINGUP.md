# Windows Pico + Jetson Bring-Up

This is the current manual bring-up flow for the real Windows host -> Pico -> Jetson setup on this branch.

Use this when:

- the Pico mounts on `D:\` as `CIRCUITPY`
- the Jetson USB/network drive is mounted on `Z:\`
- the Jetson is reachable over SSH at `192.168.55.1`

## Preconditions

On the Windows host:

- repo is checked out locally
- `.venv` exists and `requirements.txt` is installed
- the Pico appears as `D:\`
- the Jetson share appears as `Z:\`

On the Jetson:

- the bridge deployment directory is `/mnt/usb_drive/demo/pico_bridge`
- the llama.cpp demo directory is `/mnt/usb_drive/demo/llama_demo`
- `python3`, `requests`, and `pyserial` are installed
- `run_demo.sh` and `run_bridge.sh` exist

## 1. Deploy the Pico firmware to `D:\`

From the repo root on Windows:

```powershell
.\.venv\Scripts\python.exe .\tools\pico\deploy_to_pico.py --target D:\
```

This deploy now exact-syncs the default Pico runtime and removes stale non-preserved files from `CIRCUITPY`. Use `--dry-run` first if you want to inspect planned deletions.

That updates:

- `boot.py`
- `code.py`
- `jetson_transport.py`
- `protocol.py`
- `upload_protocol.py`
- `serial_bridge.py`
- `usb_config.py`
- `lib\adafruit_hid`

Notes:

- The helper copies `code.py` last so CircuitPython reloads after the support files are already in place.
- If `boot.py` changed materially, a physical Pico reconnect is still the safest way to force the USB config to re-enumerate.

## 2. Sync the Jetson bridge bundle to `Z:\demo\pico_bridge`

Copy the deployable bridge files from `jetson\` to the mounted Jetson folder.

Example PowerShell:

```powershell
$target = 'Z:\demo\pico_bridge'
$files = @(
  'db_manager.py',
  'pico_llm_bridge.py',
  'protocol.py',
  'receiver.py',
  'requirements.txt',
  'run_bridge.sh'
)

foreach ($file in $files) {
  Copy-Item -LiteralPath (Join-Path 'C:\SPARK\jetson' $file) `
    -Destination (Join-Path $target $file) `
    -Force
}
```

Do not overwrite `jetson_spark.db` unless you intentionally want to replace the Jetson database.

## 3. Start the llama.cpp server on Jetson

SSH to the Jetson:

```powershell
ssh 192.168.55.1
```

From the Jetson shell:

```bash
cd /mnt/usb_drive/demo/llama_demo
nohup bash ./run_demo.sh > server.log 2>&1 < /dev/null &
```

Wait for model load to finish. Verification:

```bash
python3 - <<'PY'
import urllib.request
for url in ("http://127.0.0.1:8080/health", "http://127.0.0.1:8080/v1/models"):
    with urllib.request.urlopen(url, timeout=10) as r:
        print(url, r.status)
        print(r.read(200).decode("utf-8", "ignore"))
PY
```

Expected result:

- `/health` returns `200` with `{"status":"ok"}`
- `/v1/models` returns `200` with the loaded GGUF model metadata

## 4. Start the Jetson bridge

From the Jetson shell:

```bash
cd /mnt/usb_drive/demo/pico_bridge
nohup ./run_bridge.sh > bridge.log 2>&1 < /dev/null &
```

Verification:

```bash
pgrep -af pico_llm_bridge.py
tail -n 40 /mnt/usb_drive/demo/pico_bridge/bridge.log
```

Expected log lines include:

- `JetsonDB opened`
- `Opening /dev/ttyTHS0 at 115200 baud`
- `Serial connected`

## 5. Important startup-order caveat

After the Jetson bridge opens `/dev/ttyTHS0`, wait about 5 to 10 seconds before launching the Windows app or sending the first host context packet.

Reason:

- If the host sends immediately after bridge startup, the first CDC packet can be truncated at the front.
- In real verification, the missing bytes were exactly the framed packet prefix (`SP`, packet header, and JSON version byte).
- After a short warmup, the full framed packet arrived and Jetson DB writes succeeded normally.

Practical rule:

- start `run_bridge.sh`
- wait 5 to 10 seconds
- then launch `spark_app_v2.py`

If you restart the bridge, follow the same wait again.

## 6. Launch the Windows host app

From the repo root on Windows:

```powershell
.\.venv\Scripts\python.exe .\spark_app_v2.py
```

Before launching another copy, make sure older `spark_app_v2.py` processes are closed. Duplicate host app processes can contend for the Pico HID session and cause:

- `BUSY`
- `read error`
- Raw HID timeouts

## 7. End-to-end verification

Minimum checks:

1. Pico Raw HID is visible and `SparkHIDClient.get_info()` succeeds.
2. Jetson bridge process is running.
3. Jetson `/health` and `/v1/models` both return `200`.
4. A context packet written through `host_pc.serial_sender.SerialSender` creates or updates a row in `jetson_spark.db`.
5. A `FEATURE_1` summarize request returns streamed text through the real host -> Pico -> Jetson -> llama.cpp path.

## 8. Fast recovery checklist

If summarize fails but USB still enumerates:

- close duplicate host app processes first
- confirm `llama-server` is still up
- confirm `pico_llm_bridge.py` is still up
- if the bridge was just restarted, wait 5 to 10 seconds and retry
- if Raw HID still times out, physically reset the Pico before deeper software recovery
