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
    It 'falls back to SSH directory checks when the mapped Jetson path is inaccessible' {
        $script:remoteChecks = @()
        $script:servicesStarted = 0
        $script:SkipSmokeTest = $true
        $script:SkipAppLaunch = $true

        function script:Write-Section {}
        function script:Write-Status {}
        function script:Get-RepoPython { 'python' }
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
        $script:servicesStarted | Should Be 1
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
