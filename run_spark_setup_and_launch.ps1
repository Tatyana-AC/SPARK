[CmdletBinding()]
param(
    [string]$JetsonHost = "192.168.55.1",
    [string]$JetsonUser = "sidac",
    [string]$JetsonMountLetter = "Z",
    [string]$JetsonRemotePath = "/mnt/usb_drive",
    [int]$JetsonMountCommandTimeoutSeconds = 30,
    [int]$JetsonSshConnectTimeoutSeconds = 10,
    [int]$BridgeSettleSeconds = 10,
    [switch]$SkipSmokeTest,
    [switch]$SkipAppLaunch,
    [switch]$HeadlessAppLaunch
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupScript = Join-Path $RepoRoot "setup_spark.ps1"

if (-not (Test-Path $SetupScript)) {
    throw "Could not find setup_spark.ps1 at $SetupScript"
}

Set-Location $RepoRoot

& $SetupScript `
    -JetsonHost $JetsonHost `
    -JetsonUser $JetsonUser `
    -JetsonMountLetter $JetsonMountLetter `
    -JetsonRemotePath $JetsonRemotePath `
    -JetsonMountCommandTimeoutSeconds $JetsonMountCommandTimeoutSeconds `
    -JetsonSshConnectTimeoutSeconds $JetsonSshConnectTimeoutSeconds `
    -BridgeSettleSeconds $BridgeSettleSeconds `
    -SkipSmokeTest:$SkipSmokeTest `
    -SkipAppLaunch:$SkipAppLaunch `
    -HeadlessAppLaunch:$HeadlessAppLaunch
