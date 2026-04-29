[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command,

    [string]$Type,
    [string]$Message,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$Push,
    [switch]$CreateGitHubRelease,
    [switch]$UseTagNotes,
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
    'README.md',
    'CHANGELOG.md'
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

function Get-EmptyTreeHash {
    return '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
}

function Convert-ToRepoPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    return ($Path.Trim() -replace '\\', '/')
}

function Get-StatusPath {
    param([string]$Line)

    if ($Line -match '^\?\? (?<path>.+)$') {
        return Convert-ToRepoPath -Path $Matches['path']
    }
    if ($Line.Length -ge 4) {
        return Convert-ToRepoPath -Path $Line.Substring(3)
    }
    return Convert-ToRepoPath -Path $Line
}

function Convert-NameStatusLine {
    param([string]$Line)

    if ([string]::IsNullOrWhiteSpace($Line)) {
        return $null
    }

    $parts = $Line -split "`t"
    if ($parts.Count -lt 2) {
        return $null
    }

    $statusCode = $parts[0].Trim()
    $status = if ($statusCode.Length -gt 0) { $statusCode.Substring(0, 1).ToUpperInvariant() } else { '' }
    $path = Convert-ToRepoPath -Path $parts[-1]
    $oldPath = $null
    $displayPath = $path

    if ($status -eq 'R' -and $parts.Count -ge 3) {
        $oldPath = Convert-ToRepoPath -Path $parts[1]
        $path = Convert-ToRepoPath -Path $parts[2]
        $displayPath = "{0} -> {1}" -f $oldPath, $path
    }

    return [pscustomobject]@{
        StatusCode = $statusCode
        Status = $status
        Path = $path
        OldPath = $oldPath
        DisplayPath = $displayPath
    }
}

function Get-UniquePaths {
    param([string[]]$Paths)

    return @(
        $Paths |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { Convert-ToRepoPath -Path $_ } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique
    )
}

function Get-DirectoryPreviewLines {
    param(
        [string[]]$Paths,
        [int]$PreviewCount = 4
    )

    $normalized = @(Get-UniquePaths -Paths $Paths)
    if ($normalized.Count -eq 0) {
        return @()
    }

    $groups = [ordered]@{}
    foreach ($path in $normalized) {
        $dir = Split-Path -Path $path -Parent
        if ([string]::IsNullOrWhiteSpace($dir) -or $dir -eq '.') {
            continue
        }

        if (-not $groups.Contains($dir)) {
            $groups[$dir] = New-Object System.Collections.Generic.List[string]
        }
        $groups[$dir].Add($path)
    }

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($dir in $groups.Keys | Sort-Object) {
        $entries = @($groups[$dir] | Sort-Object -Unique)
        $preview = @($entries | Select-Object -First $PreviewCount | ForEach-Object {
            [System.IO.Path]::GetFileName($_)
        })

        if ($entries.Count -eq 0) {
            continue
        }

        $line = "{0}/ -> {1}" -f $dir.TrimEnd('/'), ($preview -join ', ')
        if ($entries.Count -gt $PreviewCount) {
            $line = "{0} (+{1} more)" -f $line, ($entries.Count - $PreviewCount)
        }
        $lines.Add($line)
    }

    return @($lines)
}

