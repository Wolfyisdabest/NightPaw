[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command,

    [string]$Type,
    [string]$Message,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$VerboseOutput,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$script:CommitTypes = @('feat', 'fix', 'docs', 'refactor', 'chore', 'test', 'build', 'ci', 'perf')
$script:SensitivePatterns = @(
    '.env',
    '.env.*',
    '*.db',
    '*.db-wal',
    '*.db-shm',
    '*.log',
    'logs/*',
    '.venv/*',
    'venv/*',
    '__pycache__/*',
    'data/*'
)
$script:ReleaseImportantExact = @(
    'main.py',
    'config.py',
    'checks.py',
    'pyproject.toml',
    'uv.lock',
    'README.md'
)
$script:ReleaseImportantPatterns = @(
    'services/*.py',
    'cogs/*.py',
    'crates/*',
    'docs/*'
)

function Write-Header {
    param([string]$Title)

    Write-Host ''
    Write-Host $Title -ForegroundColor White
    Write-Host ('=' * $Title.Length) -ForegroundColor DarkGray
}

function Write-Section {
    param([string]$Title)

    Write-Host ''
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('-' * $Title.Length) -ForegroundColor DarkGray
}

function Write-InfoLine {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Gray
}

function Write-SuccessLine {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Green
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Yellow
}

function Write-ErrorLine {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Test-IsGitRepository {
    $null = & git rev-parse --show-toplevel 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Assert-GitRepository {
    if (-not (Test-IsGitRepository)) {
        throw 'This script must be run inside a git repository.'
    }
}

function Get-RepoRoot {
    Assert-GitRepository
    $result = Invoke-Git -Arguments @('rev-parse', '--show-toplevel')
    $root = @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1)
    if (@($root).Count -eq 0) {
        throw 'Unable to determine git repository root.'
    }
    return ([string]$root[0]).Trim()
}

function Invoke-Git {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $stderrPath = [System.IO.Path]::GetTempFileName()
    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & git @Arguments 2> $stderrPath
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorPreference
        $stderrLines = @()
        if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            $stderrLines = @(Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue)
        }

        if (-not $AllowFailure -and $exitCode -ne 0) {
            $joined = $Arguments -join ' '
            $detail = ((@($output) + @($stderrLines)) | Out-String).Trim()
            if ([string]::IsNullOrWhiteSpace($detail)) {
                throw "git $joined failed with exit code $exitCode."
            }
            throw "git $joined failed with exit code $exitCode.`n$detail"
        }

        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = @($output | ForEach-Object { "$_" })
            ErrorOutput = @($stderrLines | ForEach-Object { "$_" })
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
        Remove-Item -LiteralPath $stderrPath -ErrorAction SilentlyContinue
    }
}

function Test-CommandAvailable {
    param([string]$Name)

    return ($null -ne (Get-Command $Name -ErrorAction SilentlyContinue))
}

function Get-PythonCommand {
    $repoRoot = Get-RepoRoot
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }
    if (Test-CommandAvailable -Name 'python') {
        return 'python'
    }
    return $null
}

function Get-PythonCandidates {
    $repoRoot = Get-RepoRoot
    $candidates = @()
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

    if (Test-CommandAvailable -Name 'python') {
        $candidates += [pscustomobject]@{ Command = 'python'; PrefixArgs = @() }
    }
    if (Test-CommandAvailable -Name 'py') {
        $candidates += [pscustomobject]@{ Command = 'py'; PrefixArgs = @('-3') }
    }
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $candidates += [pscustomobject]@{ Command = $venvPython; PrefixArgs = @() }
    }

    return @($candidates)
}

function Invoke-PythonCandidates {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    $lastFailure = $null
    foreach ($candidate in (Get-PythonCandidates)) {
        try {
            & $candidate.Command @($candidate.PrefixArgs + $Arguments)
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{
                    Success = $true
                    Command = $candidate.Command
                    PrefixArgs = @($candidate.PrefixArgs)
                    ExitCode = 0
                }
            }

            $lastFailure = [pscustomobject]@{
                Success = $false
                Command = $candidate.Command
                PrefixArgs = @($candidate.PrefixArgs)
                ExitCode = $LASTEXITCODE
            }
        }
        catch {
            $lastFailure = [pscustomobject]@{
                Success = $false
                Command = $candidate.Command
                PrefixArgs = @($candidate.PrefixArgs)
                ExitCode = 1
            }
        }
    }

    if ($null -eq $lastFailure) {
        return [pscustomobject]@{
            Success = $false
            Command = $null
            PrefixArgs = @()
            ExitCode = 1
        }
    }

    return $lastFailure
}

