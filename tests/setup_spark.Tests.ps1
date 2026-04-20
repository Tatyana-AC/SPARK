Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot '..\setup_spark.ps1')

Describe 'Get-JetsonMount' {
    It 'returns only the existing mount whose provider matches the requested remote path' {
        function script:Get-CimInstance {
            @(
                [pscustomobject]@{
                    DriveType = 4
                    DeviceID = 'Y:'
                    ProviderName = '\\sshfs.r\sidac@192.168.55.1'
                    VolumeName = ''
                }
                [pscustomobject]@{
                    DriveType = 4
                    DeviceID = 'Z:'
                    ProviderName = '\\sshfs.r\sidac@192.168.55.1\mnt\usb_drive'
                    VolumeName = ''
                }
            )
        }

        $result = Get-JetsonMount `
            -JetsonHostValue '192.168.55.1' `
            -JetsonUserValue 'sidac' `
            -RemotePathValue '/mnt/usb_drive'

        $result.Drive | Should Be 'Z:'
        $result.Provider | Should Be '\\sshfs.r\sidac@192.168.55.1\mnt\usb_drive'
    }
}

Describe 'Get-PicoMount' {
    It 'falls back to an unlabeled removable drive that contains boot.py and code.py' {
        function script:Get-CimInstance {
            @(
                [pscustomobject]@{
                    DriveType = 2
                    DeviceID = 'D:'
                    VolumeName = ''
                }
            )
        }

        function script:Test-Path {
            param([string]$Path)
            return $Path -in @('D:\boot.py', 'D:\code.py')
        }

        $result = Get-PicoMount

        $result.Drive | Should Be 'D:'
        $result.CodePath | Should Be 'D:\code.py'
        $result.BootPath | Should Be 'D:\boot.py'
    }
}

Describe 'Get-RepoPython' {
    It 'prefers the shared repo virtualenv when running from a git worktree' {
        $script:RepoRoot = 'C:\SPARK\.worktrees\pico-lcd-button-summarize'

        function script:Get-GitCommonRepoRoot {
            return 'C:\SPARK'
        }

        function script:Test-Path {
            param([string]$Path)
            return $Path -eq 'C:\SPARK\.venv\Scripts\python.exe'
        }

        function script:Get-Command {
            throw 'Get-Command should not be used when shared repo venv exists'
        }

        $result = Get-RepoPython

        $result | Should Be 'C:\SPARK\.venv\Scripts\python.exe'
    }
}

Describe 'Ensure-RepoVirtualEnv' {
    It 'creates the repo virtualenv with a bootstrap Python when the venv is missing' {
        $script:RepoRoot = 'C:\SPARK'
        $script:createCall = $null

        function script:Get-RepoVirtualEnvRoot {
            'C:\SPARK'
        }
        function script:Test-Path {
            param([string]$Path)
            if ($Path -eq 'C:\SPARK\.venv\Scripts\python.exe') {
                return $false
            }
            return $true
        }
        function script:Get-BootstrapPython {
            [pscustomobject]@{
                FilePath = 'C:\Python311\python.exe'
                PrefixArguments = @()
            }
        }
        function script:Write-Status {}
        function script:Invoke-ProcessWithTimeout {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [int]$TimeoutSeconds,
                [string]$DisplayName
            )

            $script:createCall = [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                TimeoutSeconds = $TimeoutSeconds
                DisplayName = $DisplayName
            }
        }

        $result = Ensure-RepoVirtualEnv

        $result | Should Be 'C:\SPARK\.venv\Scripts\python.exe'
        $script:createCall.FilePath | Should Be 'C:\Python311\python.exe'
        $script:createCall.ArgumentList | Should Be @(
            '-m'
            'venv'
            'C:\SPARK\.venv'
        )
        $script:createCall.TimeoutSeconds | Should Be 180
        $script:createCall.DisplayName | Should Be 'Create virtual environment'
    }
}

Describe 'Ensure-RepoRequirementsInstalled' {
    It 'runs pip install and records the requirements fingerprint when dependencies are stale' {
        $script:RepoRoot = 'C:\SPARK'
        $script:processCalls = @()
        $script:stampWrite = $null

        function script:Test-RepoRequirementsCurrent {
            param([string]$PythonExe)
            return $false
        }
        function script:Get-RequirementsFingerprint {
            'abc123'
        }
        function script:Write-Status {}
        function script:Invoke-ProcessWithTimeout {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [int]$TimeoutSeconds,
                [string]$DisplayName
            )

            $script:processCalls += [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                TimeoutSeconds = $TimeoutSeconds
                DisplayName = $DisplayName
            }
        }
        function script:Set-Content {
            param(
                [string]$Path,
                [string]$Value,
                [switch]$NoNewline
            )

            $script:stampWrite = [pscustomobject]@{
                Path = $Path
                Value = $Value
                NoNewline = $NoNewline.IsPresent
            }
        }

        Ensure-RepoRequirementsInstalled -PythonExe 'C:\SPARK\.venv\Scripts\python.exe'

        $script:processCalls.Count | Should Be 2
        $script:processCalls[0].ArgumentList | Should Be @('-m', 'pip', 'install', '--upgrade', 'pip')
        $script:processCalls[1].ArgumentList | Should Be @(
            '-m'
            'pip'
            'install'
            '-r'
            'C:\SPARK\requirements.txt'
        )
        $script:stampWrite.Path | Should Be 'C:\SPARK\.venv\requirements.sha256'
        $script:stampWrite.Value | Should Be 'abc123'
        $script:stampWrite.NoNewline | Should Be $true
    }
}

Describe 'Assert-HostToolingReady' {
    It 'throws a clear error when batch-mode SSH authentication is unavailable' {
        function script:Write-Status {}
        function script:Test-Path {
            param([string]$Path)
            return $Path -eq 'C:\Program Files\SSHFS-Win\bin\sshfs-win.exe'
        }
        function script:Get-Command {
            param([string]$Name)
            if ($Name -eq 'ssh') {
                return [pscustomobject]@{ Source = 'C:\Windows\System32\OpenSSH\ssh.exe' }
            }
            return $null
        }
        function script:Test-JetsonSshBatchMode {
            param([string]$JetsonHostValue, [string]$JetsonUserValue)
            return $false
        }

        {
            Assert-HostToolingReady -JetsonHostValue '192.168.55.1' -JetsonUserValue 'sidac'
        } | Should Throw 'Batch-mode SSH authentication to sidac@192.168.55.1 failed. Configure passwordless SSH before running setup_spark.ps1.'
    }
}

Describe 'Deploy-PicoFirmware' {
    It 'runs deploy_to_pico.py against the detected Pico drive' {
        $script:RepoRoot = 'C:\SPARK'
        $script:deployArgs = $null

        function script:Write-Status {}
        function script:Test-Path {
            param([string]$Path)
            return $Path -eq 'C:\SPARK\tools\pico\deploy_to_pico.py'
        }
        function script:Invoke-ProcessWithTimeout {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [int]$TimeoutSeconds,
                [string]$DisplayName
            )

            $script:deployArgs = [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                TimeoutSeconds = $TimeoutSeconds
                DisplayName = $DisplayName
            }
        }

        Deploy-PicoFirmware -PythonExe 'python.exe' -PicoDrive 'D:'

        $script:deployArgs.FilePath | Should Be 'python.exe'
        $script:deployArgs.ArgumentList | Should Be @(
            'C:\SPARK\tools\pico\deploy_to_pico.py'
            '--target'
            'D:\'
        )
        $script:deployArgs.TimeoutSeconds | Should Be 120
        $script:deployArgs.DisplayName | Should Be 'Pico deploy'
    }
}

Describe 'Sync-JetsonBridgeBundle' {
    It 'copies the deployable Jetson bridge bundle into demo\pico_bridge without touching the database' {
        $script:RepoRoot = 'C:\SPARK'
        $script:copyCalls = @()

        function script:Write-Status {}
        function script:Test-Path {
            param([string]$Path)
            return $Path -eq 'Z:\demo\pico_bridge'
        }
        function script:Copy-Item {
            param(
                [string]$LiteralPath,
                [string]$Destination,
                [switch]$Force
            )

            $script:copyCalls += [pscustomobject]@{
                LiteralPath = $LiteralPath
                Destination = $Destination
                Force = $Force.IsPresent
            }
        }

        Sync-JetsonBridgeBundle -JetsonDrive 'Z:'

        $script:copyCalls.LiteralPath | Should Be @(
            'C:\SPARK\jetson\db_manager.py'
            'C:\SPARK\jetson\pico_llm_bridge.py'
            'C:\SPARK\jetson\protocol.py'
            'C:\SPARK\jetson\receiver.py'
            'C:\SPARK\jetson\requirements.txt'
            'C:\SPARK\jetson\run_bridge.sh'
        )
        $script:copyCalls.Destination | Should Be @(
            'Z:\demo\pico_bridge\db_manager.py'
            'Z:\demo\pico_bridge\pico_llm_bridge.py'
            'Z:\demo\pico_bridge\protocol.py'
            'Z:\demo\pico_bridge\receiver.py'
            'Z:\demo\pico_bridge\requirements.txt'
            'Z:\demo\pico_bridge\run_bridge.sh'
        )
        @($script:copyCalls | Where-Object { $_.LiteralPath -match 'jetson_spark\.db' }).Count | Should Be 0
    }
}

Describe 'Ensure-JetsonMount' {
    It 'returns the mounted drive without waiting for the mount process to exit' {
        $script:mountChecks = 0
        $script:startCalls = 0
        $script:stopCalls = 0

        function script:Write-Status {}
        function script:Test-Path { $true }
        function script:Get-CimInstance { @() }
        function script:Start-Process {
            $script:startCalls += 1
            [pscustomobject]@{ Id = 4242 }
        }
        function script:Start-Sleep {}
        function script:Stop-ProcessTree { $script:stopCalls += 1 }
        function script:Get-JetsonMount {
            $script:mountChecks += 1
            if ($script:mountChecks -lt 3) {
                return $null
            }

            [pscustomobject]@{
                Drive = 'Z:'
                Provider = '\\sshfs.kr\sidac@192.168.55.1\mnt\usb_drive'
                VolumeName = ''
            }
        }

        $result = Ensure-JetsonMount `
            -JetsonHostValue '192.168.55.1' `
            -JetsonUserValue 'sidac' `
            -MountLetter 'Z' `
            -RemotePath '/mnt/usb_drive' `
            -MountCommandTimeoutSeconds 30

        $result.Drive | Should Be 'Z:'
        $script:startCalls | Should Be 1
        $script:stopCalls | Should Be 0
    }
}

