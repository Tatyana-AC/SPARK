param(
    [string]$JetsonHost = "192.168.55.1",
    [string]$JetsonUser = "sidac",
    [string]$JetsonMountLetter = "Z",
    [string]$JetsonRemotePath = "/mnt/usb_drive",
    [int]$BridgeSettleSeconds = 10,
    [switch]$SkipSmokeTest,
    [switch]$SkipAppLaunch
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Write-Status {
    param(
        [string]$Label,
        [string]$Value
    )
    Write-Host ("{0,-24} {1}" -f "${Label}:", $Value)
}

function Get-RepoPython {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        return $python.Source
    }

    throw "Could not find a Python interpreter or .venv\Scripts\python.exe."
}

function Get-PicoMount {
    $drives = Get-CimInstance Win32_LogicalDisk | Where-Object {
        $_.VolumeName -eq "CIRCUITPY"
    }

    if (-not $drives) {
        return $null
    }

    $drive = $drives | Select-Object -First 1
    [pscustomobject]@{
        Drive       = $drive.DeviceID
        VolumeName  = $drive.VolumeName
        Provider    = $drive.ProviderName
        CodePath    = Join-Path $drive.DeviceID "code.py"
        BootPath    = Join-Path $drive.DeviceID "boot.py"
    }
}

function Get-JetsonMount {
    param(
        [string]$JetsonHostValue,
        [string]$JetsonUserValue
    )

    $expectedFragments = @(
        "\\sshfs.kr\$JetsonUserValue@$JetsonHostValue",
        "\\sshfs.r\$JetsonUserValue@$JetsonHostValue",
        "\\sshfs.k\$JetsonUserValue@$JetsonHostValue",
        "\\sshfs\$JetsonUserValue@$JetsonHostValue"
    )

    $networkDrives = Get-CimInstance Win32_LogicalDisk | Where-Object {
        $_.DriveType -eq 4 -and $_.ProviderName
    }

    foreach ($drive in $networkDrives) {
        foreach ($fragment in $expectedFragments) {
            if ($drive.ProviderName -like "$fragment*") {
                return [pscustomobject]@{
                    Drive      = $drive.DeviceID
                    Provider   = $drive.ProviderName
                    VolumeName = $drive.VolumeName
                }
            }
        }
    }

    return $null
}

function Ensure-JetsonMount {
    param(
        [string]$JetsonHostValue,
        [string]$JetsonUserValue,
        [string]$MountLetter,
        [string]$RemotePath
    )

    $existing = Get-JetsonMount -JetsonHostValue $JetsonHostValue -JetsonUserValue $JetsonUserValue
    if ($null -ne $existing) {
        Write-Status "Jetson mount" "$($existing.Drive) already mapped to $($existing.Provider)"
        return $existing
    }

    $sshfsWin = "C:\Program Files\SSHFS-Win\bin\sshfs-win.exe"
    if (-not (Test-Path $sshfsWin)) {
        throw "SSHFS-Win was not found at $sshfsWin."
    }

    $driveLetter = $MountLetter.TrimEnd(":").ToUpperInvariant()
    $driveRoot = "${driveLetter}:"
    $existingDrive = Get-CimInstance Win32_LogicalDisk | Where-Object {
        $_.DeviceID -eq $driveRoot
    }
    if ($null -ne $existingDrive) {
        $existingLabel = if ($existingDrive.ProviderName) {
            $existingDrive.ProviderName
        }
        elseif ($existingDrive.VolumeName) {
            $existingDrive.VolumeName
        }
        else {
            "another drive"
        }
        throw "$driveRoot is already in use by $existingLabel."
    }

    $remoteWindowsPath = ($RemotePath -replace "^/", "") -replace "/", "\"
    $prefix = "\sshfs.kr\$JetsonUserValue@$JetsonHostValue\$remoteWindowsPath"

    Write-Status "Jetson mount" "Mapping $driveRoot with SSHFS-Win"
    & $sshfsWin svc $prefix $driveRoot
    if ($LASTEXITCODE -ne 0) {
        throw "SSHFS-Win mount command failed with exit code $LASTEXITCODE."
    }

    for ($attempt = 1; $attempt -le 20; $attempt++) {
        Start-Sleep -Seconds 1
        $mounted = Get-JetsonMount -JetsonHostValue $JetsonHostValue -JetsonUserValue $JetsonUserValue
        if ($null -ne $mounted) {
            Write-Status "Jetson mount" "$($mounted.Drive) mapped to $($mounted.Provider)"
            return $mounted
        }
    }

    throw "Jetson SSHFS mount did not appear after mapping attempt."
}

function Invoke-JetsonSsh {
    param([string]$ScriptText)

    $target = "$JetsonUser@$JetsonHost"
    $ScriptText | & ssh $target "bash -s"
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed with exit code $LASTEXITCODE."
    }
}

