[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DoctorArgs)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib\windows\Common.ps1"
$settings = Read-SniperSettings
Enter-SniperEnvironment $settings
$python = Join-Path $script:PackageRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'The Python environment is missing. Run sniper.cmd setup.' }
& $python (Join-Path $script:PackageRoot 'install\sniper_doctor.py') @DoctorArgs
exit $LASTEXITCODE
