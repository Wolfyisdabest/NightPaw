[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version,

    [switch]$Auto,
    [switch]$Apply,
    [switch]$Force,
    [switch]$CreateGitHubRelease
)

$ErrorActionPreference = 'Stop'
$ImportantPaths = @(
    'main.py',
    'config.py',
    'checks.py',
    'pyproject.toml',
    'uv.lock',
    'services/ai_service.py',
    'services/ai_state.py',
    'services/runtime_intelligence.py',
    'cogs/ai.py',
    'cogs/sysadmin.py',
    'cogs/moderation.py',
    'cogs/automod.py'
)
$EmptyTreeHash = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

function Invoke-GitCapture {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )
    $output = & git @Args 2>$null
    if ($LASTEXITCODE -ne 0) {
        Fail ("git " + ($Args -join ' ') + " failed.")
    }
    return @($output)
}

function Invoke-GitStreaming {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        Fail ("git " + ($Args -join ' ') + " failed.")
    }
}

function Assert-CleanWorkingTree {
    $status = Invoke-GitCapture @('status', '--porcelain')
    if (-not [string]::IsNullOrWhiteSpace(($status | Out-String))) {
        Fail "Working tree is not clean. Commit or stash changes before creating a release."
    }
}

function Assert-ValidVersion([string]$Tag) {
    if ($Tag -notmatch '^v\d+\.\d+\.\d+$') {
        Fail "Version must use simple semantic tag format: vMAJOR.MINOR.PATCH"
    }
}

function Get-LatestReachableTag {
    $tag = & git describe --tags --abbrev=0 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    $trimmed = ($tag | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        return $null
    }
    return $trimmed
}

function Get-NextPatchVersion([string]$LatestTag) {
    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        return 'v0.1.0'
    }
    if ($LatestTag -notmatch '^v(\d+)\.(\d+)\.(\d+)$') {
        Fail "Latest tag '$LatestTag' is not a simple semantic tag. Supply a manual version."
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    $patch = [int]$Matches[3] + 1
    return "v$major.$minor.$patch"
}

function Assert-TagDoesNotExist([string]$Tag) {
    $existing = Invoke-GitCapture @('tag', '--list', $Tag)
    if (-not [string]::IsNullOrWhiteSpace(($existing | Out-String))) {
        Fail "Tag $Tag already exists."
    }
}

function Get-ComparisonBase([string]$LatestTag) {
    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        return $EmptyTreeHash
    }
    return $LatestTag
}

