[CmdletBinding()]
param(
    [string]$Type,
    [string]$Message,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$VerboseOutput,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'nightpaw-dev.ps1'

if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw 'scripts/nightpaw-dev.ps1 was not found.'
}

& $target 'context' @RemainingArgs -Type $Type -Message $Message -Yes:$Yes -DryRun:$DryRun -VerboseOutput:$VerboseOutput
exit $LASTEXITCODE