Describe 'Assert-JetsonWritableMount' {
    It 'throws when the Jetson remote mount is read-only' {
        function script:Invoke-JetsonSsh {
            param([string]$ScriptText)
            return 'ro,relatime'
        }

        {
            Assert-JetsonWritableMount -RemotePath '/mnt/usb_drive'
        } | Should Throw 'Jetson remote path /mnt/usb_drive is mounted read-only (ro,relatime). Repair the Jetson storage and remount it read-write before running setup_spark.ps1 again.'
    }

    It 'allows a read-write Jetson remote mount' {
        function script:Invoke-JetsonSsh {
            param([string]$ScriptText)
            return 'rw,relatime'
        }

        {
            Assert-JetsonWritableMount -RemotePath '/mnt/usb_drive'
        } | Should Not Throw
    }
}

Describe 'Invoke-SetupSpark' {
    It 'bootstraps the repo Python env and validates host tooling before drive detection' {
        $script:steps = @()
        $script:SkipSmokeTest = $true
        $script:SkipAppLaunch = $true

        function script:Write-Section {}
        function script:Write-Status {}
        function script:Initialize-RepoPythonEnvironment {
            $script:steps += 'bootstrap-python'
            return 'python.exe'
        }
        function script:Assert-HostToolingReady {
            param([string]$JetsonHostValue, [string]$JetsonUserValue)
            $script:steps += 'validate-host-tooling'
        }
        function script:Get-PicoMount {
            $script:steps += 'detect-pico'
            [pscustomobject]@{
                Drive = 'D:'
                CodePath = 'D:\code.py'
                BootPath = 'D:\boot.py'
            }
        }
        function script:Test-Path { $true }
        function script:Ensure-JetsonMount {
            [pscustomobject]@{
                Drive = 'Z:'
                Provider = '\\sshfs.r\sidac@192.168.55.1\mnt\usb_drive'
                VolumeName = ''
            }
        }
        function script:Assert-JetsonWritableMount { 'rw,relatime' }
        function script:Deploy-PicoFirmware {}
        function script:Sync-JetsonBridgeBundle {}
        function script:Stop-SparkAppProcesses {}
        function script:Stop-WatchFullStackProcesses {}
        function script:Start-JetsonServices {}
        function script:Wait-JetsonBridgeSettle {}

        Invoke-SetupSpark

        $script:steps[0..2] | Should Be @('bootstrap-python', 'validate-host-tooling', 'detect-pico')
    }

    It 'falls back to SSH directory checks when the mapped Jetson path is inaccessible' {
        $script:remoteChecks = @()
        $script:picoDeploys = @()
        $script:jetsonSyncs = @()
        $script:servicesStarted = 0
        $script:SkipSmokeTest = $true
        $script:SkipAppLaunch = $true

        function script:Write-Section {}
        function script:Write-Status {}
        function script:Initialize-RepoPythonEnvironment { 'python' }
        function script:Assert-HostToolingReady {}
        function script:Get-PicoMount {
            [pscustomobject]@{
                Drive = 'D:'
                CodePath = 'D:\code.py'
                BootPath = 'D:\boot.py'
            }
        }
        function script:Ensure-JetsonMount {
            [pscustomobject]@{
                Drive = 'Z:'
                Provider = '\\sshfs.kr\sidac@192.168.55.1\mnt\usb_drive'
                VolumeName = ''
            }
        }
        function script:Test-Path {
            param([string]$Path)

            switch ($Path) {
                'D:\code.py' { return $true }
                'D:\boot.py' { return $true }
                'Z:\demo\pico_bridge' {
                    throw [System.UnauthorizedAccessException]::new('Access is denied')
                }
                'Z:\demo\llama_demo' { return $true }
                default { throw "Unexpected path $Path" }
            }
        }
        function script:Test-JetsonRemoteDirectory {
            param([string]$RemoteDirectory)
            $script:remoteChecks += $RemoteDirectory
            return $true
        }
        function script:Assert-JetsonWritableMount {
            param([string]$RemotePath)
            return 'rw,relatime'
        }
        function script:Deploy-PicoFirmware {
            param([string]$PythonExe, [string]$PicoDrive)
            $script:picoDeploys += [pscustomobject]@{ PythonExe = $PythonExe; PicoDrive = $PicoDrive }
        }
        function script:Sync-JetsonBridgeBundle {
            param([string]$JetsonDrive)
            $script:jetsonSyncs += $JetsonDrive
        }
        function script:Start-JetsonServices {
            param([string]$RemotePath)
            $script:servicesStarted += 1
        }
        function script:Wait-JetsonBridgeSettle {}

        { Invoke-SetupSpark } | Should Not Throw
        $script:remoteChecks | Should Be @(
            '/mnt/usb_drive/demo/pico_bridge'
            '/mnt/usb_drive/demo/llama_demo'
        )
        $script:picoDeploys.Count | Should Be 1
        $script:picoDeploys[0].PythonExe | Should Be 'python'
        $script:picoDeploys[0].PicoDrive | Should Be 'D:'
        $script:jetsonSyncs | Should Be @('Z:')
        $script:servicesStarted | Should Be 1
    }

    It 'launches both the app and full stack watcher when app launch is enabled' {
        $script:SkipSmokeTest = $true
        $script:SkipAppLaunch = $false
        $script:appLaunches = @()
        $script:watcherLaunches = @()

        function script:Write-Section {}
        function script:Write-Status {}
        function script:Initialize-RepoPythonEnvironment { 'python.exe' }
        function script:Assert-HostToolingReady {}
        function script:Get-PicoMount {
            [pscustomobject]@{
                Drive = 'D:'
                CodePath = 'D:\code.py'
                BootPath = 'D:\boot.py'
            }
        }
        function script:Ensure-JetsonMount {
            [pscustomobject]@{
                Drive = 'Z:'
                Provider = '\\sshfs.r\sidac@192.168.55.1\mnt\usb_drive'
                VolumeName = ''
            }
        }
        function script:Test-Path { $true }
        function script:Assert-JetsonWritableMount { 'rw,relatime' }
        function script:Deploy-PicoFirmware {}
        function script:Sync-JetsonBridgeBundle {}
        function script:Start-JetsonServices {}
        function script:Wait-JetsonBridgeSettle {}
        Mock Start-SparkApp {
            param([string]$PythonExe, [switch]$HeadlessLaunch)
            $script:appLaunches += [pscustomobject]@{ PythonExe = $PythonExe; HeadlessLaunch = [bool]$HeadlessLaunch }
        }
        Mock Start-FullStackWatcher {
            param([string]$PythonExe)
            $script:watcherLaunches += [pscustomobject]@{ PythonExe = $PythonExe }
        }

        Invoke-SetupSpark

        $script:appLaunches.Count | Should Be 1
        $script:appLaunches[0].PythonExe | Should Be 'python.exe'
        $script:watcherLaunches.Count | Should Be 1
        $script:watcherLaunches[0].PythonExe | Should Be 'python.exe'
    }

    It 'cleans up existing desktop processes before starting services' {
        $script:SkipSmokeTest = $true
        $script:SkipAppLaunch = $false
        $script:steps = @()

        function script:Write-Section {}
        function script:Write-Status {}
        function script:Initialize-RepoPythonEnvironment { 'python.exe' }
        function script:Assert-HostToolingReady {}
        function script:Get-PicoMount {
            [pscustomobject]@{
                Drive = 'D:'
                CodePath = 'D:\code.py'
                BootPath = 'D:\boot.py'
            }
        }
        function script:Ensure-JetsonMount {
            [pscustomobject]@{
                Drive = 'Z:'
                Provider = '\\sshfs.r\sidac@192.168.55.1\mnt\usb_drive'
                VolumeName = ''
            }
        }
        function script:Test-Path { $true }
        function script:Assert-JetsonWritableMount { 'rw,relatime' }
        function script:Deploy-PicoFirmware {}
        function script:Sync-JetsonBridgeBundle {}
        function script:Stop-SparkAppProcesses { $script:steps += 'stop-app' }
        function script:Stop-WatchFullStackProcesses { $script:steps += 'stop-watcher' }
        function script:Start-JetsonServices { $script:steps += 'start-jetson' }
        function script:Wait-JetsonBridgeSettle {}
        function script:Start-SparkApp { $script:steps += 'start-app' }
        function script:Start-FullStackWatcher { $script:steps += 'start-watcher' }

        Invoke-SetupSpark

        $script:steps | Should Be @('stop-app', 'stop-watcher', 'start-jetson', 'start-app', 'start-watcher')
    }
}

