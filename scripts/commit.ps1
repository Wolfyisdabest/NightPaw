[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$commitTypes = @('feat', 'fix', 'chore', 'docs', 'refactor')

function Invoke-Git {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

try {
    $null = & git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'This script must be run inside a git repository.'
    }

    Write-Host ''
    Write-Host 'NightPaw Commit Helper' -ForegroundColor White
    Write-Host '──────────────────────' -ForegroundColor White
    Write-Host 'Choose a commit type:' -ForegroundColor Cyan
    for ($i = 0; $i -lt $commitTypes.Count; $i++) {
        Write-Host "$($i + 1). $($commitTypes[$i])" -ForegroundColor Gray
    }

    $selectionInput = (Read-Host 'Type number').Trim()
    if ([string]::IsNullOrWhiteSpace($selectionInput)) {
        throw 'Invalid selection. Enter the number for the commit type.'
    }

    $selection = 0
    if (-not [int]::TryParse($selectionInput, [ref]$selection)) {
        throw 'Invalid selection. Enter the number for the commit type.'
    }

    if ($selection -lt 1 -or $selection -gt $commitTypes.Count) {
        throw 'Selection out of range.'
    }

    $type = $commitTypes[$selection - 1]
    $message = (Read-Host 'Message').Trim()
    if ([string]::IsNullOrWhiteSpace($message)) {
        throw 'Commit message cannot be empty.'
    }

    $fullMessage = '{0}: {1}' -f $type, $message

    Write-Host ''
    Write-Host "Committing as: $fullMessage" -ForegroundColor Yellow

    Invoke-Git -Arguments @('add', '.')
    Invoke-Git -Arguments @('commit', '-m', $fullMessage)
    Invoke-Git -Arguments @('push')

    Write-Host ''
    Write-Host 'Commit and push completed.' -ForegroundColor Green
}
catch {
    Write-Error $_
    exit 1
}
