[CmdletBinding()]
param(
    [switch]$NoPreview,
    [ValidateRange(1, 200)]
    [int]$PreviewLines = 40,
    [Alias('h')]
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

$script:PrivatePreviewPatterns = @(
    '.env',
    '.env.*',
    'data/*',
    '*.db',
    '*.db-wal',
    '*.db-shm',
    '*.log',
    'logs/*',
    '.venv/*',
    '__pycache__/*'
)

function Show-Help {
    Write-Host ''
    Write-Host 'NightPaw Commit Context' -ForegroundColor White
    Write-Host '───────────────────────' -ForegroundColor White
    Write-Host ''
    Write-Host 'Usage:' -ForegroundColor Cyan
    Write-Host '  .\scripts\commit_context.ps1' -ForegroundColor Gray
    Write-Host '  .\scripts\commit_context.ps1 -NoPreview' -ForegroundColor Gray
    Write-Host '  .\scripts\commit_context.ps1 -PreviewLines 40' -ForegroundColor Gray
    Write-Host ''
    Write-Host 'Options:' -ForegroundColor Cyan
    Write-Host '  -NoPreview      Disable tracked diff preview and untracked text previews' -ForegroundColor Gray
    Write-Host '  -PreviewLines   Number of lines to preview from untracked text files' -ForegroundColor Gray
    Write-Host '  -Help, -h       Show this help and exit' -ForegroundColor Gray
    Write-Host ''
    Write-Host 'This script is read-only. It never stages, commits, pushes, deletes, or modifies files.' -ForegroundColor DarkGray
}

function Invoke-GitCapture {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [switch]$AllowEmpty
    )

    $lines = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }

    if ($AllowEmpty) {
        return @($lines)
    }

    return @($lines | Where-Object { -not [string]::IsNullOrWhiteSpace(($_ | Out-String).Trim()) })
}

function Get-TrackedRangeArguments {
    $null = & git rev-parse --verify HEAD 2>$null
    if ($LASTEXITCODE -eq 0) {
        return @('HEAD')
    }
    return @('--cached', '4b825dc642cb6eb9a060e54bf8d69288fbee4904')
}

function Write-Section {
    param(
        [Parameter(Mandatory)]
        [string]$Title,

        [string[]]$Lines
    )

    Write-Host ''
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('-' * $Title.Length) -ForegroundColor DarkGray
    if (-not $Lines -or $Lines.Count -eq 0) {
        Write-Host '(none)' -ForegroundColor DarkGray
        return
    }
    foreach ($line in $Lines) {
        Write-Host $line -ForegroundColor Gray
    }
}

function Test-IsPreviewSafePath {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    foreach ($pattern in $script:PrivatePreviewPatterns) {
        if ($Path -like $pattern) {
            return $false
        }
    }
    return $true
}

function Test-IsReadableTextFile {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
    }
    catch {
        return $false
    }

    if ($bytes.Length -eq 0) {
        return $true
    }

    $sampleLength = [Math]::Min($bytes.Length, 4096)
    for ($i = 0; $i -lt $sampleLength; $i++) {
        if ($bytes[$i] -eq 0) {
            return $false
        }
    }

    return $true
}

function Get-UntrackedFileDetails {
    param(
        [Parameter(Mandatory)]
        [string]$RelativePath
    )

    $fullPath = Join-Path $PWD.Path $RelativePath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        return [pscustomobject]@{
            Path = $RelativePath
            Size = 'missing'
            LineCount = 'n/a'
            Preview = @('file not found')
            IsPreviewable = $false
        }
    }

    $item = Get-Item -LiteralPath $fullPath
    $size = '{0:N0} bytes' -f $item.Length

    if (-not (Test-IsPreviewSafePath -Path $RelativePath)) {
        return [pscustomobject]@{
            Path = $RelativePath
            Size = $size
            LineCount = 'hidden'
            Preview = @('preview skipped (private or ignored pattern)')
            IsPreviewable = $false
        }
    }

    if (-not (Test-IsReadableTextFile -Path $fullPath)) {
        return [pscustomobject]@{
            Path = $RelativePath
            Size = $size
            LineCount = 'binary'
            Preview = @('binary or non-text file')
            IsPreviewable = $false
        }
    }

    $content = Get-Content -LiteralPath $fullPath
    return [pscustomobject]@{
        Path = $RelativePath
        Size = $size
        LineCount = $content.Count
        Preview = @($content | Select-Object -First $PreviewLines)
        IsPreviewable = $true
    }
}