Describe 'Start-JetsonServices' {
    It 'emits a remote script that restarts duplicate bridges and hard-fails unless exactly one remains' {
        $source = Get-Content (Join-Path $PSScriptRoot '..\setup_spark.ps1') -Raw

        $source | Should Match 'BRIDGE_COUNT=\$\(pgrep -fc ''\[p\]ico_llm_bridge\.py'''
        $source | Should Match 'found \$BRIDGE_COUNT running copies; restarting'
        $source | Should Match "pgrep -af '\[p\]ico_llm_bridge\.py'"
        $source | Should Match 'bridge failed to start'
        $source | Should Match 'bridge failed to settle to a single process'
        $source | Should Match "pgrep -af '\[l\]lama-server\|\[p\]ico_llm_bridge\.py'"
    }
}

Describe 'Run-SmokeTestWithRecovery' {
    It 'restarts the Jetson bridge before retrying and avoids Pico soft reload on summarize timeout' {
        $script:sections = @()
        $script:bridgeRestarts = 0
        $script:settleCalls = 0
        $script:softReloads = 0
        $script:smokeCalls = 0

        function script:Write-Section {
            param([string]$Title)
            $script:sections += $Title
        }

        function script:Write-Status {}

        function script:Invoke-SmokeTest {
            param([string]$PythonExe)
            $script:smokeCalls += 1
            if ($script:smokeCalls -eq 1) {
                return [pscustomobject]@{
                    Success = $false
                    ExitCode = 1
                    Output = 'Smoke summarize returned error payload: [ERROR] Jetson request timed out'
                }
            }

            return [pscustomobject]@{
                Success = $true
                ExitCode = 0
                Output = 'ok'
            }
        }

        function script:Restart-JetsonBridge {
            param([string]$RemotePath)
            $script:bridgeRestarts += 1
        }

        function script:Wait-JetsonBridgeSettle {
            param([int]$Seconds)
            $script:settleCalls += 1
        }

        function script:Invoke-PicoSoftReload {
            param([string]$PicoDrive)
            $script:softReloads += 1
        }

        Run-SmokeTestWithRecovery -PythonExe 'python' -PicoDrive 'D:' -RemotePath '/mnt/usb_drive'

        $script:bridgeRestarts | Should Be 1
        $script:settleCalls | Should Be 1
        $script:softReloads | Should Be 0
        $script:sections | Should Be @('Smoke Test', 'Bridge Recovery', 'Smoke Test Retry')
    }
}

