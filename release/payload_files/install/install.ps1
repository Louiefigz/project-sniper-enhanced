[CmdletBinding()]
param([string]$Workspace, [switch]$Locked)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
. "$PSScriptRoot\lib\windows\Common.ps1"
. "$PSScriptRoot\lib\windows\Runtime.ps1"
. "$PSScriptRoot\lib\windows\MediaJail.ps1"

$modelName = 'ggml-small.en.bin'
$modelSha = 'c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d'

function Write-Receipt([string]$Name, [string]$Value) {
    New-Item -ItemType Directory -Path $script:Receipts -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $script:Receipts $Name) -Value $Value -NoNewline -Encoding UTF8
}

function Test-Receipt([string]$Name, [string]$Value) {
    $file = Join-Path $script:Receipts $Name
    (Test-Path $file) -and ((Get-Content -LiteralPath $file -Raw).Trim() -eq $Value)
}

function Test-Tree([string]$Python, [string]$Root, [string]$Record, [string[]]$Extra) {
    if (-not (Test-Path $Root) -or -not (Test-Path $Record)) { return $false }
    & $Python -I -B $script:InstallTools tree-check $Root $Record @Extra *> $null
    $LASTEXITCODE -eq 0
}

function Record-Tree([string]$Python, [string]$Root, [string]$Record, [string[]]$Extra) {
    & $Python -I -B $script:InstallTools tree-record $Root $Record @Extra *> $null
    if ($LASTEXITCODE -ne 0) { throw "Could not record the installed files under $Root." }
}

function Install-NpmTree([string]$Label, [string]$Root, [string]$Receipt, $Runtime) {
    $key = "node:$(& $Runtime.Tools.Node --version)|lock:$(Get-FileSha256 (Join-Path $Root 'package-lock.json'))"
    $record = Join-Path $script:Receipts "$Receipt.tree.json"
    if ((Test-Receipt $Receipt $key) -and (Test-Tree $Runtime.Tools.Python (Join-Path $Root 'node_modules') $record @('--exclude','.cache'))) {
        Write-Host "$Label — up to date (verified)"
        return
    }
    Remove-Item -LiteralPath (Join-Path $Root 'node_modules') -Recurse -Force -ErrorAction SilentlyContinue
    Push-Location $Root
    try { & $Runtime.Tools.Npm ci --no-audit --no-fund } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Installing $Label failed." }
    Record-Tree $Runtime.Tools.Python (Join-Path $Root 'node_modules') $record @('--exclude','.cache')
    Write-Receipt $Receipt $key
}

function Install-PythonEnvironment($Runtime) {
    $lock = Join-Path $script:PackageRoot 'install\requirements.lock.txt'
    $venv = Join-Path $script:PackageRoot '.venv\Scripts\python.exe'
    $key = "python:$(& $Runtime.Tools.Python --version)|lock:$(Get-FileSha256 $lock)"
    if ((Test-Receipt 'venv' $key) -and (Test-Path $venv)) {
        & $venv -I $script:InstallTools venv-check $lock *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host 'Python environment — up to date (verified)'; return $venv }
    }
    Remove-Item -LiteralPath (Join-Path $script:PackageRoot '.venv') -Recurse -Force -ErrorAction SilentlyContinue
    & $Runtime.Tools.Python -m venv (Join-Path $script:PackageRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    & $venv -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r $lock | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Installing the pinned Python packages failed.' }
    & $venv -I $script:InstallTools venv-check $lock | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'The new Python environment does not verify.' }
    Write-Receipt 'venv' $key
    $venv
}

function Receive-Browser([string]$Python) {
    $release = Get-Content -LiteralPath (Join-Path $script:PackageRoot 'RELEASE.json') -Raw | ConvertFrom-Json
    $version = $release.components.chrome_headless_shell
    $sha = $release.components.chrome_headless_shell_sha256.win64
    $bytes = [long]$release.components.chrome_headless_shell_bytes.win64
    $cache = Join-Path $script:RuntimeDir 'browser'
    $folder = Join-Path $cache "chrome-headless-shell-win64-$version"
    $binary = Join-Path $folder 'chrome-headless-shell-win64\chrome-headless-shell.exe'
    $record = Join-Path $script:Receipts 'browser.tree.json'
    if ((Test-Receipt 'browser' "$version|$sha") -and (Test-Tree $Python $folder $record @())) {
        & $binary --version *> $null
        if ($LASTEXITCODE -eq 0) { return $binary }
    }
    $archive = Join-Path $cache "chrome-headless-shell-win64-$version.zip"
    $url = "https://storage.googleapis.com/chrome-for-testing-public/$version/win64/chrome-headless-shell-win64.zip"
    Receive-VerifiedFile $url $archive $sha $bytes
    Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $archive -DestinationPath $folder -Force
    & $binary --version *> $null
    if ($LASTEXITCODE -ne 0) { throw 'The pinned rendering browser does not start.' }
    Record-Tree $Python $folder $record @()
    Write-Receipt 'browser' "$version|$sha"
    $binary
}

function Receive-SpeechModel {
    $folder = Join-Path $script:RuntimeDir 'whisper'
    $target = Join-Path $folder $modelName
    $url = if ($env:SNIPER_MODEL_URL) { $env:SNIPER_MODEL_URL } else { "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$modelName" }
    Receive-VerifiedFile $url $target $modelSha 487614201
    $target
}

