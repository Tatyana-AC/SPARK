Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot '..\setup_spark.ps1')

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