Describe 'Invoke-SmokeTest' {
    It 'returns a non-zero exit without printing a Python traceback for handled smoke failures' {
        $source = Get-Content (Join-Path $PSScriptRoot '..\setup_spark.ps1') -Raw

        $source | Should Match 'print\(json\.dumps\(\{"smoke_ok": False, "error": str\(exc\)\}, indent=2\)\)'
        $source | Should Match 'sys\.exit\(1\)'
        $source | Should Not Match 'except Exception as exc:\s+print\(json\.dumps\(\{"smoke_ok": False, "error": str\(exc\)\}, indent=2\)\)\s+raise'
    }
}

Describe 'Restart-JetsonBridge' {
    It 'requires exactly one bridge process after restart' {
        $source = Get-Content (Join-Path $PSScriptRoot '..\setup_spark.ps1') -Raw

        $source | Should Match 'BRIDGE_COUNT=\$\(pgrep -fc ''\[p\]ico_llm_bridge\.py'''
        $source | Should Match 'bridge restart failed'
        $source | Should Match '\[ "\$\{BRIDGE_COUNT:-0\}" -ne 1 \]'
    }
}

Describe 'Start-SparkApp' {
    It 'launches spark_app_v2.py in a visible PowerShell window by default' {
        $script:RepoRoot = 'C:\SPARK'
        $script:startCall = $null
        $script:statusMessages = @()

        function script:Get-SparkAppProcesses { @() }
        function script:Write-Status {
            param([string]$Label, [string]$Value)
            $script:statusMessages += [pscustomobject]@{ Label = $Label; Value = $Value }
        }
        function script:Start-Process {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [string]$WorkingDirectory
            )

            $script:startCall = [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                WorkingDirectory = $WorkingDirectory
            }
        }

        Start-SparkApp -PythonExe 'C:\SPARK\.venv\Scripts\python.exe'

        $script:startCall.FilePath | Should Be 'powershell.exe'
        $script:startCall.ArgumentList[0] | Should Be '-NoExit'
        $script:startCall.ArgumentList[1] | Should Be '-Command'
        $script:startCall.ArgumentList[2] | Should Match 'spark_app_v2\.py'
        $script:startCall.ArgumentList[2] | Should Match 'python\.exe'
        $script:startCall.WorkingDirectory | Should Be 'C:\SPARK'
        $script:statusMessages[-1].Value | Should Be 'spark_app_v2.py launched in a visible console'
    }

    It 'launches spark_app_v2.py directly when headless launch is requested' {
        $script:RepoRoot = 'C:\SPARK'
        $script:startCall = $null

        function script:Get-SparkAppProcesses { @() }
        function script:Write-Status {}
        function script:Start-Process {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [string]$WorkingDirectory
            )

            $script:startCall = [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                WorkingDirectory = $WorkingDirectory
            }
        }

        Start-SparkApp -PythonExe 'C:\SPARK\.venv\Scripts\python.exe' -HeadlessLaunch

        $script:startCall.FilePath | Should Be 'C:\SPARK\.venv\Scripts\python.exe'
        $script:startCall.ArgumentList | Should Be @('C:\SPARK\spark_app_v2.py')
        $script:startCall.WorkingDirectory | Should Be 'C:\SPARK'
    }

    It 'stops an existing app instance before relaunching' {
        $script:startCall = $null
        $script:stopCalls = 0
        $script:statusMessages = @()

        function script:Get-SparkAppProcesses {
            @([pscustomobject]@{ ProcessId = 1234 })
        }
        function script:Stop-SparkAppProcesses {
            $script:stopCalls += 1
        }
        function script:Write-Status {
            param([string]$Label, [string]$Value)
            $script:statusMessages += [pscustomobject]@{ Label = $Label; Value = $Value }
        }
        function script:Start-Process {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [string]$WorkingDirectory
            )

            $script:startCall = [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                WorkingDirectory = $WorkingDirectory
            }
        }

        Start-SparkApp -PythonExe 'python.exe'

        $script:stopCalls | Should Be 1
        $script:startCall.FilePath | Should Be 'powershell.exe'
        $script:statusMessages[-1].Value | Should Be 'spark_app_v2.py launched in a visible console'
    }
}