function Test-IsSensitivePath {
    param([string]$Path)

    foreach ($pattern in $script:SensitivePatterns) {
        if ($Path -like $pattern) {
            return $true
        }
    }
    return $false
}

function Test-IsReleaseImportantPath {
    param([string]$Path)

    if ($script:ReleaseImportantExact -contains $Path) {
        return $true
    }

    foreach ($pattern in $script:ReleaseImportantPatterns) {
        if ($Path -like $pattern) {
            return $true
        }
    }

    return $false
}

function Get-StatusCategory {
    param([string]$Line)

    if ($Line -match '^\?\? ') {
        return 'added'
    }
    if ($Line.Length -lt 3) {
        return 'modified'
    }

    $xy = $Line.Substring(0, 2)
    $x = $xy[0]
    $y = $xy[1]

    if ($x -eq 'R' -or $y -eq 'R' -or $Line -match ' -> ') {
        return 'renamed'
    }
    if ($x -eq 'D' -or $y -eq 'D') {
        return 'deleted'
    }
    if ($x -eq 'A' -or $y -eq 'A' -or $x -eq 'C' -or $y -eq 'C') {
        return 'added'
    }
    return 'modified'
}

function Get-StatusPath {
    param([string]$Line)

    if ($Line -match '^\?\? (?<path>.+)$') {
        return $Matches['path'].Trim()
    }
    if ($Line.Length -ge 4) {
        return $Line.Substring(3).Trim()
    }
    return $Line.Trim()
}

