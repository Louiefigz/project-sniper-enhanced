Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

function Get-RuntimePaths {
    $id = (Get-FileSha256 $script:LockFile).Substring(0, 16)
    $runtimeHome = Join-Path $env:LOCALAPPDATA 'ProjectSniper'
    [pscustomobject]@{
        Id=$id; Home=$runtimeHome; Cache=(Join-Path $runtimeHome 'packages')
        Prefix=(Join-Path $runtimeHome "runtimes\$id")
        Record=(Join-Path $runtimeHome "runtimes\$id.tree.json"); Tools=(Join-Path $runtimeHome 'tools')
    }
}

function Get-ToolPath([string]$Prefix, [string[]]$Candidates, [string]$Name) {
    foreach ($relative in $Candidates) {
        $path = Join-Path $Prefix $relative
        if (Test-Path $path) { return $path }
    }
    $found = Get-ChildItem -LiteralPath $Prefix -Filter $Name -File -Recurse | Select-Object -First 1
    if (-not $found) { throw "The locked runtime did not install $Name." }
    $found.FullName
}

function Get-RuntimeTools([string]$Prefix) {
    @{
        Python=(Get-ToolPath $Prefix @('python.exe') 'python.exe')
        Node=(Get-ToolPath $Prefix @('node.exe','Library\bin\node.exe') 'node.exe')
        Npm=(Get-ToolPath $Prefix @('npm.cmd','Scripts\npm.cmd','Library\bin\npm.cmd') 'npm.cmd')
        Ffmpeg=(Get-ToolPath $Prefix @('Library\bin\ffmpeg.exe','ffmpeg.exe') 'ffmpeg.exe')
        Ffprobe=(Get-ToolPath $Prefix @('Library\bin\ffprobe.exe','ffprobe.exe') 'ffprobe.exe')
        Whisper=(Get-ToolPath $Prefix @('Library\bin\whisper-cli.exe','whisper-cli.exe') 'whisper-cli.exe')
        Tesseract=(Get-ToolPath $Prefix @('Library\bin\tesseract.exe','tesseract.exe') 'tesseract.exe')
        YtDlp=(Get-ToolPath $Prefix @('Scripts\yt-dlp.exe','yt-dlp.exe') 'yt-dlp.exe')
        Git=(Get-ToolPath $Prefix @('Library\bin\git.exe','Library\cmd\git.exe','git.exe') 'git.exe')
    }
}

