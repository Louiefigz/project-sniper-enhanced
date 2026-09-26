Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

$script:PackageRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$script:RuntimeDir = Join-Path $script:PackageRoot 'runtime'
$script:StateDir = Join-Path $script:RuntimeDir 'state'
$script:Receipts = Join-Path $script:StateDir 'receipts'
$script:SettingsFile = Join-Path $script:RuntimeDir 'sniper.env'
$script:LockFile = Join-Path $script:PackageRoot 'install\deps\win-64.lock'
$script:InstallTools = Join-Path $script:PackageRoot 'install\lib\install_tools.py'

function Write-Step([string]$Text) {
    Write-Host "`n== $Text"
}

function Get-FileSha256([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-WindowsTarget {
    if ($env:OS -ne 'Windows_NT') {
        throw 'Project Sniper Windows setup must run on Windows.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'Project Sniper requires 64-bit Windows.'
    }
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt 19045) {
        throw "Project Sniper requires Windows 10 22H2 (build 19045) or newer; this PC is build $build."
    }
}

function Read-RuntimeLock {
    if (-not (Test-Path $script:LockFile)) { throw 'The win-64 runtime lock is missing.' }
    $rows = @()
    foreach ($line in Get-Content -LiteralPath $script:LockFile) {
        if (-not $line -or $line.StartsWith('#')) { continue }
        $parts = $line -split '\s+', 5
        if ($parts.Count -ne 5) { throw "Malformed runtime lock row: $line" }
        $rows += [pscustomobject]@{ Kind=$parts[0]; Sha=$parts[1]; Bytes=[long]$parts[2]; Path=$parts[3]; Source=$parts[4] }
    }
    $rows
}

function Receive-VerifiedFile([string]$Url, [string]$Target, [string]$Sha, [long]$Bytes) {
    if (Test-Path $Target) {
        $item = Get-Item -LiteralPath $Target
        if ($item.Length -eq $Bytes -and (Get-FileSha256 $Target) -eq $Sha) { return }
        Remove-Item -LiteralPath $Target -Force
    }
    $parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $part = "$Target.part"
    Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
    Invoke-WebRequest -Uri $Url -OutFile $part -UseBasicParsing
    $item = Get-Item -LiteralPath $part
    if ($item.Length -ne $Bytes -or (Get-FileSha256 $part) -ne $Sha) {
        Remove-Item -LiteralPath $part -Force
        throw "Downloaded file failed its pinned size or SHA-256 check: $Url"
    }
    Move-Item -LiteralPath $part -Destination $Target
}

function Read-SniperSettings {
    if (-not (Test-Path $script:SettingsFile)) { throw 'Sniper is not set up. Run sniper.cmd setup.' }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $script:SettingsFile) {
        if (-not $line -or $line.StartsWith('#')) { continue }
        $at = $line.IndexOf('=')
        if ($at -lt 1) { throw 'runtime\sniper.env contains an invalid line.' }
        $values[$line.Substring(0, $at)] = $line.Substring($at + 1)
    }
    $values
}

function Enter-SniperEnvironment([hashtable]$Settings) {
    foreach ($pair in $Settings.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($pair.Key, $pair.Value, 'Process')
    }
    $env:PKG_ROOT = $script:PackageRoot
    $env:APP_DIR = $script:PackageRoot
    $connection = Join-Path $script:RuntimeDir 'deepgram.env'
    if (Test-Path $connection) {
        foreach ($line in Get-Content -LiteralPath $connection) {
            if (-not $line -or $line.StartsWith('#')) { continue }
            $at = $line.IndexOf('=')
            if ($at -gt 0) { [Environment]::SetEnvironmentVariable($line.Substring(0,$at),$line.Substring($at+1),'Process') }
        }
    }
    foreach ($name in @('PYTHONHOME','PYTHONPATH','PYTHONSTARTUP','PYTHONUSERBASE','NODE_OPTIONS','NODE_PATH',
            'CONDA_PREFIX','CONDA_DEFAULT_ENV','MAMBA_ROOT_PREFIX','OPENAI_API_KEY','ANTHROPIC_API_KEY')) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

function Write-SniperSettings([hashtable]$Values) {
    New-Item -ItemType Directory -Path $script:RuntimeDir -Force | Out-Null
    $lines = @('# sniper-settings-v1 — written by install\install.ps1; values are literal')
    foreach ($key in ($Values.Keys | Sort-Object)) {
        if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$' -or $Values[$key] -match '[\x00-\x1f\x7f]') {
            throw "Cannot store invalid setting $key."
        }
        $lines += "$key=$($Values[$key])"
    }
    $temporary = "$script:SettingsFile.tmp"
    Set-Content -LiteralPath $temporary -Value $lines -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $script:SettingsFile -Force
}