function Get-GitStatus {
    Assert-GitRepository
    $statusResult = Invoke-Git -Arguments @('status', '--porcelain')
    $lines = @($statusResult.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $groups = [ordered]@{
        modified = New-Object System.Collections.Generic.List[string]
        added = New-Object System.Collections.Generic.List[string]
        deleted = New-Object System.Collections.Generic.List[string]
        renamed = New-Object System.Collections.Generic.List[string]
    }

    foreach ($line in $lines) {
        $category = Get-StatusCategory -Line $line
        $path = Get-StatusPath -Line $line
        $groups[$category].Add($path)
    }

    $summary = [ordered]@{
        modified = $groups.modified.Count
        added = $groups.added.Count
        deleted = $groups.deleted.Count
        renamed = $groups.renamed.Count
    }

    return [pscustomobject]@{
        Lines = $lines
        Groups = $groups
        Summary = $summary
        IsClean = ($lines.Count -eq 0)
    }
}

function Get-ChangedFiles {
    $status = Get-GitStatus
    $allPaths = @(
        $status.Groups.modified +
        $status.Groups.added +
        $status.Groups.deleted +
        $status.Groups.renamed
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique

    return [pscustomobject]@{
        Modified = @($status.Groups.modified)
        Added = @($status.Groups.added)
        Deleted = @($status.Groups.deleted)
        Renamed = @($status.Groups.renamed)
        All = @($allPaths)
    }
}

function Get-DiffStat {
    Assert-GitRepository

    $repoRoot = Get-RepoRoot
    $hasHead = ((Invoke-Git -Arguments @('rev-parse', '--verify', 'HEAD') -AllowFailure).ExitCode -eq 0)
    $base = if ($hasHead) { 'HEAD' } else { '4b825dc642cb6eb9a060e54bf8d69288fbee4904' }
    $result = Invoke-Git -Arguments @('diff', '--stat', $base, '--')
    $lines = @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $status = Get-GitStatus
    if ($status.Groups.added.Count -gt 0) {
        $untrackedNotes = @()
        foreach ($path in $status.Groups.added) {
            $fullPath = Join-Path $repoRoot $path
            if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
                try {
                    $lineCount = (Get-Content -LiteralPath $fullPath -ErrorAction Stop | Measure-Object -Line).Lines
                    $untrackedNotes += "{0} | new file preview: {1} lines" -f $path, $lineCount
                }
                catch {
                    $untrackedNotes += "{0} | new file preview unavailable" -f $path
                }
            }
        }
        if ($untrackedNotes.Count -gt 0) {
            $lines += 'Untracked files not shown in git diff stat:'
            $lines += $untrackedNotes
        }
    }

    if ($lines.Count -eq 0) {
        $lines = @('No tracked diff stat available.')
    }

    return $lines
}

function Get-RecentCommitSubjects {
    param([int]$Count = 8)

    Assert-GitRepository
    $result = Invoke-Git -Arguments @('log', '--pretty=format:%s', '-n', "$Count") -AllowFailure
    if ($result.ExitCode -ne 0) {
        return @()
    }
    return @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-SuggestedCommitType {
    param(
        [string[]]$ChangedPaths,
        [string[]]$RecentCommitSubjects
    )

    if (-not $ChangedPaths -or $ChangedPaths.Count -eq 0) {
        return 'chore'
    }

    $normalized = @($ChangedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.ToLowerInvariant() })
    $docsOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(readme\.md|docs/)' }).Count -eq 0)
    $testsOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(tests/|test_.*\.py$)' }).Count -eq 0)
    $scriptsOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(scripts/|readme\.md|docs/)' }).Count -eq 0)
    $ciOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(\.github/|github/)' }).Count -eq 0)
    $hasRustHelper = @($normalized | Where-Object {
        $_ -like 'crates/*' -or $_ -eq 'services/rust_bridge.py' -or $_ -eq 'tests/test_rust_bridge.py'
    }).Count -gt 0
    $hasBuildFiles = @($normalized | Where-Object { $_ -in @('pyproject.toml', 'uv.lock', 'cargo.toml', 'cargo.lock') }).Count -gt 0
    $hasPerfHints = @($normalized | Where-Object { $_ -like 'crates/*' -or $_ -match 'perf|optimi|cache' }).Count -gt 0
    $hasUserFacingCode = @($normalized | Where-Object {
        $_ -eq 'main.py' -or $_ -eq 'config.py' -or $_ -eq 'checks.py' -or $_ -like 'services/*.py' -or $_ -like 'cogs/*.py'
    }).Count -gt 0
    $recentText = ((@($RecentCommitSubjects | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join "`n")).ToLowerInvariant()

    if ($docsOnly) { return 'docs' }
    if ($testsOnly) { return 'test' }
    if ($ciOnly) { return 'ci' }
    if ($scriptsOnly) { return 'chore' }
    if ($hasRustHelper) { return 'feat' }
    if ($hasBuildFiles -and -not $hasUserFacingCode) { return 'build' }
    if ($hasPerfHints -and $recentText -match 'perf') { return 'perf' }
    if ($hasUserFacingCode) { return 'feat' }
    if ($hasBuildFiles) { return 'build' }
    return 'refactor'
}

function Get-SuggestedCommitMessage {
    param(
        [string]$CommitType,
        [string[]]$ChangedPaths
    )

    $normalized = @($ChangedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.ToLowerInvariant() })

    if (@($normalized | Where-Object {
        $_ -like 'crates/*' -or $_ -eq 'services/rust_bridge.py' -or $_ -eq 'tests/test_rust_bridge.py'
    }).Count -gt 0) {
        return 'add optional Rust-backed service helpers'
    }
    if (($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(readme\.md|docs/)' }).Count -eq 0)) {
        return 'update developer documentation'
    }
    if (($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^scripts/' }).Count -eq 0)) {
        return 'unify developer console helper workflow'
    }

    switch ($CommitType) {
        'docs' { return 'update project documentation' }
        'test' { return 'add coverage for current changes' }
        'build' { return 'update development dependencies' }
        'ci' { return 'adjust CI workflow behavior' }
        'refactor' { return 'refactor internal helper flow' }
        'chore' { return 'refresh development tooling' }
        'perf' { return 'improve helper performance' }
        'fix' { return 'fix current helper behavior' }
        default { return 'add developer workflow improvements' }
    }
}

function Get-CommitTypeMenuSelection {
    param([string]$SuggestedType)

    Write-Section 'Commit Type'
    Write-InfoLine '1. feat'
    Write-InfoLine '2. fix'
    Write-InfoLine '3. docs'
    Write-InfoLine '4. refactor'
    Write-InfoLine '5. chore'
    Write-InfoLine '6. test'
    Write-InfoLine '7. build'
    Write-InfoLine '8. ci'
    Write-InfoLine '9. perf'
    Write-InfoLine ("10. use suggested type ({0})" -f $SuggestedType)
    Write-InfoLine '11. custom type'
    Write-InfoLine '12. cancel'

    while ($true) {
        $raw = (Read-Host 'Choose commit type').Trim()
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $SuggestedType
        }

        $value = 0
        if (-not [int]::TryParse($raw, [ref]$value)) {
            Write-WarnLine 'Enter a number from 1 to 12.'
            continue
        }

        switch ($value) {
            1 { return 'feat' }
            2 { return 'fix' }
            3 { return 'docs' }
            4 { return 'refactor' }
            5 { return 'chore' }
            6 { return 'test' }
            7 { return 'build' }
            8 { return 'ci' }
            9 { return 'perf' }
            10 { return $SuggestedType }
            11 {
                while ($true) {
                    $custom = (Read-Host 'Custom commit type').Trim()
                    if (-not [string]::IsNullOrWhiteSpace($custom)) {
                        return $custom
                    }
                    Write-WarnLine 'Custom type cannot be empty.'
                }
            }
            12 { return $null }
            default { Write-WarnLine 'Enter a number from 1 to 12.' }
        }
    }
}

function Confirm-Action {
    param(
        [string]$Prompt,
        [switch]$AssumeYes
    )

    if ($AssumeYes) {
        return $true
    }

    $answer = (Read-Host $Prompt).Trim()
    return ($answer -match '^(?i:y|yes)$')
}

function Show-ChangedFileGroups {
    param([pscustomobject]$ChangedFiles)

    Write-Section 'Changed Files'
    foreach ($entry in @(
        @{ Name = 'Modified'; Values = @($ChangedFiles.Modified) }
        @{ Name = 'Added/Untracked'; Values = @($ChangedFiles.Added) }
        @{ Name = 'Deleted'; Values = @($ChangedFiles.Deleted) }
        @{ Name = 'Renamed'; Values = @($ChangedFiles.Renamed) }
    )) {
        Write-Host $entry.Name -ForegroundColor White
        if ($entry.Values.Count -eq 0) {
            Write-Host '  (none)' -ForegroundColor DarkGray
            continue
        }
        foreach ($path in $entry.Values) {
            Write-Host ("  {0}" -f $path) -ForegroundColor Gray
        }
    }
}

function Show-ProjectStatus {
    Assert-GitRepository
    $status = Get-GitStatus
    $changed = Get-ChangedFiles
    $diffStat = Get-DiffStat

    Write-Header 'NightPaw Project Status'
    if ($status.IsClean) {
        Write-SuccessLine 'Working tree is clean.'
    }
    else {
        Write-InfoLine ("Modified: {0} | Added/Untracked: {1} | Deleted: {2} | Renamed: {3}" -f
            $status.Summary.modified,
            $status.Summary.added,
            $status.Summary.deleted,
            $status.Summary.renamed)
    }

    Show-ChangedFileGroups -ChangedFiles $changed

    Write-Section 'Diff Stat'
    foreach ($line in $diffStat) {
        Write-InfoLine $line
    }
}

function Show-CommitContext {
    Assert-GitRepository
    $changed = Get-ChangedFiles
    $recentCommits = Get-RecentCommitSubjects -Count 8
    $suggestedType = Get-SuggestedCommitType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits
    $suggestedMessage = Get-SuggestedCommitMessage -CommitType $suggestedType -ChangedPaths $changed.All

    Show-ProjectStatus

    Write-Section 'Recent Commits'
    if ($recentCommits.Count -eq 0) {
        Write-InfoLine '(none)'
    }
    else {
        foreach ($line in $recentCommits) {
            Write-InfoLine $line
        }
    }

    Write-Section 'Commit Suggestion'
    Write-InfoLine ("Suggested type: {0}" -f $suggestedType)
    Write-InfoLine ("Suggested subject: {0}" -f $suggestedMessage)
}

function Invoke-CommitFlow {
    param(
        [string]$CommitType,
        [string]$CommitMessage,
        [switch]$AssumeYes
    )

    Assert-GitRepository
    $status = Get-GitStatus
    if ($status.IsClean) {
        Write-WarnLine 'Working tree is clean. Nothing to commit.'
        return
    }

    $changed = Get-ChangedFiles
    $recentCommits = Get-RecentCommitSubjects -Count 8
    $suggestedType = Get-SuggestedCommitType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits
    $suggestedMessage = Get-SuggestedCommitMessage -CommitType $suggestedType -ChangedPaths $changed.All

    Show-CommitContext

    if ([string]::IsNullOrWhiteSpace($CommitType)) {
        $CommitType = Get-CommitTypeMenuSelection -SuggestedType $suggestedType
        if ($null -eq $CommitType) {
            Write-WarnLine 'Commit canceled.'
            return
        }
    }

    if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
        $defaultMessage = $suggestedMessage
        while ($true) {
            $rawMessage = Read-Host ("Commit subject [{0}]" -f $defaultMessage)
            $CommitMessage = if ([string]::IsNullOrWhiteSpace($rawMessage)) { $defaultMessage } else { $rawMessage.Trim() }
            if (-not [string]::IsNullOrWhiteSpace($CommitMessage)) {
                break
            }
            Write-WarnLine 'Commit subject cannot be empty.'
        }
    }

    $finalMessage = '{0}: {1}' -f $CommitType.Trim(), $CommitMessage.Trim()
    Write-Section 'Commit Preview'
    Write-InfoLine $finalMessage

    if (-not (Confirm-Action -Prompt 'Commit with this message? [y/N]' -AssumeYes:$AssumeYes)) {
        Write-WarnLine 'Commit canceled.'
        return
    }

    Invoke-Git -Arguments @('add', '--all') | Out-Null
    Invoke-Git -Arguments @('commit', '-m', $finalMessage) | Out-Null

    Write-SuccessLine 'Commit created successfully.'
    Write-InfoLine 'No push was performed.'
}

function Get-LatestReachableTag {
    $result = Invoke-Git -Arguments @('describe', '--tags', '--abbrev=0') -AllowFailure
    if ($result.ExitCode -ne 0) {
        return $null
    }
    $tag = (($result.Output | Select-Object -First 1) | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($tag)) {
        return $null
    }
    return $tag
}

function Test-IsSemVerTag {
    param([string]$Tag)
    return ($Tag -match '^v\d+\.\d+\.\d+$')
}

function Get-NextVersion {
    param(
        [string]$LatestTag,
        [string]$BumpType
    )

    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        switch ($BumpType) {
            'major' { return 'v1.0.0' }
            'minor' { return 'v0.1.0' }
            default { return 'v0.0.1' }
        }
    }

    if (-not (Test-IsSemVerTag -Tag $LatestTag)) {
        throw "Latest tag '$LatestTag' is not in vMAJOR.MINOR.PATCH format."
    }

    $parts = $LatestTag.TrimStart('v').Split('.')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    $patch = [int]$parts[2]

    switch ($BumpType) {
        'major' { return "v$($major + 1).0.0" }
        'minor' { return "v$major.$($minor + 1).0" }
        default { return "v$major.$minor.$($patch + 1)" }
    }
}