function Get-GitStatus {
    Assert-GitRepository
    $porcelain = @((Invoke-Git -Arguments @('status', '--porcelain=v1')).Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $unstagedEntries = @((Invoke-Git -Arguments @('diff', '--name-status')).Output | ForEach-Object { Convert-NameStatusLine -Line $_ } | Where-Object { $null -ne $_ })
    $stagedEntries = @((Invoke-Git -Arguments @('diff', '--cached', '--name-status')).Output | ForEach-Object { Convert-NameStatusLine -Line $_ } | Where-Object { $null -ne $_ })
    $untracked = @((Invoke-Git -Arguments @('ls-files', '--others', '--exclude-standard')).Output | ForEach-Object { Convert-ToRepoPath -Path $_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $modified = New-Object System.Collections.Generic.List[string]
    $staged = New-Object System.Collections.Generic.List[string]
    $deleted = New-Object System.Collections.Generic.List[string]
    $renamed = New-Object System.Collections.Generic.List[string]

    foreach ($entry in @($unstagedEntries + $stagedEntries)) {
        switch ($entry.Status) {
            'M' { $modified.Add($entry.Path) }
            'T' { $modified.Add($entry.Path) }
            'C' { $modified.Add($entry.Path) }
            'D' { $deleted.Add($entry.DisplayPath) }
            'R' { $renamed.Add($entry.DisplayPath) }
            default {
                if ($entry.Status -notin @('A')) {
                    $modified.Add($entry.Path)
                }
            }
        }
    }

    foreach ($entry in $stagedEntries) {
        if (-not [string]::IsNullOrWhiteSpace($entry.DisplayPath)) {
            $staged.Add($entry.DisplayPath)
        }
    }

    foreach ($line in $porcelain) {
        if ($line -match '^\?\? ') {
            continue
        }

        $path = Get-StatusPath -Line $line
        if ([string]::IsNullOrWhiteSpace($path)) {
            continue
        }

        $xy = if ($line.Length -ge 2) { $line.Substring(0, 2) } else { '  ' }
        if ($xy -match '[MT]') {
            $modified.Add($path)
        }
        if ($xy -match 'D') {
            $deleted.Add($path)
        }
        if ($xy -match 'R' -or $path -match ' -> ') {
            $renamed.Add($path)
        }
    }

    $modifiedPaths = @(Get-UniquePaths -Paths $modified)
    $stagedPaths = @(Get-UniquePaths -Paths $staged)
    $untrackedPaths = @(Get-UniquePaths -Paths $untracked)
    $deletedPaths = @(Get-UniquePaths -Paths $deleted)
    $renamedPaths = @(Get-UniquePaths -Paths $renamed)
    $commitPreview = @(Get-UniquePaths -Paths @($modifiedPaths + $stagedPaths + $untrackedPaths + $deletedPaths + $renamedPaths))

    return [pscustomobject]@{
        Lines = $porcelain
        UnstagedEntries = @($unstagedEntries)
        StagedEntries = @($stagedEntries)
        Modified = $modifiedPaths
        Staged = $stagedPaths
        Untracked = $untrackedPaths
        Deleted = $deletedPaths
        Renamed = $renamedPaths
        DirectoryPreview = @(Get-DirectoryPreviewLines -Paths $untrackedPaths)
        CommitPreview = $commitPreview
        Summary = [ordered]@{
            modified = $modifiedPaths.Count
            staged = $stagedPaths.Count
            untracked = $untrackedPaths.Count
            deleted = $deletedPaths.Count
            renamed = $renamedPaths.Count
        }
        IsClean = ($porcelain.Count -eq 0)
    }
}

function Get-ChangedFiles {
    $status = Get-GitStatus

    return [pscustomobject]@{
        Modified = @($status.Modified)
        Staged = @($status.Staged)
        Untracked = @($status.Untracked)
        Deleted = @($status.Deleted)
        Renamed = @($status.Renamed)
        DirectoryPreview = @($status.DirectoryPreview)
        All = @($status.CommitPreview)
    }
}

function Get-DiffStat {
    Assert-GitRepository

    $hasHead = ((Invoke-Git -Arguments @('rev-parse', '--verify', 'HEAD') -AllowFailure).ExitCode -eq 0)
    $base = if ($hasHead) { 'HEAD' } else { Get-EmptyTreeHash }
    $result = Invoke-Git -Arguments @('diff', '--stat', $base, '--')
    $lines = @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $status = Get-GitStatus
    if ($status.Untracked.Count -gt 0) {
        $lines += 'Untracked files included in status/context but not in git diff --stat:'
        foreach ($path in $status.Untracked) {
            $lines += ("  {0}" -f $path)
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
    $docsOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(readme\.md|docs/|changelog\.md$)' }).Count -eq 0)
    $testsOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(tests/|test_.*\.py$)' }).Count -eq 0)
    $scriptsOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(scripts/|readme\.md|docs/|changelog\.md$)' }).Count -eq 0)
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
    if (($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(readme\.md|docs/|changelog\.md$)' }).Count -eq 0)) {
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
        @{ Name = 'Staged'; Values = @($ChangedFiles.Staged) }
        @{ Name = 'Untracked'; Values = @($ChangedFiles.Untracked) }
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

    Write-Host 'Commit Preview (all files that would be committed)' -ForegroundColor White
    if (@($ChangedFiles.All).Count -eq 0) {
        Write-Host '  (none)' -ForegroundColor DarkGray
    }
    else {
        foreach ($path in @($ChangedFiles.All)) {
            Write-Host ("  {0}" -f $path) -ForegroundColor Gray
        }
    }

    if (@($ChangedFiles.DirectoryPreview).Count -gt 0) {
        Write-Host 'Untracked Directory Preview' -ForegroundColor White
        foreach ($line in @($ChangedFiles.DirectoryPreview)) {
            Write-Host ("  {0}" -f $line) -ForegroundColor DarkGray
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
        Write-InfoLine ("Modified: {0} | Staged: {1} | Untracked: {2} | Deleted: {3} | Renamed: {4}" -f
            $status.Summary.modified,
            $status.Summary.staged,
            $status.Summary.untracked,
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

function Get-CurrentBranchInfo {
    $result = Invoke-Git -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')
    $branch = (($result.Output | Select-Object -First 1) | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw 'Unable to determine the current branch.'
    }

    return [pscustomobject]@{
        Name = $branch
        IsDetached = ($branch -eq 'HEAD')
    }
}

function Test-RemoteTagExists {
    param([Parameter(Mandatory)][string]$Tag)

    $result = Invoke-Git -Arguments @('ls-remote', '--tags', 'origin', "refs/tags/$Tag") -AllowFailure
    if ($result.ExitCode -ne 0) {
        return $false
    }

    return (@($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -gt 0)
}

function Get-ReleaseRangeSpec {
    param(
        [string]$PreviousTag,
        [string]$TargetRef = 'HEAD'
    )

    if ([string]::IsNullOrWhiteSpace($PreviousTag)) {
        return $null
    }

    return "{0}..{1}" -f $PreviousTag, $TargetRef
}

function Get-ReleaseChangedFiles {
    param(
        [string]$PreviousTag,
        [string]$TargetRef = 'HEAD'
    )

    $rangeSpec = Get-ReleaseRangeSpec -PreviousTag $PreviousTag -TargetRef $TargetRef
    $args = if ($rangeSpec) {
        @('diff', '--name-status', $rangeSpec)
    }
    else {
        @('diff', '--name-status', (Get-EmptyTreeHash), $TargetRef)
    }

    return @((Invoke-Git -Arguments $args).Output | ForEach-Object { Convert-NameStatusLine -Line $_ } | Where-Object { $null -ne $_ })
}

function Get-CommitObjectsSinceTag {
    param(
        [string]$PreviousTag,
        [string]$TargetRef = 'HEAD'
    )

    $rangeSpec = Get-ReleaseRangeSpec -PreviousTag $PreviousTag -TargetRef $TargetRef
    $args = @('log', '--format=%H%x1f%h%x1f%s%x1f%b%x1e')
    if ($rangeSpec) {
        $args += $rangeSpec
    }
    else {
        $args += $TargetRef
    }

    $raw = ((Invoke-Git -Arguments $args).Output -join "`n")
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return @()
    }

    $records = @($raw -split [char]0x1e | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $commits = @()
    foreach ($record in $records) {
        $parts = $record.Trim() -split [char]0x1f, 4
        if ($parts.Count -lt 3) {
            continue
        }

        $body = if ($parts.Count -ge 4) { $parts[3].Trim() } else { '' }
        $subject = $parts[2].Trim()
        $lineText = "{0} {1}" -f $parts[1].Trim(), $subject
        $commits += [pscustomobject]@{
            Hash = $parts[0].Trim()
            ShortHash = $parts[1].Trim()
            Subject = $subject
            Body = $body
            Line = $lineText
        }
    }

    return @($commits)
}

function Get-ReleaseAreaSummary {
    param([string[]]$Paths)

    $areas = New-Object System.Collections.Generic.List[string]
    $normalized = @($Paths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    if (@($normalized | Where-Object { $_ -eq 'main.py' -or $_ -eq 'config.py' -or $_ -eq 'checks.py' }).Count -gt 0) {
        $areas.Add('core runtime')
    }
    if (@($normalized | Where-Object { $_ -like 'services/*' }).Count -gt 0) {
        $areas.Add('services')
    }
    if (@($normalized | Where-Object { $_ -like 'cogs/*' }).Count -gt 0) {
        $areas.Add('cogs')
    }
    if (@($normalized | Where-Object { $_ -like 'crates/*' -or $_ -eq 'services/rust_bridge.py' -or $_ -like 'tests/*rust*' }).Count -gt 0) {
        $areas.Add('Rust helper layer')
    }
    if (@($normalized | Where-Object { $_ -eq 'pyproject.toml' -or $_ -eq 'uv.lock' }).Count -gt 0) {
        $areas.Add('build and dependencies')
    }
    if (@($normalized | Where-Object { $_ -eq 'README.md' -or $_ -eq 'CHANGELOG.md' -or $_ -like 'docs/*' }).Count -gt 0) {
        $areas.Add('documentation')
    }
    if (@($normalized | Where-Object { $_ -like 'scripts/*' }).Count -gt 0) {
        $areas.Add('developer tooling')
    }

    return @($areas | Select-Object -Unique)
}

function Get-GroupedReleaseNotes {
    param(
        [object[]]$Commits
    )

    $groups = [ordered]@{
        Added = New-Object System.Collections.Generic.List[string]
        Fixed = New-Object System.Collections.Generic.List[string]
        Changed = New-Object System.Collections.Generic.List[string]
        Performance = New-Object System.Collections.Generic.List[string]
        Docs = New-Object System.Collections.Generic.List[string]
        Build = New-Object System.Collections.Generic.List[string]
        Tests = New-Object System.Collections.Generic.List[string]
        Chore = New-Object System.Collections.Generic.List[string]
        'Breaking Changes' = New-Object System.Collections.Generic.List[string]
    }

    foreach ($commit in @($Commits)) {
        $subject = [string]$commit.Subject
        $body = [string]$commit.Body
        $line = "- {0} {1}" -f $commit.ShortHash, $subject
        $isBreaking = ($subject -match '!' -or $subject -match 'breaking:' -or $body -match 'BREAKING CHANGE|breaking:')

        if ($isBreaking) {
            $groups['Breaking Changes'].Add($line)
        }

        if ($subject -match '^feat(\(.+\))?!?: ') {
            $groups.Added.Add($line)
        }
        elseif ($subject -match '^fix(\(.+\))?!?: ') {
            $groups.Fixed.Add($line)
        }
        elseif ($subject -match '^perf(\(.+\))?!?: ') {
            $groups.Performance.Add($line)
        }
        elseif ($subject -match '^docs(\(.+\))?!?: ') {
            $groups.Docs.Add($line)
        }
        elseif ($subject -match '^(build|ci)(\(.+\))?!?: ') {
            $groups.Build.Add($line)
        }
        elseif ($subject -match '^test(\(.+\))?!?: ') {
            $groups.Tests.Add($line)
        }
        elseif ($subject -match '^chore(\(.+\))?!?: ') {
            $groups.Chore.Add($line)
        }
        else {
            $groups.Changed.Add($line)
        }
    }

    return $groups
}

function Format-ReleaseFileLine {
    param([pscustomobject]$Entry)

    if ($null -eq $Entry) {
        return $null
    }

    return "- {0} {1}" -f $Entry.Status, $Entry.DisplayPath
}

function Get-ReleaseNotesMarkdown {
    param(
        [Parameter(Mandatory)]
        [pscustomobject]$Analysis,
        [Parameter(Mandatory)]
        [string]$NewTag
    )

    $previousTag = if ($Analysis.LatestTag) { $Analysis.LatestTag } else { 'initial release' }
    $changedAreas = @(Get-ReleaseAreaSummary -Paths @($Analysis.ReleaseRangePaths + $Analysis.PendingPaths))
    $grouped = Get-GroupedReleaseNotes -Commits $Analysis.Commits
    $lines = New-Object System.Collections.Generic.List[string]

    $lines.Add("# $NewTag")
    $lines.Add('')
    $lines.Add(("Previous tag: {0}" -f $previousTag))
    $lines.Add(("New tag: {0}" -f $NewTag))
    $lines.Add(("Release range: {0}" -f $Analysis.ReleaseRangeLabel))

    if ($changedAreas.Count -gt 0) {
        $lines.Add('')
        $lines.Add('## Changed Areas')
        foreach ($area in $changedAreas) {
            $lines.Add(("- {0}" -f $area))
        }
    }

    $hasGroupedCommits = $false
    foreach ($groupName in @('Breaking Changes', 'Added', 'Fixed', 'Changed', 'Performance', 'Docs', 'Build', 'Tests', 'Chore')) {
        $entries = @($grouped[$groupName])
        if ($entries.Count -gt 0) {
            $hasGroupedCommits = $true
            $lines.Add('')
            $lines.Add(("## {0}" -f $groupName))
            foreach ($entry in $entries) {
                $lines.Add($entry)
            }
        }
    }

    if (-not $hasGroupedCommits) {
        $lines.Add('')
        $lines.Add('## Changes')
        if (@($Analysis.Commits).Count -gt 0) {
            foreach ($commit in @($Analysis.Commits)) {
                $lines.Add(("- {0}" -f $commit.Line))
            }
        }
        else {
            $lines.Add('- No commits are in the release range yet.')
        }
    }

    $lines.Add('')
    $lines.Add('## Commits')
    if (@($Analysis.Commits).Count -eq 0) {
        $lines.Add('- (none)')
    }
    else {
        foreach ($commit in @($Analysis.Commits)) {
            $lines.Add(("- {0}" -f $commit.Line))
        }
    }

    $lines.Add('')
    $lines.Add('## Changed Files')
    if (@($Analysis.ReleaseRangeFiles).Count -eq 0) {
        $lines.Add('- (none in committed release range)')
    }
    else {
        foreach ($entry in @($Analysis.ReleaseRangeFiles)) {
            $lines.Add((Format-ReleaseFileLine -Entry $entry))
        }
    }

    if (@($Analysis.PendingPaths).Count -gt 0) {
        $lines.Add('')
        $lines.Add('## Pending Working Tree Changes')
        foreach ($path in @($Analysis.PendingPaths)) {
            $lines.Add(("- {0}" -f $path))
        }
    }

    return @($lines)
}

function Invoke-GitHubReleaseCreate {
    param(
        [Parameter(Mandatory)][string]$Tag,
        [Parameter(Mandatory)][string[]]$Notes,
        [switch]$UseTagNotesFallback
    )

    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-WarnLine 'GitHub CLI is not available. You can create the GitHub release manually later.'
        return $false
    }

    if ($UseTagNotesFallback) {
        & gh release create $Tag --title $Tag --notes-from-tag
        if ($LASTEXITCODE -ne 0) {
            throw "gh release create failed with exit code $LASTEXITCODE."
        }
    }
    else {
        $notesPath = [System.IO.Path]::GetTempFileName()
        try {
            Set-Content -LiteralPath $notesPath -Value $Notes -Encoding UTF8
            & gh release create $Tag --title $Tag --notes-file $notesPath
            if ($LASTEXITCODE -ne 0) {
                throw "gh release create failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Remove-Item -LiteralPath $notesPath -ErrorAction SilentlyContinue
        }
    }

    Write-SuccessLine ("Created GitHub release for {0}." -f $Tag)
    return $true
}

function Test-IsSemVerTag {
    param([string]$Tag)
    return ($Tag -match '^v\d+\.\d+\.\d+$')
}

function Get-ResolvedReleaseBumpType {
    param([string]$TypeValue)

    if ([string]::IsNullOrWhiteSpace($TypeValue)) {
        return $null
    }

    switch ($TypeValue.Trim().ToLowerInvariant()) {
        'major' { return 'major' }
        'minor' { return 'minor' }
        'patch' { return 'patch' }
        default { return $null }
    }
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
    return @(Get-CommitObjectsSinceTag -PreviousTag $LatestTag | ForEach-Object { $_.Subject })
}

function Get-CommitsSinceTag {
    param([string]$LatestTag)
    return @(Get-CommitObjectsSinceTag -PreviousTag $LatestTag | ForEach-Object { $_.Line })
}

function Get-ReleaseAnalysis {
    param([string]$RequestedBumpType)

    $latestTag = Get-LatestReachableTag
    if ($null -ne $latestTag -and -not (Test-IsSemVerTag -Tag $latestTag)) {
        throw "Latest tag '$latestTag' is not in vMAJOR.MINOR.PATCH format."
    }

    $branchInfo = Get-CurrentBranchInfo
    $status = Get-GitStatus
    $changed = Get-ChangedFiles
    $recentCommits = Get-RecentCommitSubjects -Count 8
    $workingTreeCommitType = if ($status.IsClean) { $null } else { Get-SuggestedCommitType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits }

    $commits = @(Get-CommitObjectsSinceTag -PreviousTag $latestTag)
    $commitMessages = @($commits | ForEach-Object { $_.Subject })
    $commitLines = @($commits | ForEach-Object { $_.Line })
    $releaseRangeFiles = @(Get-ReleaseChangedFiles -PreviousTag $latestTag)
    $releaseRangePaths = @($releaseRangeFiles | ForEach-Object { $_.Path } | Sort-Object -Unique)
    $pendingPaths = @($changed.All | Sort-Object -Unique)
    $allChangedPaths = @((@($releaseRangePaths) + @($pendingPaths)) | Sort-Object -Unique)
    $importantPaths = @($allChangedPaths | Where-Object { Test-IsReleaseImportantPath -Path $_ } | Sort-Object -Unique)
    $docsOnlyOverall = ($allChangedPaths.Count -gt 0) -and (@($allChangedPaths | Where-Object { $_ -notmatch '^(readme\.md|docs/|changelog\.md$)' }).Count -eq 0)
    $requestedBump = Get-ResolvedReleaseBumpType -TypeValue $RequestedBumpType

    $hasBreaking = @($commits | Where-Object { $_.Subject -match '!' -or $_.Subject -match 'breaking:' -or $_.Body -match 'BREAKING CHANGE|breaking:' }).Count -gt 0
    $hasFeatCommit = @($commitMessages | Where-Object { $_ -match '^feat(\(.+\))?!?: ' }).Count -gt 0
    $hasPatchCommit = @($commitMessages | Where-Object { $_ -match '^(fix|perf|refactor|build|test|docs|chore|ci)(\(.+\))?!?: ' }).Count -gt 0
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
    if ($pendingPaths.Count -gt 0) {
        $releaseNeeded = $true
        $reasons.Add('working tree changes are pending since the latest tag')
    }
    if ($importantPaths.Count -gt 0) {
        $releaseNeeded = $true
        $reasons.Add('release-important files changed since the latest tag or in the working tree')
    }
    if (@($commitMessages).Count -ge 3) {
        $releaseNeeded = $true
        $reasons.Add('multiple commits landed since the latest tag')
    }
    if ($allChangedPaths.Count -ge 5) {
        $releaseNeeded = $true
        $reasons.Add('multiple files changed since the latest tag')
    }
    if ($docsOnlyOverall) {
        $releaseNeeded = $false
        $reasons.Clear()
        $reasons.Add('docs-only changes do not require a release by default')
    }
    if ($status.IsClean -and @($commitMessages).Count -eq 0 -and $releaseRangeFiles.Count -eq 0) {
        $releaseNeeded = $false
        $reasons.Clear()
        $reasons.Add('no commits or working tree changes since the latest tag')
    }
    if ($requestedBump) {
        $releaseNeeded = $true
        $reasons.Add("release type forced to $requestedBump by -Type")
    }

    $bumpType = 'patch'
    if ($requestedBump) {
        $bumpType = $requestedBump
    }
    elseif ($hasBreaking) {
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
        Branch = $branchInfo.Name
        IsDetachedHead = $branchInfo.IsDetached
        Status = $status
        Changed = $changed
        Commits = @($commits)
        CommitMessages = $commitMessages
        CommitLines = $commitLines
        ReleaseRangeLabel = if ($latestTag) { "$latestTag..HEAD" } else { 'initial release (empty tree..HEAD)' }
        ReleaseRangeFiles = @($releaseRangeFiles)
        ReleaseRangePaths = @($releaseRangePaths)
        PendingPaths = @($pendingPaths)
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
        [switch]$AssumeYes,
        [switch]$PushAfterTag,
        [switch]$CreateReleaseAfterPush,
        [switch]$UseTagNotesFallback
)

    Assert-GitRepository
    $analysis = Get-ReleaseAnalysis -RequestedBumpType $Type

    Write-Header 'NightPaw Release Helper'
    Write-InfoLine ("Latest tag: {0}" -f $(if ($analysis.LatestTag) { $analysis.LatestTag } else { 'none' }))
    Write-InfoLine ("Current branch: {0}" -f $analysis.Branch)
    Write-InfoLine ("Working tree clean: {0}" -f $(if ($analysis.Status.IsClean) { 'yes' } else { 'no' }))
    Write-InfoLine ("Release recommended: {0}" -f $(if ($analysis.ReleaseRecommended) { 'yes' } else { 'no' }))
    Write-InfoLine ("Recommended bump: {0}" -f $analysis.BumpType)
    Write-InfoLine ("Proposed version: {0}" -f $analysis.ProposedVersion)
    if ($analysis.IsDetachedHead) {
        Write-WarnLine 'Detached HEAD detected. The helper will not push automatically from this state.'
    }

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

    Write-Section 'Changed Files Since Latest Tag'
    if (@($analysis.ReleaseRangeFiles).Count -eq 0) {
        Write-InfoLine '(none)'
    }
    else {
        foreach ($entry in @($analysis.ReleaseRangeFiles)) {
            Write-InfoLine ((Format-ReleaseFileLine -Entry $entry).TrimStart('-', ' '))
        }
    }

    if (@($analysis.PendingPaths).Count -gt 0) {
        Write-Section 'Pending Working Tree Changes'
        foreach ($path in @($analysis.PendingPaths)) {
            Write-InfoLine $path
        }
    }

    Show-ChangedFileGroups -ChangedFiles $analysis.Changed

    Write-Section 'Diff Stat'
    foreach ($line in (Get-DiffStat)) {
        Write-InfoLine $line
    }

    $releaseNotes = Get-ReleaseNotesMarkdown -Analysis $analysis -NewTag $analysis.ProposedVersion
    $changelogPreview = Get-ChangelogPreview -Analysis $analysis -NewTag $analysis.ProposedVersion

    Write-Section 'Generated Release Notes Preview'
    foreach ($line in $releaseNotes) {
        Write-InfoLine $line
    }

    Write-Section 'CHANGELOG Preview'
    foreach ($line in $changelogPreview.PreviewLines) {
        Write-InfoLine $line
    }
    if ($changelogPreview.RequiresWrite) {
        Write-WarnLine 'CHANGELOG.md does not contain this version yet.'
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
    if ($changelogPreview.RequiresWrite) {
        if (-not (Confirm-Action -Prompt ("Write CHANGELOG.md entry for {0}? [y/N]" -f $analysis.ProposedVersion) -AssumeYes:$AssumeYes)) {
            Write-WarnLine 'Release canceled before CHANGELOG.md update.'
            return
        }

        Write-ChangelogFile -ChangelogPath $changelogPreview.Path -ContentLines $changelogPreview.UpdatedContent
        Write-WarnLine 'CHANGELOG.md was updated. Commit it before or with the release, then rerun the release command.'
        return
    }
    if (-not (Confirm-Action -Prompt ("Create annotated tag {0}? [y/N]" -f $analysis.ProposedVersion) -AssumeYes:$AssumeYes)) {
        Write-WarnLine 'Release canceled.'
        return
    }

    Invoke-Git -Arguments @('tag', '-a', $analysis.ProposedVersion, '-m', ("NightPaw {0}" -f $analysis.ProposedVersion)) | Out-Null
    Write-SuccessLine ("Created annotated tag {0}." -f $analysis.ProposedVersion)

    $didPush = $false
    $shouldPush = $PushAfterTag
    if ($analysis.IsDetachedHead) {
        $shouldPush = $false
        Write-WarnLine 'Detached HEAD detected. Skipping push.'
    }
    elseif (-not $shouldPush) {
        $shouldPush = Confirm-Action -Prompt 'Push current branch and tags to origin now? [y/N]'
    }

    if ($shouldPush) {
        Invoke-Git -Arguments @('push', 'origin', $analysis.Branch, '--tags') | Out-Null
        $didPush = $true
        Write-SuccessLine ("Pushed branch {0} and tags to origin." -f $analysis.Branch)
    }
    else {
        Write-InfoLine 'No push was performed.'
        Write-InfoLine 'Next manual command:'
        if ($analysis.IsDetachedHead) {
            Write-InfoLine 'git push origin <branch-name> --tags'
        }
        else {
            Write-InfoLine ("git push origin {0} --tags" -f $analysis.Branch)
        }
    }

    $shouldCreateGitHubRelease = $false
    if ($CreateReleaseAfterPush) {
        $shouldCreateGitHubRelease = $true
    }
    elseif ($didPush -and (Test-CommandAvailable -Name 'gh')) {
        $shouldCreateGitHubRelease = Confirm-Action -Prompt 'Create GitHub release with gh now? [y/N]'
    }
    elseif ($didPush) {
        Write-WarnLine 'GitHub CLI is not available. You can create the GitHub release manually later.'
    }

    if ($shouldCreateGitHubRelease) {
        if (-not $didPush) {
            if (-not (Test-RemoteTagExists -Tag $analysis.ProposedVersion)) {
                Write-WarnLine 'Tag is not available on origin yet, so GitHub release creation was skipped.'
                return
            }
        }

        $null = Invoke-GitHubReleaseCreate -Tag $analysis.ProposedVersion -Notes $releaseNotes -UseTagNotesFallback:$UseTagNotesFallback
    }
}

function Get-ChangelogPath {
    return (Join-Path (Get-RepoRoot) 'CHANGELOG.md')
}

function Get-ChangelogLines {
    param([string]$ChangelogPath)

    if (Test-Path -LiteralPath $ChangelogPath -PathType Leaf) {
        return @(Get-Content -LiteralPath $ChangelogPath)
    }

    return @(
        '# Changelog',
        '',
        'All notable changes to this project will be documented in this file.',
        ''
    )
}

function Test-ChangelogHasVersion {
    param(
        [string[]]$Lines,
        [string]$Version
    )

    return (@($Lines | Where-Object { $_ -match ("^##\s+{0}\s+-\s+\d{{4}}-\d{{2}}-\d{{2}}$" -f [regex]::Escape($Version)) }).Count -gt 0)
}

function Get-ChangelogEntryLines {
    param(
        [Parameter(Mandatory)][pscustomobject]$Analysis,
        [Parameter(Mandatory)][string]$NewTag
    )

    $dateText = Get-Date -Format 'yyyy-MM-dd'
    $releaseLines = @(Get-ReleaseNotesMarkdown -Analysis $Analysis -NewTag $NewTag)
    $bodyLines = if ($releaseLines.Count -gt 4) { $releaseLines[4..($releaseLines.Count - 1)] } else { @() }
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("## $NewTag - $dateText")
    $lines.Add('')
    foreach ($line in $bodyLines) {
        if ($line -match '^## ') {
            $lines.Add(($line -replace '^## ', '### '))
        }
        else {
            $lines.Add($line)
        }
    }
    $lines.Add('')
    return @($lines)
}

function Get-ChangelogPreview {
    param(
        [Parameter(Mandatory)][pscustomobject]$Analysis,
        [Parameter(Mandatory)][string]$NewTag
    )

    $path = Get-ChangelogPath
    $currentLines = @(Get-ChangelogLines -ChangelogPath $path)
    $hasVersion = Test-ChangelogHasVersion -Lines $currentLines -Version $NewTag
    $entryLines = @(Get-ChangelogEntryLines -Analysis $Analysis -NewTag $NewTag)
    $updatedContent = New-Object System.Collections.Generic.List[string]

    if (-not $hasVersion -and $currentLines.Count -ge 4 -and $currentLines[0] -eq '# Changelog') {
        $updatedContent.Add($currentLines[0])
        $updatedContent.Add('')
        $updatedContent.Add($currentLines[2])
        $updatedContent.Add('')
        foreach ($line in $entryLines) {
            $updatedContent.Add($line)
        }
        for ($index = 4; $index -lt $currentLines.Count; $index++) {
            $updatedContent.Add($currentLines[$index])
        }
    }
    else {
        foreach ($line in $currentLines) {
            $updatedContent.Add($line)
        }
        if (-not $hasVersion) {
            if ($updatedContent.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($updatedContent[$updatedContent.Count - 1])) {
                $updatedContent.Add('')
            }
            foreach ($line in $entryLines) {
                $updatedContent.Add($line)
            }
        }
    }

    return [pscustomobject]@{
        Path = $path
        RequiresWrite = (-not $hasVersion)
        PreviewLines = $entryLines
        UpdatedContent = @($updatedContent)
    }
}

function Write-ChangelogFile {
    param(
        [Parameter(Mandatory)][string]$ChangelogPath,
        [Parameter(Mandatory)][string[]]$ContentLines
    )

    Set-Content -LiteralPath $ChangelogPath -Value $ContentLines -Encoding UTF8
    Write-SuccessLine ("Updated {0}" -f (Split-Path -Path $ChangelogPath -Leaf))
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
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 release -Push'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease -UseTagNotes'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 tests'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 bot-check'
    Write-InfoLine '  .\scripts\nightpaw-dev.ps1 rust-check'
    Write-Host ''
    Write-InfoLine 'Flags: -Type -Message -Yes -DryRun -Push -CreateGitHubRelease -UseTagNotes -VerboseOutput'
    Write-InfoLine '-Type can override release bump selection with major, minor, or patch.'
    Write-InfoLine '-Yes skips the local changelog/tag confirmations only. It does not imply push or GitHub release creation.'
    Write-InfoLine 'Release previews include grouped notes, commits, changed files, and the CHANGELOG entry.'
    Write-InfoLine '-UseTagNotes restores gh --notes-from-tag as an explicit fallback.'
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
            '--push' { $script:Push = $true }
            '--create-github-release' { $script:CreateGitHubRelease = $true }
            '--use-tag-notes' { $script:UseTagNotes = $true }
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

        $rawChoice = Read-Host 'Choose an option'
        if ($null -eq $rawChoice) {
            return
        }
        $choice = $rawChoice.Trim()
        switch ($choice) {
            '1' { Show-ProjectStatus }
            '2' { Show-CommitContext }
            '3' { Invoke-CommitFlow -CommitType $Type -CommitMessage $Message -AssumeYes:$Yes }
            '4' { Invoke-ReleaseFlow -DryRunMode -AssumeYes:$Yes -PushAfterTag:$Push -CreateReleaseAfterPush:$CreateGitHubRelease -UseTagNotesFallback:$UseTagNotes }
            '5' { Invoke-ReleaseFlow -AssumeYes:$Yes -PushAfterTag:$Push -CreateReleaseAfterPush:$CreateGitHubRelease -UseTagNotesFallback:$UseTagNotes }
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
            'release' { Invoke-ReleaseFlow -DryRunMode:$DryRun -AssumeYes:$Yes -PushAfterTag:$Push -CreateReleaseAfterPush:$CreateGitHubRelease -UseTagNotesFallback:$UseTagNotes; exit 0 }
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
