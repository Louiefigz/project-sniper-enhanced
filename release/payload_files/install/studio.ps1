[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$StudioArgs)

$action = if ($StudioArgs.Count) { $StudioArgs[0] } else { '' }
if ($action -notin @('open','status','sync','rebuild','stop','context')) {
    throw 'Usage: studio.cmd open|status|sync|rebuild|stop <project>\producer [options]'
}
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
& "$root\sniper.ps1" python.exe "$root\scripts\producer\studio\studio_review.py" @StudioArgs
exit $LASTEXITCODE
