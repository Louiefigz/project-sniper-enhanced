[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Command)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

if ($Command.Count -eq 0) {
    Write-Error 'usage: sniper.cmd setup | doctor | workspace | <command> [args...]'
    exit 64
}
if ($Command[0] -eq 'setup') {
    & "$root\install\install.ps1" @($Command | Select-Object -Skip 1)
    exit $LASTEXITCODE
}
if ($Command[0] -eq 'doctor') {
    & "$root\install\doctor.ps1" @($Command | Select-Object -Skip 1)
    exit $LASTEXITCODE
}

. "$root\install\lib\windows\Common.ps1"
$settings = Read-SniperSettings
$installed = Join-Path $script:Receipts 'installed'
if (-not (Test-Path $installed) -or (Get-Content -LiteralPath $installed -Raw).Trim() -ne $root) {
    throw 'Sniper setup is incomplete or this folder moved. Run sniper.cmd setup.'
}
if ($Command[0] -eq 'workspace') {
    $settings['SNIPER_WORKSPACE_ROOT']
    exit 0
}
Enter-SniperEnvironment $settings
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Sniper is not set up. Run sniper.cmd setup.'
}
$lock = Join-Path $root 'scripts\infra\sniper_lock.py'
$state = Join-Path $root 'runtime\state'
if ($Command[0] -eq 'connections') {
    $setup = Join-Path $root 'install\lib\deepgram_setup.py'
    & $python $lock exec --state-dir $state --mode exclusive --label 'connection setup' `
        --busy-message 'A Sniper command is running. Let it finish, then try again.' -- `
        $python $setup @($Command | Select-Object -Skip 1)
    exit $LASTEXITCODE
}
& $python $lock exec --state-dir $state --mode shared --label "sniper $($Command[0])" `
    --busy-message 'Sniper is being installed, repaired, cleaned or removed.' -- @Command
exit $LASTEXITCODE