function Write-WindowsSettings($Runtime, [string]$Venv, [string]$Browser, [string]$Model, $Jail) {
    $workspacePath = if ($Workspace) { [IO.Path]::GetFullPath($Workspace) } else { Join-Path $script:PackageRoot 'projects' }
    New-Item -ItemType Directory -Path $workspacePath -Force | Out-Null
    $venvBin = Split-Path $Venv -Parent
    $prefix = $Runtime.Paths.Prefix
    $path = @($venvBin,$prefix,(Join-Path $prefix 'Scripts'),(Join-Path $prefix 'Library\bin'),
        (Join-Path $prefix 'Library\usr\bin'),$env:SystemRoot,(Join-Path $env:SystemRoot 'System32')) -join ';'
    $values = @{
        'PKG_ROOT' = $script:PackageRoot
        'APP_DIR' = $script:PackageRoot
        'PATH' = $path
        'SNIPER_DEPS_PREFIX' = $prefix
        'SNIPER_EXECUTION_MODE' = 'local'
        'SNIPER_WORKSPACE_ROOT' = $workspacePath
        'SNIPER_NODE_PATH' = $Runtime.Tools.Node
        'HYPERFRAMES_BROWSER_PATH' = $Browser
        'HYPERFRAMES_FFMPEG_PATH' = $Runtime.Tools.Ffmpeg
        'HYPERFRAMES_FFPROBE_PATH' = $Runtime.Tools.Ffprobe
        'HYPERFRAMES_NO_TELEMETRY' = '1'
        'NEXT_TELEMETRY_DISABLED' = '1'
        'HYPERFRAMES_NO_UPDATE_CHECK' = '1'
        'HYPERFRAMES_NO_AUTO_INSTALL' = '1'
        'WHISPER_CPP_BIN' = $Runtime.Tools.Whisper
        'WHISPER_CPP_MODEL' = $Model
        'SNIPER_TRANSCRIBE_PROVIDER' = 'local-whisper'
        'SNIPER_STUDIO_COMMAND' = (Join-Path $script:PackageRoot 'install\studio.cmd')
        'SNIPER_WINDOWS_MEDIA_JAIL' = $Jail.Jail
        'SNIPER_WINDOWS_MEDIA_INSPECT' = $Jail.Inspect
    }
    Write-SniperSettings $values
    $workspacePath
}

Assert-WindowsTarget
if (-not $Locked) {
    $bootstrapMutex = [Threading.Mutex]::new($false, 'Local\ProjectSniperInstaller')
    if (-not $bootstrapMutex.WaitOne([TimeSpan]::FromHours(1))) { throw 'Another installer did not finish within one hour.' }
    try {
        Write-Step '1/8  Locked Windows runtime'
        $bootstrapRuntime = Ensure-WindowsRuntime
    } finally {
        $bootstrapMutex.ReleaseMutex(); $bootstrapMutex.Dispose()
    }
    $lock = Join-Path $script:PackageRoot 'scripts\infra\sniper_lock.py'
    $arguments = @($lock,'exec','--state-dir',$script:StateDir,'--mode','exclusive','--label','installer',
        '--wait','0','--busy-message','Sniper cannot be installed while one of its commands is running.','--',
        'powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',$PSCommandPath,'-Locked')
    if ($Workspace) { $arguments += @('-Workspace',$Workspace) }
    & $bootstrapRuntime.Tools.Python @arguments
    exit $LASTEXITCODE
}
$mutex = [Threading.Mutex]::new($false, 'Local\ProjectSniperInstaller')
if (-not $mutex.WaitOne([TimeSpan]::FromHours(1))) { throw 'Another Project Sniper installer did not finish within one hour.' }
try {
    New-Item -ItemType Directory -Path $script:Receipts -Force | Out-Null
    Remove-Item -LiteralPath (Join-Path $script:Receipts 'installed') -Force -ErrorAction SilentlyContinue
    $runtime = Ensure-WindowsRuntime
    Write-Step '2/8  JavaScript dependencies'
    Install-NpmTree 'JavaScript dependencies' $script:PackageRoot 'npm-app' $runtime
    Write-Step '3/8  Rendering-project dependencies'
    Install-NpmTree 'Rendering-project dependencies' (Join-Path $script:PackageRoot 'templates\motion') 'npm-motion' $runtime
    Write-Step '4/8  Pinned Python environment'
    $venv = Install-PythonEnvironment $runtime
    Write-Step '5/8  Rendering browser'
    $browser = Receive-Browser $venv
    Write-Step '6/8  Speech model'
    $model = Receive-SpeechModel
    Write-Step '7/8  Configuration'
    $jail = Install-WindowsMediaJail $runtime
    $workspacePath = Write-WindowsSettings $runtime $venv $browser $model $jail
    Enter-SniperEnvironment (Read-SniperSettings)
    Write-Step '8/8  Rendering runtime'
    & $venv (Join-Path $script:PackageRoot 'scripts\producer\studio\native_runtime.py') --repair
    if ($LASTEXITCODE -ne 0) { throw 'The rendering runtime did not build from the shipped patch set.' }
    Write-Receipt 'installed' $script:PackageRoot
    Write-Host "`nProject Sniper is installed. Video projects: $workspacePath"
    & (Join-Path $script:PackageRoot 'install\doctor.ps1')
    exit $LASTEXITCODE
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