Describe 'Start-FullStackWatcher' {
    It 'launches tools/monitoring/watch_full_stack.py in a visible cmd window' {
        $script:RepoRoot = 'C:\SPARK'
        $script:startCall = $null
        $script:statusMessages = @()

        function script:Get-WatchFullStackProcesses { @() }
        function script:Write-Status {
            param([string]$Label, [string]$Value)
            $script:statusMessages += [pscustomobject]@{ Label = $Label; Value = $Value }
        }
        function script:Start-Process {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [string]$WorkingDirectory
            )

            $script:startCall = [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                WorkingDirectory = $WorkingDirectory
            }
        }

        Start-FullStackWatcher -PythonExe 'C:\SPARK\.venv\Scripts\python.exe'

        $script:startCall.FilePath | Should Be 'cmd.exe'
        $script:startCall.ArgumentList[0] | Should Be '/k'
        $script:startCall.ArgumentList[1] | Should Match 'watch_full_stack\.py'
        $script:startCall.ArgumentList[1] | Should Match 'python\.exe'
        $script:startCall.WorkingDirectory | Should Be 'C:\SPARK'
        $script:statusMessages[-1].Value | Should Be 'tools/monitoring/watch_full_stack.py launched in a visible console'
    }

    It 'stops an existing watcher before relaunching' {
        $script:startCall = $null
        $script:stopCalls = 0
        $script:statusMessages = @()

        function script:Get-WatchFullStackProcesses {
            @([pscustomobject]@{ ProcessId = 5678 })
        }
        function script:Stop-WatchFullStackProcesses {
            $script:stopCalls += 1
        }
        function script:Write-Status {
            param([string]$Label, [string]$Value)
            $script:statusMessages += [pscustomobject]@{ Label = $Label; Value = $Value }
        }
        function script:Start-Process {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [string]$WorkingDirectory
            )

            $script:startCall = [pscustomobject]@{
                FilePath = $FilePath
                ArgumentList = $ArgumentList
                WorkingDirectory = $WorkingDirectory
            }
        }

        Start-FullStackWatcher -PythonExe 'python.exe'

        $script:stopCalls | Should Be 1
        $script:startCall.FilePath | Should Be 'cmd.exe'
        $script:statusMessages[-1].Value | Should Be 'tools/monitoring/watch_full_stack.py launched in a visible console'
    }
}
