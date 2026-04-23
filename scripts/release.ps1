[CmdletBinding()]
param(
    [ValidatePattern('^v\d+\.\d+\.\d+$')]
    [string]$Version,

    [ValidateSet('major', 'minor', 'patch')]
    [string]$Bump,

    [string]$ReleaseDate,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$Scheduled,
    [switch]$Force
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

$script:RepoRoot = $null
$script:LogPath = $null
$script:ModeLabel = 'manual'

function Write-ReleaseLog {
    param(
        [string]$Level,
        [string]$Message
    )

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$timestamp] [$Level] mode=$script:ModeLabel $Message"
    if ($script:LogPath) {
        Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
    }
    Write-Host $line
}

function Fail {
    param(
        [string]$Message,
        [int]$ExitCode = 1
    )
    Write-ReleaseLog -Level 'ERROR' -Message $Message
    exit $ExitCode
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

function Initialize-Logging {
    $logsDir = Join-Path $script:RepoRoot 'logs'
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    $script:LogPath = Join-Path $logsDir 'release-helper.log'
    Write-ReleaseLog -Level 'INFO' -Message 'release helper started'
}

function Assert-SemVerTag([string]$Tag, [string]$Label = 'tag') {
    if ($Tag -notmatch '^v\d+\.\d+\.\d+$') {
        Fail "$Label '$Tag' is not a simple semantic tag. Use vMAJOR.MINOR.PATCH."
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

function Get-ReleaseDateText([string]$Override) {
    if ([string]::IsNullOrWhiteSpace($Override)) {
        return (Get-Date).ToString('dd/MM/yyyy')
    }

    $parsed = $null
    if (-not [datetime]::TryParseExact(
        $Override,
        @('dd/MM/yyyy'),
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::None,
        [ref]$parsed
    )) {
        Fail "ReleaseDate must use dd/MM/yyyy format, for example 24/04/2026."
    }
    return $parsed.ToString('dd/MM/yyyy')
}

function Get-ComparisonBase([string]$LatestTag) {
    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        return $EmptyTreeHash
    }
    return $LatestTag
}

function Parse-VersionParts([string]$Tag) {
    Assert-SemVerTag $Tag 'Latest tag'
    if ($Tag -notmatch '^v(\d+)\.(\d+)\.(\d+)$') {
        Fail "Unable to parse version parts from $Tag."
    }
    return [pscustomobject]@{
        Major = [int]$Matches[1]
        Minor = [int]$Matches[2]
        Patch = [int]$Matches[3]
    }
}

function Get-NextVersion([string]$LatestTag, [string]$BumpType) {
    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        return 'v1.0.0'
    }

    $parts = Parse-VersionParts $LatestTag
    switch ($BumpType) {
        'major' { return "v$($parts.Major + 1).0.0" }
        'minor' { return "v$($parts.Major).$($parts.Minor + 1).0" }
        default { return "v$($parts.Major).$($parts.Minor).$($parts.Patch + 1)" }
    }
}

function Assert-TagDoesNotExist([string]$Tag) {
    $existing = Invoke-GitCapture tag --list $Tag
    if (-not [string]::IsNullOrWhiteSpace(($existing | Out-String))) {
        Fail "Tag $Tag already exists."
    }
}

function Get-ReleaseStats([string]$BaseRef, [string]$LatestTag) {
    $logFormat = '%H%x09%s'
    $commitMeta = Invoke-GitCapture log --format=$logFormat "$BaseRef..HEAD"
    $commitCount = @($commitMeta | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count

    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        $commitCount = [int](Invoke-GitCapture rev-list --count HEAD | Select-Object -First 1)
        $commitMeta = Invoke-GitCapture log --format=$logFormat --reverse HEAD
    }

    $numstatLines = Invoke-GitCapture diff --numstat "$BaseRef..HEAD"
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

    $importantChanged = @($changedPaths | Where-Object { $ImportantPaths -contains $_ } | Sort-Object -Unique)
    $messages = New-Object System.Collections.Generic.List[string]
    $logLines = New-Object System.Collections.Generic.List[string]
    foreach ($entry in $commitMeta) {
        $text = ($entry | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        $parts = $text -split "`t", 2
        if ($parts.Count -eq 2) {
            $messages.Add($parts[1])
            $short = (Invoke-GitCapture rev-parse --short $parts[0] | Select-Object -First 1).Trim()
            $logLines.Add("$short $($parts[1])")
        }
    }

    return [pscustomobject]@{
        CommitCount = $commitCount
        ChangedFiles = $changedFiles
        InsertedLines = $inserted
        DeletedLines = $deleted
        TotalChangedLines = ($inserted + $deleted)
        ImportantChanged = @($importantChanged)
        CommitMessages = @($messages)
        CommitLines = @($logLines)
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

function Get-BumpType([string[]]$CommitMessages, [pscustomobject]$Recommendation) {
    foreach ($message in $CommitMessages) {
        $m = $message.Trim()
        if ($m -match 'BREAKING CHANGE' -or $m -match 'breaking:' -or $m -match '!:' ) {
            return 'major'
        }
    }
    foreach ($message in $CommitMessages) {
        if ($message.Trim() -match '^feat:') {
            return 'minor'
        }
    }
    foreach ($message in $CommitMessages) {
        if ($message.Trim() -match '^(fix|docs|refactor|chore|style|test):') {
            return 'patch'
        }
    }
    if ($Recommendation.Recommended) {
        return 'patch'
    }
    return 'patch'
}

function Get-ReleaseNotes([string[]]$CommitLines, [string]$Tag) {
    if ($CommitLines.Count -gt 0) {
        return @(
            "Source snapshot for $Tag"
            ""
            "Changes since previous tag:"
            $CommitLines
        )
    }
    return @(
        "Source snapshot for $Tag"
        ""
        "No commit log entries were found for this release range."
    )
}

function Show-Report(
    [string]$LatestTag,
    [string]$ProposedVersion,
    [string]$BumpType,
    [string]$ReleaseTitle,
    [pscustomobject]$Stats,
    [pscustomobject]$Recommendation,
    [bool]$ManualOverride
) {
    $latestLabel = if ([string]::IsNullOrWhiteSpace($LatestTag)) { 'none (initial release)' } else { $LatestTag }
    $why = if ($Recommendation.Recommended) { $Recommendation.Reasons } else { @('thresholds not met and no important project files changed') }

    Write-ReleaseLog -Level 'INFO' -Message "latest_tag=$latestLabel"
    Write-ReleaseLog -Level 'INFO' -Message "proposed_version=$ProposedVersion"
    Write-ReleaseLog -Level 'INFO' -Message "release_title=$ReleaseTitle"
    Write-ReleaseLog -Level 'INFO' -Message "bump_type=$BumpType"
    Write-ReleaseLog -Level 'INFO' -Message "commits_since_tag=$($Stats.CommitCount) changed_files=$($Stats.ChangedFiles) inserted=$($Stats.InsertedLines) deleted=$($Stats.DeletedLines) total_changed=$($Stats.TotalChangedLines)"
    Write-ReleaseLog -Level 'INFO' -Message "important_files_changed=$(if ($Stats.ImportantChanged.Count) { $Stats.ImportantChanged -join ', ' } else { 'none' })"
    Write-ReleaseLog -Level 'INFO' -Message "release_recommended=$(if ($Recommendation.Recommended) { 'yes' } else { 'no' }) reasons=$($why -join '; ')"
    Write-ReleaseLog -Level 'INFO' -Message "manual_override=$(if ($ManualOverride) { 'yes' } else { 'no' })"
}

function Test-CanPrompt {
    if ($Scheduled -or $Yes -or $DryRun) {
        return $false
    }
    if (-not [Environment]::UserInteractive) {
        return $false
    }
    if ([Environment]::CommandLine -match '(?i)(^|\s)-NonInteractive(\s|$)') {
        return $false
    }
    try {
        $null = $Host.UI.RawUI
    }
    catch {
        return $false
    }
    try {
        if ([Console]::IsInputRedirected) {
            return $false
        }
    }
    catch {
        return $false
    }
    return $true
}

function Confirm-Release([string]$ReleaseTitle) {
    if ($Scheduled) {
        return $true
    }
    if ($Yes) {
        return $true
    }
    if (-not (Test-CanPrompt)) {
        Write-ReleaseLog -Level 'WARN' -Message "prompt required but input is unavailable; exiting without creating release"
        exit 0
    }
    $answer = Read-Host "Create GitHub release $ReleaseTitle? [y/N]"
    return ($answer -match '^(y|yes)$')
}

function New-Release([string]$Tag, [string]$ReleaseTitle, [string[]]$ReleaseNotes) {
    $headCommit = (Invoke-GitCapture rev-parse --short HEAD | Select-Object -First 1).Trim()
    Write-ReleaseLog -Level 'INFO' -Message "tag_creation_started tag=$Tag commit=$headCommit"
    Invoke-GitStreaming tag -a $Tag -m "NightPaw $Tag"
    Write-ReleaseLog -Level 'INFO' -Message "tag_creation_result=success tag=$Tag"

    Write-ReleaseLog -Level 'INFO' -Message "tag_push_started tag=$Tag remote=origin"
    Invoke-GitStreaming push origin $Tag
    Write-ReleaseLog -Level 'INFO' -Message "tag_push_result=success tag=$Tag"

    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -eq $gh) {
        Write-ReleaseLog -Level 'WARN' -Message 'github_release_result=skipped reason=gh_not_available'
        return
    }

    $notesFile = [System.IO.Path]::GetTempFileName()
    try {
        $ReleaseNotes | Set-Content -Path $notesFile -Encoding UTF8
        Write-ReleaseLog -Level 'INFO' -Message "github_release_started title=$ReleaseTitle"
        & $gh.Source release create $Tag --verify-tag --title $ReleaseTitle --notes-file $notesFile
        if ($LASTEXITCODE -ne 0) {
            Fail "GitHub release creation failed after tag push."
        }
        Write-ReleaseLog -Level 'INFO' -Message "github_release_result=success title=$ReleaseTitle"
    }
    finally {
        Remove-Item $notesFile -ErrorAction SilentlyContinue
    }
}

$script:ModeLabel = if ($Scheduled) { 'scheduled' } elseif ($DryRun) { 'dry-run' } elseif ($Yes) { 'yes' } else { 'manual' }

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    Write-Error "This script must be run inside a git repository."
    exit 1
}
$script:RepoRoot = $repoRoot.Trim()
Set-Location $script:RepoRoot
Initialize-Logging

if ($Scheduled -and $Force) {
    Write-ReleaseLog -Level 'WARN' -Message 'scheduled mode does not allow -Force; exiting without creating release'
    exit 0
}

$status = Invoke-GitCapture status --porcelain
if (-not [string]::IsNullOrWhiteSpace(($status | Out-String))) {
    $dirtyMessage = 'working tree is dirty'
    if ($Scheduled) {
        Write-ReleaseLog -Level 'INFO' -Message "$dirtyMessage; scheduled mode exits cleanly without release"
        exit 0
    }
    Fail "$dirtyMessage. Commit or stash changes before creating a release."
}

if (-not [string]::IsNullOrWhiteSpace($Version)) {
    Assert-SemVerTag $Version 'Version'
}

$latestTag = Get-LatestReachableTag
if (-not [string]::IsNullOrWhiteSpace($latestTag)) {
    Assert-SemVerTag $latestTag 'Latest tag'
}

$baseRef = Get-ComparisonBase $latestTag
$stats = Get-ReleaseStats -BaseRef $baseRef -LatestTag $latestTag
$recommendation = Get-Recommendation $stats
$autoBump = Get-BumpType -CommitMessages $stats.CommitMessages -Recommendation $recommendation
$effectiveBump = if ([string]::IsNullOrWhiteSpace($Bump)) { $autoBump } else { $Bump }
$manualOverride = (-not [string]::IsNullOrWhiteSpace($Version)) -or (-not [string]::IsNullOrWhiteSpace($Bump)) -or $Force
$proposedVersion = if ([string]::IsNullOrWhiteSpace($Version)) { Get-NextVersion -LatestTag $latestTag -BumpType $effectiveBump } else { $Version }
$releaseDateText = Get-ReleaseDateText $ReleaseDate
$releaseTitle = "NightPaw $proposedVersion — $releaseDateText"
$releaseNotes = Get-ReleaseNotes -CommitLines $stats.CommitLines -Tag $proposedVersion

Assert-TagDoesNotExist $proposedVersion
Show-Report -LatestTag $latestTag -ProposedVersion $proposedVersion -BumpType $effectiveBump -ReleaseTitle $releaseTitle -Stats $stats -Recommendation $recommendation -ManualOverride:$manualOverride

if ($DryRun) {
    Write-ReleaseLog -Level 'INFO' -Message 'dry run only; no tag or GitHub release was created'
    exit 0
}

if ($Scheduled) {
    if (-not $recommendation.Recommended) {
        Write-ReleaseLog -Level 'INFO' -Message 'scheduled mode found no recommended release; exiting cleanly'
        exit 0
    }
    New-Release -Tag $proposedVersion -ReleaseTitle $releaseTitle -ReleaseNotes $releaseNotes
    exit 0
}

if (-not $recommendation.Recommended -and -not $manualOverride) {
    Write-ReleaseLog -Level 'INFO' -Message 'no release created because the script does not recommend one right now'
    exit 0
}

if (-not (Confirm-Release -ReleaseTitle $releaseTitle)) {
    Write-ReleaseLog -Level 'INFO' -Message 'user declined release creation'
    exit 0
}

New-Release -Tag $proposedVersion -ReleaseTitle $releaseTitle -ReleaseNotes $releaseNotes
