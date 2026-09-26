[CmdletBinding()]
param([switch]$Yes, [switch]$Locked)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib\windows\Common.ps1"

if (-not $Locked -and (Test-Path (Join-Path $script:PackageRoot '.venv\Scripts\python.exe'))) {
    $python = Join-Path $script:PackageRoot '.venv\Scripts\python.exe'
    $lock = Join-Path $script:PackageRoot 'scripts\infra\sniper_lock.py'
    $arguments = @($lock,'exec','--state-dir',$script:StateDir,'--mode','exclusive','--label','uninstall',
        '--busy-message','Sniper cannot be removed while one of its commands is running.','--',
        'powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',$PSCommandPath,'-Locked')
    if ($Yes) { $arguments += '-Yes' }
    & $python @arguments
    exit $LASTEXITCODE
}

$settings = if (Test-Path $script:SettingsFile) { Read-SniperSettings } else { @{} }
$workspace = if ($settings.ContainsKey('SNIPER_WORKSPACE_ROOT')) {
    $settings['SNIPER_WORKSPACE_ROOT']
} else { Join-Path $script:PackageRoot 'projects' }
Write-Host 'This removes the runtime, dependencies, Python environment and caches created inside this folder.'
Write-Host "It does not remove video projects at $workspace."
if (-not $Yes) {
    $answer = Read-Host 'Type REMOVE to continue'
    if ($answer -ne 'REMOVE') { Write-Host 'Nothing was removed.'; exit 0 }
}

$runtime = Join-Path $script:PackageRoot 'runtime'
$local = Join-Path $runtime 'sniper.local.env'
$localBytes = if (Test-Path $local) { [IO.File]::ReadAllBytes($local) } else { $null }
$history = Join-Path $script:PackageRoot 'templates\motion\.sniper-native-runtime\native-export-history'
$targets = @(
    (Join-Path $script:PackageRoot 'node_modules'),
    (Join-Path $script:PackageRoot 'templates\motion\node_modules'),
    (Join-Path $script:PackageRoot '.venv'),
    (Join-Path $script:PackageRoot '.next'),
    $runtime
)
foreach ($target in $targets) {
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
}
$runtimeCache = Split-Path $history -Parent
if (Test-Path $runtimeCache) {
    Get-ChildItem -LiteralPath $runtimeCache -Force | Where-Object FullName -ne $history | Remove-Item -Recurse -Force
}
if ($localBytes) {
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    [IO.File]::WriteAllBytes($local, $localBytes)
}
Write-Host 'Project Sniper installation files were removed. Your projects and optional local settings were kept.'