function Get-SuggestedCommitType {
    param(
        [string[]]$ChangedPaths,
        [string[]]$CommitText
    )

    $joinedText = (($CommitText -join "`n") + "`n" + ($ChangedPaths -join "`n")).ToLowerInvariant()
    $hasCogChange = @($ChangedPaths | Where-Object { $_ -like 'cogs/*.py' }).Count -gt 0
    $hasCodeChange = @($ChangedPaths | Where-Object { $_ -like '*.py' }).Count -gt 0
    $onlyDocs = $ChangedPaths.Count -gt 0 -and @($ChangedPaths | Where-Object { $_ -notmatch '^(README\.md|docs/)' }).Count -eq 0
    $hasChoreChange = @($ChangedPaths | Where-Object { $_ -like 'scripts/*' -or $_ -in @('.gitignore', 'pyproject.toml', 'uv.lock') }).Count -gt 0

    if ($joinedText -match 'breaking change|breaking:|!:' ) {
        return 'feat'
    }
    if ($joinedText -match '\b(fix|bug|error|exception|broken)\b') {
        return 'fix'
    }
    if ($onlyDocs) {
        return 'docs'
    }
    if ($hasCogChange -and $joinedText -match '\b(command|slash|feature|add|new|enable|support)\b') {
        return 'feat'
    }
    if ($hasChoreChange -and -not $hasCodeChange) {
        return 'chore'
    }
    if ($ChangedPaths.Count -ge 3 -and $hasCodeChange) {
        return 'refactor'
    }
    if ($hasChoreChange) {
        return 'chore'
    }
    return 'fix'
}

if ($Help) {
    Show-Help
    exit 0
}

