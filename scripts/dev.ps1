[CmdletBinding()]
param(
    [Alias('h')]
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

function Show-DevHelp {
    Write-Host ''
    Write-Host 'NightPaw Dev Helper' -ForegroundColor White
    Write-Host '───────────────────' -ForegroundColor White
    Write-Host ''
    Write-Host 'Usage:' -ForegroundColor Cyan
    Write-Host '  .\scripts\dev.ps1' -ForegroundColor Gray
    Write-Host '  .\scripts\dev.ps1 -Help' -ForegroundColor Gray
    Write-Host ''
    Write-Host 'Menu:' -ForegroundColor Cyan
    Write-Host '  1. Show commit context' -ForegroundColor Gray
    Write-Host '  2. Commit changes' -ForegroundColor Gray
    Write-Host '  3. Dry-run release' -ForegroundColor Gray
    Write-Host '  4. Release' -ForegroundColor Gray
    Write-Host '  5. Show release help' -ForegroundColor Gray
    Write-Host '  6. Show git status' -ForegroundColor Gray
    Write-Host '  7. Exit' -ForegroundColor Gray
}

function Invoke-MenuAction {
    param(
        [Parameter(Mandatory)]
        [string]$Selection
    )

    switch ($Selection.Trim()) {
        '1' { & '.\scripts\commit_context.ps1' -NoPreview; return $true }
        '2' { & '.\scripts\commit.ps1'; return $true }
        '3' { & '.\scripts\release.ps1' -DryRun -ShowCommits -ShowFiles; return $true }
        '4' { & '.\scripts\release.ps1'; return $true }
        '5' { & '.\scripts\release.ps1' -Help; return $true }
        '6' { & git status --short; return $true }
        '7' { return $false }
        default {
            Write-Host ''
            Write-Host 'Invalid selection. Choose 1-7.' -ForegroundColor Yellow
            return $true
        }
    }
}

if ($Help) {
    Show-DevHelp
    exit 0
}

try {
    $null = & git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'This script must be run inside a git repository.'
    }

    $keepRunning = $true
    while ($keepRunning) {
        Write-Host ''
        Write-Host 'NightPaw Dev Helper' -ForegroundColor White
        Write-Host '───────────────────' -ForegroundColor White
        Write-Host '1. Show commit context' -ForegroundColor Gray
        Write-Host '2. Commit changes' -ForegroundColor Gray
        Write-Host '3. Dry-run release' -ForegroundColor Gray
        Write-Host '4. Release' -ForegroundColor Gray
        Write-Host '5. Show release help' -ForegroundColor Gray
        Write-Host '6. Show git status' -ForegroundColor Gray
        Write-Host '7. Exit' -ForegroundColor Gray

        $selection = Read-Host 'Choose an option'
        $keepRunning = Invoke-MenuAction -Selection $selection
    }
}
catch {
    Write-Error $_
    exit 1
}
