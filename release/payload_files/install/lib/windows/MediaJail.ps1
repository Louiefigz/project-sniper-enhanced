Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

function Compile-JailProgram([string]$Source, [string]$Target) {
    $temporary = "$Target.compiling.exe"
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    $text = Get-Content -LiteralPath $Source -Raw
    $compiler = New-Object System.CodeDom.Compiler.CompilerParameters
    $compiler.CompilerOptions = '/optimize+'
    Add-Type -TypeDefinition $text -Language CSharp -OutputAssembly $temporary `
        -OutputType ConsoleApplication -CompilerParameters $compiler | Out-Null
    if (-not (Test-Path $temporary)) { throw "The Windows C# compiler did not create $Target." }
    Move-Item -LiteralPath $temporary -Destination $Target -Force
}

function Install-WindowsMediaJail($Runtime) {
    $sourceDir = Join-Path $script:PackageRoot 'scripts\producer\headless'
    $approvalPath = Join-Path $sourceDir 'windows_media_runtime_approval.json'
    $approval = Get-Content -LiteralPath $approvalPath -Raw | ConvertFrom-Json
    $jailSource = Join-Path $sourceDir 'windows_media_jail.cs'
    $inspectSource = Join-Path $sourceDir 'windows_media_inspect.cs'
    if ((Get-FileSha256 $jailSource) -ne $approval.approved.'windows_media_jail.cs' -or
            (Get-FileSha256 $inspectSource) -ne $approval.approved.'windows_media_inspect.cs') {
        throw 'The Windows media jail source is not the approved source for this release.'
    }
    $folder = Join-Path $script:RuntimeDir 'windows-jail'
    $jail = Join-Path $folder 'windows_media_jail.exe'
    $inspect = Join-Path $folder 'windows_media_inspect.exe'
    $key = "$(Get-FileSha256 $jailSource)|$(Get-FileSha256 $inspectSource)"
    if (-not ((Test-Receipt 'windows-media-jail' $key) -and (Test-Path $jail) -and (Test-Path $inspect))) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        Compile-JailProgram $jailSource $jail
        Compile-JailProgram $inspectSource $inspect
        Write-Receipt 'windows-media-jail' $key
    }
    $sid = (& $jail sid | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or $sid -notmatch '^S-1-15-2-') { throw 'Could not create the media AppContainer profile.' }
    [pscustomobject]@{ Jail=$jail; Inspect=$inspect; Sid=$sid }
}