function Get-ReleaseStats([string]$BaseRef, [string]$LatestTag) {
    $commitLines = Invoke-GitCapture @('log', '--oneline', "$BaseRef..HEAD")
    $commitCount = @($commitLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count

    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        $commitCount = [int](Invoke-GitCapture @('rev-list', '--count', 'HEAD') | Select-Object -First 1)
    }

    $numstatLines = Invoke-GitCapture @('diff', '--numstat', "$BaseRef..HEAD")
    $changedFiles = 0
    $inserted = 0
    $deleted = 0
    $changedPaths = New-Object System.Collections.Generic.List[string]

    foreach ($line in $numstatLines) {
        $text = ($line | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        $parts = $text -split "`t", 3
        if ($parts.Count -lt 3) {
            continue
        }
        $changedFiles += 1
        if ($parts[0] -match '^\d+$') {
            $inserted += [int]$parts[0]
        }
        if ($parts[1] -match '^\d+$') {
            $deleted += [int]$parts[1]
        }
        $changedPaths.Add($parts[2])
    }

    $importantChanged = @(
        $changedPaths | Where-Object { $ImportantPaths -contains $_ } | Sort-Object -Unique
    )

    return [pscustomobject]@{
        CommitCount = $commitCount
        ChangedFiles = $changedFiles
        InsertedLines = $inserted
        DeletedLines = $deleted
        TotalChangedLines = ($inserted + $deleted)
        ChangedPaths = @($changedPaths)
        ImportantChanged = @($importantChanged)
        CommitLines = @($commitLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
}

function Get-Recommendation([pscustomobject]$Stats) {
    $reasons = New-Object System.Collections.Generic.List[string]
    if ($Stats.CommitCount -ge 5) {
        $reasons.Add("5 or more commits since the last tag")
    }
    if ($Stats.ChangedFiles -ge 8) {
        $reasons.Add("8 or more tracked files changed")
    }
    if ($Stats.TotalChangedLines -ge 250) {
        $reasons.Add("250 or more total changed lines")
    }
    if ($Stats.ImportantChanged.Count -gt 0) {
        $reasons.Add("important project files changed")
    }

    return [pscustomobject]@{
        Recommended = ($reasons.Count -gt 0)
        Reasons = @($reasons)
    }
}

function Get-ReleaseNotes([string]$BaseRef, [string]$LatestTag) {
    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        $lines = Invoke-GitCapture @('log', '--oneline', '--reverse', 'HEAD')
    }
    else {
        $lines = Invoke-GitCapture @('log', '--oneline', "$BaseRef..HEAD")
    }
    return @($lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function New-Release([string]$Tag, [switch]$CreateGitHubRelease, [string[]]$ReleaseNotes) {
    $headCommit = (Invoke-GitCapture @('rev-parse', '--short', 'HEAD') | Select-Object -First 1).Trim()
    Write-Host "Creating annotated tag $Tag on commit $headCommit..."
    Invoke-GitStreaming @('tag', '-a', $Tag, '-m', "NightPaw $Tag")

    Write-Host "Pushing tag $Tag to origin..."
    Invoke-GitStreaming @('push', 'origin', $Tag)

    if (-not $CreateGitHubRelease) {
        Write-Host "Tag pushed. GitHub release creation was not requested."
        return
    }

    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -eq $gh) {
        Write-Warning "GitHub CLI (gh) is not available. Tag was pushed, but no GitHub release was created."
        return
    }

    $notesFile = [System.IO.Path]::GetTempFileName()
    try {
        if ($ReleaseNotes.Count -gt 0) {
            @(
                "Source snapshot for $Tag"
                ""
                "Changes since previous tag:"
                $ReleaseNotes
            ) | Set-Content -Path $notesFile -Encoding UTF8
        }
        else {
            @(
                "Source snapshot for $Tag"
                ""
                "No commit log entries were found for this release range."
            ) | Set-Content -Path $notesFile -Encoding UTF8
        }

        Write-Host "Creating GitHub release $Tag..."
        & $gh.Source release create $Tag --verify-tag --title "NightPaw $Tag" --notes-file $notesFile
        if ($LASTEXITCODE -ne 0) {
            Fail "gh release create failed."
        }
    }
    finally {
        Remove-Item $notesFile -ErrorAction SilentlyContinue
    }

    Write-Host "Release $Tag completed."
}

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    Fail "This script must be run inside a git repository."
}

Set-Location $repoRoot.Trim()
Assert-CleanWorkingTree

if (-not $Auto -and [string]::IsNullOrWhiteSpace($Version)) {
    Fail "Provide a version like v0.1.0, or use -Auto."
}

$latestTag = Get-LatestReachableTag
$baseRef = Get-ComparisonBase $latestTag
$stats = Get-ReleaseStats -BaseRef $baseRef -LatestTag $latestTag
$recommendation = Get-Recommendation $stats
$releaseNotes = Get-ReleaseNotes -BaseRef $baseRef -LatestTag $latestTag

if (-not [string]::IsNullOrWhiteSpace($Version)) {
    Assert-ValidVersion $Version
}

if ($Auto) {
    $proposedVersion = if ([string]::IsNullOrWhiteSpace($Version)) { Get-NextPatchVersion $latestTag } else { $Version }
    Assert-TagDoesNotExist $proposedVersion

    $why = if ($recommendation.Recommended) {
        $recommendation.Reasons
    }
    else {
        @("thresholds not met and no important project files changed")
    }
    $latestTagLabel = if ([string]::IsNullOrWhiteSpace($latestTag)) { 'none (initial release)' } else { $latestTag }

    Write-Host ""
    Write-Host "NightPaw release recommendation"
    Write-Host "-----------------------------"
    Write-Host "Latest tag: $latestTagLabel"
    Write-Host "Proposed next version: $proposedVersion"
    Write-Host "Commits since tag: $($stats.CommitCount)"
    Write-Host "Changed tracked files: $($stats.ChangedFiles)"
    Write-Host "Inserted lines: $($stats.InsertedLines)"
    Write-Host "Deleted lines: $($stats.DeletedLines)"
    Write-Host "Total changed lines: $($stats.TotalChangedLines)"
    Write-Host "Important files changed: $(if ($stats.ImportantChanged.Count) { $stats.ImportantChanged -join ', ' } else { 'none' })"
    Write-Host "Release recommended: $(if ($recommendation.Recommended) { 'yes' } else { 'no' })"
    Write-Host "Why: $($why -join '; ')"

    $applyCommand = "pwsh -File .\scripts\release.ps1 $proposedVersion"
    if ($CreateGitHubRelease) {
        $applyCommand += " -CreateGitHubRelease"
    }
    $applyCommand += " -Auto -Apply"
    if ($Force) {
        $applyCommand += " -Force"
    }
    Write-Host "Apply command: $applyCommand"
    Write-Host ""

    if (-not $Apply) {
        exit 0
    }

    if (-not $recommendation.Recommended -and -not $Force) {
        Fail "Auto mode did not recommend a release. Re-run with -Force if you still want to create $proposedVersion."
    }

    New-Release -Tag $proposedVersion -CreateGitHubRelease:$CreateGitHubRelease -ReleaseNotes $releaseNotes
    exit 0
}

Assert-TagDoesNotExist $Version
New-Release -Tag $Version -CreateGitHubRelease:$CreateGitHubRelease -ReleaseNotes $releaseNotes