function Start-JetsonServices {
    param([string]$RemotePath)

    $remoteScript = @'
set -euo pipefail

ROOT_DIR='__REMOTE_PATH__/demo'
LLAMA_DIR="$ROOT_DIR/llama_demo"
BRIDGE_DIR="$ROOT_DIR/pico_bridge"
SERVER_LOG="$LLAMA_DIR/server.log"
BRIDGE_LOG="$BRIDGE_DIR/bridge.log"
MODEL_PATH="$LLAMA_DIR/models/Qwen3.5-2B-Q4_K_M.gguf"
BIN_PATH="$LLAMA_DIR/llama.cpp/build/bin/llama-server"

check_server() {
python3 - <<'PY'
import json
import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen('http://127.0.0.1:8080/v1/models', timeout=3) as response:
        payload = response.read().decode('utf-8', 'ignore')
    print(payload)
    sys.exit(0)
except urllib.error.HTTPError as exc:
    print(f"HTTP {exc.code}")
    sys.exit(2)
except Exception as exc:
    print(type(exc).__name__, exc)
    sys.exit(1)
PY
}

echo "Jetson host: $(hostname)"
echo "Jetson user: $(whoami)"
echo "Bridge dir: $BRIDGE_DIR"

if pgrep -af 'llama-server' >/dev/null 2>&1; then
    echo "llama-server status: already running"
else
    echo "llama-server status: starting"
    nohup bash -lc "cd '$LLAMA_DIR' && exec '$BIN_PATH' -m '$MODEL_PATH' -c 8192 -ngl 40 --reasoning-budget 0 --port 8080 --host 0.0.0.0" >"$SERVER_LOG" 2>&1 < /dev/null &
fi

server_ready=0
for attempt in $(seq 1 90); do
    set +e
    server_output=$(check_server 2>&1)
    server_rc=$?
    set -e
    if [ "$server_rc" -eq 0 ]; then
        server_ready=1
        echo "llama-server endpoint: ready"
        echo "$server_output"
        break
    fi
    if [ "$server_rc" -eq 2 ]; then
        echo "llama-server endpoint: loading ($attempt/90)"
    else
        echo "llama-server endpoint: waiting ($attempt/90) - $server_output"
    fi
    sleep 2
done

if [ "$server_ready" -ne 1 ]; then
    echo "llama-server failed to become ready"
    tail -n 80 "$SERVER_LOG" || true
    exit 1
fi

sudo chmod 666 /dev/ttyTHS0

if pgrep -af 'pico_llm_bridge.py' >/dev/null 2>&1; then
    echo "bridge status: already running"
else
    echo "bridge status: starting"
    nohup bash -lc "cd '$BRIDGE_DIR' && exec ./run_bridge.sh" >"$BRIDGE_LOG" 2>&1 < /dev/null &
fi

sleep 3

echo "process status:"
pgrep -af 'llama-server|pico_llm_bridge.py' || true
echo "bridge log tail:"
tail -n 20 "$BRIDGE_LOG" || true
'@
    $remoteScript = $remoteScript.Replace("__REMOTE_PATH__", $RemotePath)

    Invoke-JetsonSsh -ScriptText $remoteScript
}

function Restart-JetsonBridge {
    param([string]$RemotePath)

    $remoteScript = @'
set -euo pipefail

BRIDGE_DIR="__REMOTE_PATH__/demo/pico_bridge"
BRIDGE_LOG="$BRIDGE_DIR/bridge.log"

pkill -f 'pico_llm_bridge.py' || true
sleep 2
cd "$BRIDGE_DIR"
nohup bash -lc "cd '$BRIDGE_DIR' && exec ./run_bridge.sh" >"$BRIDGE_LOG" 2>&1 < /dev/null &
sleep 4
echo "bridge restart status:"
pgrep -af 'pico_llm_bridge.py' || true
echo "bridge log tail:"
tail -n 20 "$BRIDGE_LOG" || true
'@
    $remoteScript = $remoteScript.Replace("__REMOTE_PATH__", $RemotePath)

    Invoke-JetsonSsh -ScriptText $remoteScript
}

function Wait-JetsonBridgeSettle {
    param([int]$Seconds)

    if ($Seconds -le 0) {
        return
    }

    Write-Status "Bridge settle" "Waiting $Seconds second(s) for UART path to stabilize"
    Start-Sleep -Seconds $Seconds
}

function Invoke-SmokeTest {
    param([string]$PythonExe)

    $smokeScript = @'
import json
import sys
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
'@

    $previousPreference = $ErrorActionPreference
    $global:ErrorActionPreference = "Continue"
    try {
        $output = $smokeScript | & $PythonExe "-" 2>&1
    }
    finally {
        $global:ErrorActionPreference = $previousPreference
    }
    $exitCode = $LASTEXITCODE

    foreach ($line in $output) {
        Write-Host $line
    }

    return [pscustomobject]@{
        Success  = ($exitCode -eq 0)
        ExitCode = $exitCode
        Output   = ($output -join [Environment]::NewLine)
    }
}