function Get-CommitMessagesSinceTag {
    param([string]$LatestTag)

    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        $result = Invoke-Git -Arguments @('log', '--pretty=format:%s')
    }
    else {
        $result = Invoke-Git -Arguments @('log', '--pretty=format:%s', "$LatestTag..HEAD")
    }

    return @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-CommitsSinceTag {
    param([string]$LatestTag)

    if ([string]::IsNullOrWhiteSpace($LatestTag)) {
        $result = Invoke-Git -Arguments @('log', '--oneline')
    }
    else {
        $result = Invoke-Git -Arguments @('log', '--oneline', "$LatestTag..HEAD")
    }

    return @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-ReleaseAnalysis {
    $latestTag = Get-LatestReachableTag
    if ($null -ne $latestTag -and -not (Test-IsSemVerTag -Tag $latestTag)) {
        throw "Latest tag '$latestTag' is not in vMAJOR.MINOR.PATCH format."
    }

    $status = Get-GitStatus
    $changed = Get-ChangedFiles
    $recentCommits = Get-RecentCommitSubjects -Count 8
    $workingTreeCommitType = if ($status.IsClean) { $null } else { Get-SuggestedCommitType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits }

    $commitMessages = Get-CommitMessagesSinceTag -LatestTag $latestTag
    $commitLines = Get-CommitsSinceTag -LatestTag $latestTag
    $importantPaths = @($changed.All | Where-Object { Test-IsReleaseImportantPath -Path $_ } | Sort-Object -Unique)
    $allChangedPaths = @($changed.All)
    $docsOnlyWorkingTree = ($allChangedPaths.Count -gt 0) -and (@($allChangedPaths | Where-Object { $_ -notmatch '^(README\.md|docs/)' }).Count -eq 0)

    $hasBreaking = @($commitMessages | Where-Object { $_ -match 'BREAKING CHANGE|breaking:|!:' }).Count -gt 0
    $hasFeatCommit = @($commitMessages | Where-Object { $_ -match '^feat(\(.+\))?: ' }).Count -gt 0
    $hasPatchCommit = @($commitMessages | Where-Object { $_ -match '^(fix|perf|refactor|build|test|docs|chore)(\(.+\))?: ' }).Count -gt 0
    $releaseNeeded = $false
    $reasons = New-Object System.Collections.Generic.List[string]

    if ($hasBreaking) {
        $releaseNeeded = $true
        $reasons.Add('breaking change markers detected since the latest tag')
    }
    if ($hasFeatCommit) {
        $releaseNeeded = $true
        $reasons.Add('feature commits detected since the latest tag')
    }
    if ($workingTreeCommitType -eq 'feat') {
        $releaseNeeded = $true
        $reasons.Add('current working tree looks like a feature change')
    }
    if ($importantPaths.Count -gt 0) {
        $releaseNeeded = $true
        $reasons.Add('release-important files changed in the working tree')
    }
    if (@($commitMessages).Count -ge 3) {
        $releaseNeeded = $true
        $reasons.Add('multiple commits landed since the latest tag')
    }
    if ($allChangedPaths.Count -ge 5) {
        $releaseNeeded = $true
        $reasons.Add('multiple files changed in the working tree')
    }
    if ($docsOnlyWorkingTree -and @($commitMessages).Count -eq 0) {
        $releaseNeeded = $false
        $reasons.Clear()
        $reasons.Add('docs-only working tree changes do not require a release by default')
    }
    if ($status.IsClean -and @($commitMessages).Count -eq 0) {
        $releaseNeeded = $false
        $reasons.Clear()
        $reasons.Add('no commits or working tree changes since the latest tag')
    }

    $bumpType = 'patch'
    if ($hasBreaking) {
        $bumpType = 'major'
    }
    elseif ($hasFeatCommit -or $workingTreeCommitType -eq 'feat') {
        $bumpType = 'minor'
    }
    elseif (-not $releaseNeeded) {
        $bumpType = 'patch'
    }
    elseif ($hasPatchCommit -or $workingTreeCommitType) {
        $bumpType = 'patch'
    }

    return [pscustomobject]@{
        LatestTag = $latestTag
        Status = $status
        Changed = $changed
        CommitMessages = $commitMessages
        CommitLines = $commitLines
        WorkingTreeCommitType = $workingTreeCommitType
        ImportantPaths = $importantPaths
        ReleaseRecommended = $releaseNeeded
        Reasons = @($reasons)
        BumpType = $bumpType
        ProposedVersion = Get-NextVersion -LatestTag $latestTag -BumpType $bumpType
    }
}

function Invoke-ReleaseFlow {
    param(
        [switch]$DryRunMode,
        [switch]$AssumeYes
    )

    Assert-GitRepository
    $analysis = Get-ReleaseAnalysis

    Write-Header 'NightPaw Release Helper'
    Write-InfoLine ("Latest tag: {0}" -f $(if ($analysis.LatestTag) { $analysis.LatestTag } else { 'none' }))
    Write-InfoLine ("Working tree clean: {0}" -f $(if ($analysis.Status.IsClean) { 'yes' } else { 'no' }))
    Write-InfoLine ("Release recommended: {0}" -f $(if ($analysis.ReleaseRecommended) { 'yes' } else { 'no' }))
    Write-InfoLine ("Recommended bump: {0}" -f $analysis.BumpType)
    Write-InfoLine ("Proposed version: {0}" -f $analysis.ProposedVersion)

    Write-Section 'Why'
    foreach ($reason in @($analysis.Reasons)) {
        Write-InfoLine $reason
    }
    if (@($analysis.Reasons).Count -eq 0) {
        Write-InfoLine '(no reasons)'
    }

    Write-Section 'Commits Since Latest Tag'
    if (@($analysis.CommitLines).Count -eq 0) {
        Write-InfoLine '(none)'
    }
    else {
        foreach ($line in @($analysis.CommitLines)) {
            Write-InfoLine $line
        }
    }

    Show-ChangedFileGroups -ChangedFiles $analysis.Changed

    Write-Section 'Diff Stat'
    foreach ($line in (Get-DiffStat)) {
        Write-InfoLine $line
    }

    if ($DryRunMode) {
        Write-WarnLine 'Dry run only. No tag was created.'
        return
    }
    if (-not $analysis.ReleaseRecommended) {
        Write-WarnLine 'Release is not recommended right now. No tag created.'
        return
    }
    if (-not $analysis.Status.IsClean) {
        Write-WarnLine 'Working tree is dirty. Commit or stash changes before creating a real release tag.'
        return
    }
    if (-not (Confirm-Action -Prompt ("Create annotated tag {0}? [y/N]" -f $analysis.ProposedVersion) -AssumeYes:$AssumeYes)) {
        Write-WarnLine 'Release canceled.'
        return
    }

    Invoke-Git -Arguments @('tag', '-a', $analysis.ProposedVersion, '-m', ("NightPaw {0}" -f $analysis.ProposedVersion)) | Out-Null
    Write-SuccessLine ("Created annotated tag {0}." -f $analysis.ProposedVersion)
    Write-InfoLine 'No push was performed.'
    Write-InfoLine 'Next manual command:'
    Write-InfoLine 'git push origin main --tags'
}

function Invoke-TestFlow {
    Assert-GitRepository
    $repoRoot = Get-RepoRoot
    $testsPath = Join-Path $repoRoot 'tests'
    $rustBridgeTest = Join-Path $testsPath 'test_rust_bridge.py'
    $previousUvCache = $env:UV_CACHE_DIR

    Write-Header 'NightPaw Test Helper'
    if (-not (Test-Path -LiteralPath $testsPath -PathType Container)) {
        Write-WarnLine 'No tests directory was found.'
        return
    }
    if (Test-Path -LiteralPath $rustBridgeTest -PathType Leaf) {
        Write-InfoLine 'Found focused Rust bridge test: tests/test_rust_bridge.py'
    }
    if (-not (Test-CommandAvailable -Name 'uv')) {
        Write-WarnLine 'uv is not available, so pytest was not run.'
        return
    }

    try {
        $env:UV_CACHE_DIR = Join-Path $repoRoot '.uv-cache'
        & uv run python -m pytest
        if ($LASTEXITCODE -ne 0) {
            throw "uv run python -m pytest failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        $env:UV_CACHE_DIR = $previousUvCache
    }

    Write-SuccessLine 'Tests completed successfully.'
}

function Invoke-BotCheck {
    Assert-GitRepository
    $pythonCandidates = @(Get-PythonCandidates)

    Write-Header 'NightPaw Bot Check'
    if ($pythonCandidates.Count -eq 0) {
        Write-WarnLine 'No Python interpreter was found in the project venv or PATH.'
        return
    }

    $result = Invoke-PythonCandidates -Arguments @('-m', 'compileall', 'main.py', 'config.py', 'checks.py', 'services', 'cogs')
    if (-not $result.Success) {
        throw "Python compileall check failed with exit code $($result.ExitCode)."
    }

    Write-SuccessLine 'Syntax/import safety check completed successfully.'
}

function Invoke-RustCheck {
    Assert-GitRepository
    $repoRoot = Get-RepoRoot
    $cratePath = Join-Path $repoRoot 'crates\nightpaw_rs'
    $pythonCandidates = @(Get-PythonCandidates)
    $python = if ($pythonCandidates.Count -gt 0) { $pythonCandidates[0].Command } else { $null }
    $pythonPrefixArgs = if ($pythonCandidates.Count -gt 0) { @($pythonCandidates[0].PrefixArgs) } else { @() }
    $previousPyo3Python = $env:PYO3_PYTHON

    Write-Header 'NightPaw Rust Helper Check'
    if (-not (Test-Path -LiteralPath $cratePath -PathType Container)) {
        Write-WarnLine 'crates/nightpaw_rs was not found.'
        return
    }

    if (Test-CommandAvailable -Name 'cargo') {
        Push-Location $cratePath
        try {
            if ($null -ne $python) {
                $env:PYO3_PYTHON = if (@($pythonPrefixArgs).Count -gt 0) { "$python $($pythonPrefixArgs -join ' ')" } else { $python }
            }
            & cargo test
            if ($LASTEXITCODE -ne 0) {
                throw "cargo test failed with exit code $LASTEXITCODE."
            }
            Write-SuccessLine 'cargo test completed successfully.'
        }
        finally {
            $env:PYO3_PYTHON = $previousPyo3Python
            Pop-Location
        }
    }
    else {
        Write-WarnLine 'cargo is not available, so cargo test was skipped.'
    }

    if (Test-CommandAvailable -Name 'uv') {
        & uv run --with maturin maturin develop --help
        if ($LASTEXITCODE -eq 0) {
            Write-SuccessLine 'maturin helper command is available through uv.'
        }
        else {
            Write-WarnLine 'maturin helper check through uv was not available.'
        }
    }
    else {
        Write-WarnLine 'uv is not available, so the maturin helper check was skipped.'
    }

    if ($pythonCandidates.Count -gt 0) {
        $importResult = Invoke-PythonCandidates -Arguments @('-c', "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('nightpaw_rs') else 1)")
        if ($importResult.Success) {
            Write-SuccessLine 'nightpaw_rs is importable from Python.'
        }
        else {
            Write-WarnLine 'nightpaw_rs is not currently importable from Python.'
        }
    }
    else {
        Write-WarnLine 'Python was not available, so the import check was skipped.'
    }
}

function Show-HelpPanel {
    Write-Header 'NightPaw Developer Console'
    Write-InfoLine 'Usage:'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 status'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 context'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 commit'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 commit -Type feat -Message "add optional Rust-backed service helpers" -Yes'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 release -DryRun'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 release'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 tests'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 bot-check'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 rust-check'
    Write-Host ''
    Write-InfoLine 'Flags: -Type -Message -Yes -DryRun -VerboseOutput'
    Write-InfoLine 'Legacy-style flags such as --dry-run and --help are also accepted.'
}

function Resolve-CommandArguments {
    $resolvedCommand = if ([string]::IsNullOrWhiteSpace($Command)) { $null } else { $Command.Trim().ToLowerInvariant() }

    foreach ($arg in @($RemainingArgs)) {
        if ($null -eq $arg) {
            continue
        }

        $argText = "$arg"
        if ([string]::IsNullOrWhiteSpace($argText)) {
            continue
        }

        switch ($argText.Trim().ToLowerInvariant()) {
            '--dry-run' { $script:DryRun = $true }
            '--help' { $resolvedCommand = 'help' }
            '-h' { $resolvedCommand = 'help' }
            '--yes' { $script:Yes = $true }
            '--verbose-output' { $script:VerboseOutput = $true }
            default {
                if ([string]::IsNullOrWhiteSpace($resolvedCommand)) {
                    $resolvedCommand = $argText.Trim().ToLowerInvariant()
                }
            }
        }
    }

    return $resolvedCommand
}

function Show-MainMenu {
    while ($true) {
        Write-Header 'NightPaw Developer Console'
        Write-InfoLine '1. Show project status'
        Write-InfoLine '2. Show commit context'
        Write-InfoLine '3. Commit changes'
        Write-InfoLine '4. Dry-run release'
        Write-InfoLine '5. Create release'
        Write-InfoLine '6. Run tests'
        Write-InfoLine '7. Run bot check'
        Write-InfoLine '8. Rust helper check'
        Write-InfoLine '9. Show help'
        Write-InfoLine '10. Exit'

        $choice = (Read-Host 'Choose an option').Trim()
        switch ($choice) {
            '1' { Show-ProjectStatus }
            '2' { Show-CommitContext }
            '3' { Invoke-CommitFlow -CommitType $Type -CommitMessage $Message -AssumeYes:$Yes }
            '4' { Invoke-ReleaseFlow -DryRunMode -AssumeYes:$Yes }
            '5' { Invoke-ReleaseFlow -AssumeYes:$Yes }
            '6' { Invoke-TestFlow }
            '7' { Invoke-BotCheck }
            '8' { Invoke-RustCheck }
            '9' { Show-HelpPanel }
            '10' { return }
            default { Write-WarnLine 'Choose a number from 1 to 10.' }
        }
    }
}

try {
    $resolvedCommand = Resolve-CommandArguments

    if (-not [string]::IsNullOrWhiteSpace($resolvedCommand)) {
        switch ($resolvedCommand) {
            'status' { Show-ProjectStatus; exit 0 }
            'context' { Show-CommitContext; exit 0 }
            'commit' { Invoke-CommitFlow -CommitType $Type -CommitMessage $Message -AssumeYes:$Yes; exit 0 }
            'release' { Invoke-ReleaseFlow -DryRunMode:$DryRun -AssumeYes:$Yes; exit 0 }
            'tests' { Invoke-TestFlow; exit 0 }
            'bot-check' { Invoke-BotCheck; exit 0 }
            'rust-check' { Invoke-RustCheck; exit 0 }
            'help' { Show-HelpPanel; exit 0 }
            default { throw "Unknown command '$resolvedCommand'. Run '.\scripts\nightpaw-dev.ps1 help' for usage." }
        }
    }

    Show-MainMenu
}
catch {
    Write-ErrorLine $_.Exception.Message
    if ($VerboseOutput) {
        if ($_.InvocationInfo) {
            Write-ErrorLine $_.InvocationInfo.PositionMessage
        }
        if ($_.ScriptStackTrace) {
            Write-ErrorLine $_.ScriptStackTrace
        }
    }
    exit 1
}
