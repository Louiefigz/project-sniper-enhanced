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
    $packageLock = Join-Path $Root 'package-lock.json'
    $modules = Join-Path $Root 'node_modules'
    $treeArgs = [string[]]@('--exclude', '.cache')
    $key = "node:$(& $Runtime.Tools.Node --version)|lock:$(Get-FileSha256 $packageLock)"
    $record = Join-Path $script:Receipts "$Receipt.tree.json"
    $receiptMatches = Test-Receipt $Receipt $key
    $treeMatches = $false
    if ($receiptMatches) {
        $treeMatches = Test-Tree $Runtime.Tools.Python $modules $record $treeArgs
    }
    if ($receiptMatches -and $treeMatches) {
        Write-Host "$Label - up to date (verified)"
        return
    }
    Remove-Item -LiteralPath $modules -Recurse -Force -ErrorAction SilentlyContinue
    Push-Location $Root
    try { $code = Invoke-SniperNative $Runtime.Tools.Npm @('ci','--no-audit','--no-fund') } finally { Pop-Location }
    if ($code -ne 0) { throw "Installing $Label failed." }
    Record-Tree $Runtime.Tools.Python $modules $record $treeArgs
    Write-Receipt $Receipt $key
}

function Install-PythonEnvironment($Runtime) {
    $lock = Join-Path $script:PackageRoot 'install\requirements.lock.txt'
    $venv = Join-Path $script:PackageRoot '.venv\Scripts\python.exe'
    $key = "python:$(& $Runtime.Tools.Python --version)|lock:$(Get-FileSha256 $lock)"
    if ((Test-Receipt 'venv' $key) -and (Test-Path $venv)) {
        & $venv -I $script:InstallTools venv-check $lock *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host 'Python environment - up to date (verified)'; return $venv }
    }
    Remove-Item -LiteralPath (Join-Path $script:PackageRoot '.venv') -Recurse -Force -ErrorAction SilentlyContinue
    $venvRoot = Join-Path $script:PackageRoot '.venv'
    if ((Invoke-SniperNative $Runtime.Tools.Python @('-m','venv',$venvRoot)) -ne 0) {
        throw 'Could not create the Python environment.'
    }
    $pipArgs = @('-m','pip','install','--disable-pip-version-check','--no-input','--require-hashes',
        '--only-binary=:all:','-r',$lock)
    if ((Invoke-SniperNative $venv $pipArgs) -ne 0) { throw 'Installing the pinned Python packages failed.' }
    if ((Invoke-SniperNative $venv @('-I',$script:InstallTools,'venv-check',$lock)) -ne 0) {
        throw 'The new Python environment does not verify.'
    }
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
    $receiptMatches = Test-Receipt 'browser' "$version|$sha"
    $treeMatches = $false
    if ($receiptMatches) {
        $treeMatches = Test-Tree $Python $folder $record ([string[]]@())
    }
    if ($receiptMatches -and $treeMatches) {
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
    Record-Tree $Python $folder $record ([string[]]@())
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
    $prefixScripts = Join-Path $prefix 'Scripts'
    $prefixBin = Join-Path $prefix 'Library\bin'
    $prefixUsrBin = Join-Path $prefix 'Library\usr\bin'
    $systemBin = Join-Path $env:SystemRoot 'System32'
    $path = @($venvBin, $prefix, $prefixScripts, $prefixBin, $prefixUsrBin,
        $env:SystemRoot, $systemBin) -join ';'
    $studioCommand = Join-Path $script:PackageRoot 'install\studio.cmd'
    $values = New-Object -TypeName System.Collections.Hashtable
    $values.Add('PKG_ROOT', $script:PackageRoot)
    $values.Add('APP_DIR', $script:PackageRoot)
    $values.Add('PATH', $path)
    $values.Add('SNIPER_DEPS_PREFIX', $prefix)
    $values.Add('SNIPER_EXECUTION_MODE', 'local')
    $values.Add('SNIPER_WORKSPACE_ROOT', $workspacePath)
    $values.Add('SNIPER_NODE_PATH', $Runtime.Tools.Node)
    $values.Add('HYPERFRAMES_BROWSER_PATH', $Browser)
    $values.Add('HYPERFRAMES_FFMPEG_PATH', $Runtime.Tools.Ffmpeg)
    $values.Add('HYPERFRAMES_FFPROBE_PATH', $Runtime.Tools.Ffprobe)
    $values.Add('HYPERFRAMES_NO_TELEMETRY', '1')
    $values.Add('NEXT_TELEMETRY_DISABLED', '1')
    $values.Add('HYPERFRAMES_NO_UPDATE_CHECK', '1')
    $values.Add('HYPERFRAMES_NO_AUTO_INSTALL', '1')
    $values.Add('WHISPER_CPP_BIN', $Runtime.Tools.Whisper)
    $values.Add('WHISPER_CPP_MODEL', $Model)
    $values.Add('SNIPER_TRANSCRIBE_PROVIDER', 'local-whisper')
    $values.Add('SNIPER_STUDIO_COMMAND', $studioCommand)
    $values.Add('SNIPER_WINDOWS_MEDIA_JAIL', $Jail.Jail)
    $values.Add('SNIPER_WINDOWS_MEDIA_INSPECT', $Jail.Inspect)
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
    exit (Invoke-SniperNative $bootstrapRuntime.Tools.Python $arguments)
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
    $repair = Join-Path $script:PackageRoot 'scripts\producer\studio\native_runtime.py'
    if ((Invoke-SniperNative $venv @($repair,'--repair')) -ne 0) {
        throw 'The rendering runtime did not build from the shipped patch set.'
    }
    Write-Receipt 'installed' $script:PackageRoot
    Write-Host "`nProject Sniper is installed. Video projects: $workspacePath"
    & (Join-Path $script:PackageRoot 'install\doctor.ps1')
    exit $LASTEXITCODE
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