function Invoke-PicoSoftReload {
    param([string]$PicoDrive)

    $probePath = Join-Path $PicoDrive "__spark_reload_probe.txt"
    Write-Status "Pico recovery" "Triggering CircuitPython autoreload on $PicoDrive"
    Set-Content -Path $probePath -Value (Get-Date).ToString("o")
    Start-Sleep -Seconds 2
    Remove-Item -Path $probePath -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
}

function Run-SmokeTestWithRecovery {
    param(
        [string]$PythonExe,
        [string]$PicoDrive,
        [string]$RemotePath
    )

    Write-Section "Smoke Test"
    $result = Invoke-SmokeTest -PythonExe $PythonExe
    if ($result.Success) {
        return
    }

    $shouldRetry = $result.Output -match "status=BUSY" -or
        $result.Output -match "Timed out waiting for streamed device response" -or
        $result.Output -match "Smoke summarize returned error payload"

    if (-not $shouldRetry) {
        throw "Smoke test failed with exit code $($result.ExitCode)."
    }

    Write-Status "Smoke recovery" "Detected busy or stuck summarize state; retrying after Pico soft reload"
    Invoke-PicoSoftReload -PicoDrive $PicoDrive
    Write-Section "Bridge Recovery"
    Restart-JetsonBridge -RemotePath $RemotePath
    Wait-JetsonBridgeSettle -Seconds $BridgeSettleSeconds

    Write-Section "Smoke Test Retry"
    $retry = Invoke-SmokeTest -PythonExe $PythonExe
    if ($retry.Success) {
        return
    }

    throw "Smoke test failed after Pico soft reload retry."
}

function Get-SparkAppProcesses {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match "^python(?:w)?(?:\.exe)?$" -and
        $_.CommandLine -match "spark_app_v2\.py"
    }
}

function Stop-SparkAppProcesses {
    $processes = @(Get-SparkAppProcesses)
    if ($processes.Count -eq 0) {
        return
    }

    $ids = $processes | ForEach-Object { $_.ProcessId }
    Write-Status "App status" ("Stopping existing spark_app_v2.py instance(s): " + ($ids -join ", "))

    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 2

    $remaining = @(Get-SparkAppProcesses)
    foreach ($process in $remaining) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 1
}

function Start-SparkApp {
    param([string]$PythonExe)

    $existing = @(Get-SparkAppProcesses)

    if ($existing) {
        Write-Status "App status" "spark_app_v2.py is already running"
        return
    }

    $scriptPath = Join-Path $RepoRoot "spark_app_v2.py"
    Start-Process -FilePath $PythonExe -ArgumentList @($scriptPath) -WorkingDirectory $RepoRoot | Out-Null
    Write-Status "App status" "spark_app_v2.py launched"
}

Write-Section "Environment"
$pythonExe = Get-RepoPython
Write-Status "Repo root" $RepoRoot
Write-Status "Python" $pythonExe
Write-Status "Jetson SSH" "$JetsonUser@$JetsonHost"

Write-Section "Drive Detection"
$picoMount = Get-PicoMount
if ($null -eq $picoMount) {
    throw "Could not find a mounted CIRCUITPY drive for the Pico."
}
Write-Status "Pico drive" $picoMount.Drive
Write-Status "Pico code.py" (Test-Path $picoMount.CodePath)
Write-Status "Pico boot.py" (Test-Path $picoMount.BootPath)

$jetsonMount = Ensure-JetsonMount -JetsonHostValue $JetsonHost -JetsonUserValue $JetsonUser -MountLetter $JetsonMountLetter -RemotePath $JetsonRemotePath
Write-Status "Jetson drive" $jetsonMount.Drive
Write-Status "Jetson path" $jetsonMount.Provider

$bridgePath = Join-Path $jetsonMount.Drive "demo\pico_bridge"
$llamaPath = Join-Path $jetsonMount.Drive "demo\llama_demo"
Write-Status "Bridge folder" (Test-Path $bridgePath)
Write-Status "LLM folder" (Test-Path $llamaPath)

Write-Section "Jetson Services"
Start-JetsonServices -RemotePath $JetsonRemotePath
Wait-JetsonBridgeSettle -Seconds $BridgeSettleSeconds

if (-not $SkipSmokeTest) {
    Stop-SparkAppProcesses
    Run-SmokeTestWithRecovery -PythonExe $pythonExe -PicoDrive $picoMount.Drive -RemotePath $JetsonRemotePath
}

if (-not $SkipAppLaunch) {
    Write-Section "Launch App"
    Start-SparkApp -PythonExe $pythonExe
}

Write-Section "Done"
Write-Status "Result" "Setup complete"