function Receive-RuntimePackages($Paths, [object[]]$Rows) {
    $downloads = @($Rows | Where-Object { $_.Kind -in @('micromamba','conda','download') })
    $number = 0
    foreach ($row in $downloads) {
        $number++
        $target = Join-Path $Paths.Cache ($row.Path -replace '/', '\')
        Write-Host "[$number/$($downloads.Count)] $($row.Path)"
        Receive-VerifiedFile $row.Source $target $row.Sha $row.Bytes
    }
}

function Install-CondaRuntime($Paths, [object[]]$Rows) {
    $mambaRow = $Rows | Where-Object Kind -eq 'micromamba' | Select-Object -First 1
    $binRow = $Rows | Where-Object Kind -eq 'micromamba-bin' | Select-Object -First 1
    $archive = Join-Path $Paths.Cache ($mambaRow.Path -replace '/', '\')
    $mambaDir = Join-Path $Paths.Tools "micromamba-$($Paths.Id)"
    $mamba = Join-Path $mambaDir 'Library\bin\micromamba.exe'
    if (-not (Test-Path $mamba) -or (Get-FileSha256 $mamba) -ne $binRow.Sha) {
        Remove-Item -LiteralPath $mambaDir -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $mambaDir -Force | Out-Null
        & tar.exe -xjf $archive -C $mambaDir 'Library/bin/micromamba.exe'
        if ($LASTEXITCODE -ne 0 -or (Get-FileSha256 $mamba) -ne $binRow.Sha) { throw 'Pinned micromamba did not extract correctly.' }
    }
    $runtimes = Join-Path $Paths.Home 'runtimes'
    New-Item -ItemType Directory -Path $runtimes -Force | Out-Null
    $explicit = Join-Path $runtimes "$($Paths.Id).explicit.txt"
    $lines = @('@EXPLICIT')
    foreach ($row in ($Rows | Where-Object Kind -eq 'conda')) {
        $file = Join-Path $Paths.Cache ($row.Path -replace '/', '\')
        $lines += "$(([Uri]$file).AbsoluteUri)#sha256:$($row.Sha)"
    }
    Set-Content -LiteralPath $explicit -Value $lines -Encoding ASCII
    Remove-Item -LiteralPath $Paths.Prefix -Recurse -Force -ErrorAction SilentlyContinue
    $env:MAMBA_ROOT_PREFIX = Join-Path $Paths.Home 'mamba-root'
    $arguments = @('create','--no-rc','-y','-q','-p',$Paths.Prefix,'--offline','--platform','win-64',
        '--always-copy','--file',$explicit)
    if ((Invoke-SniperNative $mamba $arguments) -ne 0) {
        throw 'Installing the checked Windows runtime packages failed.'
    }
}

function Install-WindowsFfmpeg($Paths, [object[]]$Rows) {
    $row = $Rows | Where-Object Kind -eq 'download' | Select-Object -First 1
    if (-not $row) { throw 'The Windows runtime lock has no FFmpeg download.' }
    $archive = Join-Path $Paths.Cache ($row.Path -replace '/', '\')
    $extract = Join-Path $Paths.Home "ffmpeg-$($Paths.Id)-extracting"
    Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    $root = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
    $destination = Join-Path $Paths.Prefix 'Library\bin'
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root.FullName 'bin\ffmpeg.exe') -Destination $destination
    Copy-Item -LiteralPath (Join-Path $root.FullName 'bin\ffprobe.exe') -Destination $destination
    Copy-Item -LiteralPath (Join-Path $root.FullName 'LICENSE.txt') -Destination (Join-Path $Paths.Prefix 'FFMPEG-LICENSE.txt')
    Remove-Item -LiteralPath $extract -Recurse -Force
}

function Assert-ToolStarts([string]$Path, [string]$Argument, [string]$Name) {
    $previous = $ErrorActionPreference
    try {
        # Windows PowerShell 5 turns native stderr into error records. Several
        # healthy tools print version/help text there, so trust the exit code.
        $ErrorActionPreference = 'Continue'
        & $Path $Argument *> $null
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "$Name does not start from the locked runtime." }
}

function Test-RuntimeTools([hashtable]$Tools) {
    foreach ($entry in $Tools.GetEnumerator()) {
        $arg = if ($entry.Key -in @('Python','Node','YtDlp')) { '--version' } else { '-version' }
        if ($entry.Key -eq 'Npm') { $arg = '--version' }
        if ($entry.Key -eq 'Git') { $arg = '--version' }
        if ($entry.Key -eq 'Whisper') { $arg = '--help' }
        if ($entry.Key -eq 'Tesseract') { $arg = '--version' }
        Assert-ToolStarts $entry.Value $arg $entry.Key
    }
    $filters = & $Tools.Ffmpeg -hide_banner -filters 2>&1 | Out-String
    foreach ($name in @('rubberband','zscale','subtitles','arnndn','loudnorm')) {
        if ($filters -notmatch "(?m)\s$name\s") { throw "The pinned FFmpeg lacks $name." }
    }
}

function Ensure-WindowsRuntime {
    $rows = @(Read-RuntimeLock)
    $paths = Get-RuntimePaths
    $marker = Join-Path $paths.Prefix '.sniper-runtime-complete'
    if ((Test-Path $marker) -and (Get-Content -LiteralPath $marker -Raw).Trim() -eq $paths.Id) {
        $tools = Get-RuntimeTools $paths.Prefix
        Test-RuntimeTools $tools
        return [pscustomobject]@{ Paths=$paths; Tools=$tools }
    }
    Receive-RuntimePackages $paths $rows
    Install-CondaRuntime $paths $rows
    Install-WindowsFfmpeg $paths $rows
    $tools = Get-RuntimeTools $paths.Prefix
    Test-RuntimeTools $tools
    & $tools.Python -I -B $script:InstallTools tree-record $paths.Prefix $paths.Record --exclude var/cache/fontconfig --exclude-name __pycache__ --exclude-file .sniper-runtime-complete | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not record the installed runtime.' }
    Set-Content -LiteralPath $marker -Value $paths.Id -NoNewline -Encoding ASCII
    [pscustomobject]@{ Paths=$paths; Tools=$tools }
}