try {
    $null = & git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'This script must be run inside a git repository.'
    }

    $trackedRangeArguments = @(Get-TrackedRangeArguments)

    $statusLines = Invoke-GitCapture -Arguments @('status', '--short') -AllowEmpty
    $statusDisplay = if ($statusLines.Count -eq 0) { @('working tree clean') } else { @($statusLines) }

    $diffStatArguments = @('diff', '--stat') + $trackedRangeArguments
    $diffStatLines = Invoke-GitCapture -Arguments $diffStatArguments -AllowEmpty
    $diffStatDisplay = if ($diffStatLines.Count -eq 0) { @('no tracked diff stat') } else { @($diffStatLines) }

    $nameStatusArguments = @('diff', '--name-status') + $trackedRangeArguments
    $nameStatusLines = Invoke-GitCapture -Arguments $nameStatusArguments -AllowEmpty
    $nameStatusDisplay = if ($nameStatusLines.Count -eq 0) { @('no tracked file changes') } else { @($nameStatusLines) }

    $recentCommitLines = Invoke-GitCapture -Arguments @('log', '--oneline', '-n', '5') -AllowEmpty
    $recentCommitDisplay = if ($recentCommitLines.Count -eq 0) { @('no commits found') } else { @($recentCommitLines) }

    $trackedDiffPreview = @()
    if (-not $NoPreview) {
        $trackedDiffArguments = @('diff', '--unified=1') + $trackedRangeArguments
        $trackedDiffPreview = @(Invoke-GitCapture -Arguments $trackedDiffArguments -AllowEmpty | Select-Object -First 120)
    }

    $untrackedPaths = @(Invoke-GitCapture -Arguments @('ls-files', '--others', '--exclude-standard') -AllowEmpty)
    $untrackedDetails = @()
    foreach ($path in $untrackedPaths) {
        $untrackedDetails += Get-UntrackedFileDetails -RelativePath $path
    }

    $changedPaths = @()
    foreach ($line in $nameStatusLines) {
        $text = ($line | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        $parts = $text -split "`t"
        if ($parts.Count -ge 2) {
            $changedPaths += $parts[-1]
        }
    }
    $changedPaths += $untrackedPaths
    $changedPaths = @($changedPaths | Sort-Object -Unique)

    $commitHint = Get-SuggestedCommitType -ChangedPaths $changedPaths -CommitText (@($nameStatusLines) + @($trackedDiffPreview))

    Write-Host ''
    Write-Host 'NightPaw Commit Context' -ForegroundColor White
    Write-Host '───────────────────────' -ForegroundColor White

    Write-Section -Title 'Git Status' -Lines $statusDisplay
    Write-Section -Title 'Diff Stat' -Lines $diffStatDisplay
    Write-Section -Title 'Changed Files (Name Status)' -Lines $nameStatusDisplay

    if (-not $NoPreview) {
        Write-Section -Title 'Tracked Diff Preview' -Lines $(if ($trackedDiffPreview.Count -eq 0) { @('no tracked diff preview') } else { $trackedDiffPreview })
    }

    Write-Host ''
    Write-Host 'Untracked Files' -ForegroundColor Cyan
    Write-Host '---------------' -ForegroundColor DarkGray
    if ($untrackedDetails.Count -eq 0) {
        Write-Host '(none)' -ForegroundColor DarkGray
    }
    else {
        foreach ($detail in $untrackedDetails) {
            Write-Host $detail.Path -ForegroundColor Gray
            Write-Host "  size: $($detail.Size)" -ForegroundColor DarkGray
            Write-Host "  lines: $($detail.LineCount)" -ForegroundColor DarkGray
            if (-not $NoPreview) {
                foreach ($previewLine in $detail.Preview) {
                    Write-Host "  > $previewLine" -ForegroundColor DarkGray
                }
            }
        }
    }

    Write-Section -Title 'Recent Commits' -Lines $recentCommitDisplay
    Write-Section -Title 'Suggested Commit Type' -Lines @("$commitHint (hint only)")

    $copyStatus = if ($statusLines.Count -eq 0) { 'working tree clean' } else { $statusLines -join "`n" }
    $copyChanged = if ($nameStatusLines.Count -eq 0) { 'no tracked changes' } else { $nameStatusLines -join "`n" }
    $copyUntracked = if ($untrackedDetails.Count -eq 0) {
        'none'
    }
    else {
        ($untrackedDetails | ForEach-Object {
            '{0} | {1} | lines: {2}' -f $_.Path, $_.Size, $_.LineCount
        }) -join "`n"
    }
    $copyRecent = if ($recentCommitLines.Count -eq 0) { 'none' } else { $recentCommitLines -join "`n" }

    Write-Host ''
    Write-Host 'Copy this into ChatGPT if you want commit help:' -ForegroundColor Yellow
    Write-Host '```text' -ForegroundColor DarkGray
    Write-Host 'Status:' -ForegroundColor Gray
    Write-Host $copyStatus -ForegroundColor Gray
    Write-Host '' -ForegroundColor Gray
    Write-Host 'Changed files:' -ForegroundColor Gray
    Write-Host $copyChanged -ForegroundColor Gray
    Write-Host '' -ForegroundColor Gray
    Write-Host 'Untracked files:' -ForegroundColor Gray
    Write-Host $copyUntracked -ForegroundColor Gray
    Write-Host '' -ForegroundColor Gray
    Write-Host 'Recent commits:' -ForegroundColor Gray
    Write-Host $copyRecent -ForegroundColor Gray
    Write-Host '' -ForegroundColor Gray
    Write-Host 'Suggested commit type:' -ForegroundColor Gray
    Write-Host $commitHint -ForegroundColor Gray
    Write-Host '```' -ForegroundColor DarkGray
}
catch {
    Write-Error $_
    exit 1
}
