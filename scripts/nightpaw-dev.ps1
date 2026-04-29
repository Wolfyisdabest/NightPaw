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
            $commandOutput = & $candidate.Command @($candidate.PrefixArgs + $Arguments) 2>&1
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{
                    Success = $true
                    Command = $candidate.Command
                    PrefixArgs = @($candidate.PrefixArgs)
                    ExitCode = 0
                    Output = @($commandOutput | ForEach-Object { "$_" })
                }
            }

            $lastFailure = [pscustomobject]@{
                Success = $false
                Command = $candidate.Command
                PrefixArgs = @($candidate.PrefixArgs)
                ExitCode = $LASTEXITCODE
                Output = @($commandOutput | ForEach-Object { "$_" })
            }
        }
        catch {
            $lastFailure = [pscustomobject]@{
                Success = $false
                Command = $candidate.Command
                PrefixArgs = @($candidate.PrefixArgs)
                ExitCode = 1
                Output = @($_ | Out-String)
            }
        }
    }

    if ($null -eq $lastFailure) {
        return [pscustomobject]@{
            Success = $false
            Command = $null
            PrefixArgs = @()
            ExitCode = 1
            Output = @()
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

function Get-TrackedDiffPreview {
    param([int]$MaxLines = 120)

    Assert-GitRepository
    $result = Invoke-Git -Arguments @('diff', 'HEAD', '--no-ext-diff', '--no-color', '--unified=0', '--minimal') -AllowFailure
    if ($result.ExitCode -ne 0) {
        return ''
    }

    $lines = @($result.Output | Select-Object -First $MaxLines)
    if ($lines.Count -eq 0) {
        return ''
    }

    return ($lines -join "`n")
}

function Get-CommitHintSignals {
    param(
        [string[]]$ChangedPaths,
        [string]$DiffText
    )

    $normalized = @(
        $ChangedPaths |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_.ToLowerInvariant() }
    )
    $diffLower = if ([string]::IsNullOrWhiteSpace($DiffText)) { '' } else { $DiffText.ToLowerInvariant() }

    $docsOnly = ($normalized.Count -gt 0) -and (@($normalized | Where-Object { $_ -notmatch '^(readme\.md|docs/|changelog\.md$|license$)' }).Count -eq 0)
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

    $hasReleaseFlow = ($diffLower -match 'push commit and tags to origin now' -or $diffLower -match 'create github release' -or $diffLower -match 'gh release create' -or $diffLower -match 'pushtag' -or $diffLower -match 'creategithubrelease')
    $hasReleaseNotes = ($diffLower -match 'notes-file' -or $diffLower -match 'generated release notes preview' -or $diffLower -match 'notes-from-tag' -or $diffLower -match 'groupedreleasenotes')
    $hasCommitHeuristics = ($diffLower -match 'suggestedcommittype' -or $diffLower -match 'suggestedcommitmessage' -or $diffLower -match 'commit suggestion' -or $diffLower -match 'commit subject')
    $hasBotCheck = (@($normalized | Where-Object { $_ -eq 'scripts/nightpaw-dev.ps1' }).Count -gt 0) -and ($diffLower -match 'bot check|invokepythoncandidates|compileall|success')
    $hasRustCheck = (@($normalized | Where-Object { $_ -eq 'scripts/nightpaw-dev.ps1' }).Count -gt 0) -and ($diffLower -match 'rust helper check|cargo test|maturin|nightpaw_rs')
    $hasMenuFlow = (@($normalized | Where-Object { $_ -eq 'scripts/nightpaw-dev.ps1' }).Count -gt 0) -and ($diffLower -match 'nightpaw developer console|choose an option|argument types do not match')
    $hasWrapperChanges = @($normalized | Where-Object { $_ -match '^scripts/(commit|commit_context|dev|release)\.ps1$' }).Count -gt 0
    $hasLicenseDocs = @($normalized | Where-Object { $_ -eq 'license' -or $_ -eq 'readme.md' }).Count -gt 0 -and ($diffLower -match 'gnu affero|agpl|license')

    return [pscustomobject]@{
        Normalized = $normalized
        DiffText = $diffLower
        DocsOnly = $docsOnly
        TestsOnly = $testsOnly
        ScriptsOnly = $scriptsOnly
        CiOnly = $ciOnly
        HasRustHelper = $hasRustHelper
        HasBuildFiles = $hasBuildFiles
        HasPerfHints = $hasPerfHints
        HasUserFacingCode = $hasUserFacingCode
        HasReleaseFlow = $hasReleaseFlow
        HasReleaseNotes = $hasReleaseNotes
        HasCommitHeuristics = $hasCommitHeuristics
        HasBotCheck = $hasBotCheck
        HasRustCheck = $hasRustCheck
        HasMenuFlow = $hasMenuFlow
        HasWrapperChanges = $hasWrapperChanges
        HasLicenseDocs = $hasLicenseDocs
    }
}

function Get-UniqueCommitSuggestion {
    param(
        [string[]]$Candidates,
        [string[]]$RecentCommitSubjects
    )

    $recentNormalized = @(
        $RecentCommitSubjects |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_.Trim().ToLowerInvariant() }
    )

    foreach ($candidate in @($Candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $normalizedCandidate = $candidate.Trim().ToLowerInvariant()
        if ($recentNormalized -notcontains $normalizedCandidate) {
            return $candidate.Trim()
        }
    }

    return (@($Candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1) + @('update current changes'))[0]
}

function Get-SuggestedCommitType {
    param(
        [string[]]$ChangedPaths,
        [string[]]$RecentCommitSubjects,
        [string]$DiffText
    )

    if (-not $ChangedPaths -or $ChangedPaths.Count -eq 0) {
        return 'chore'
    }

    $signals = Get-CommitHintSignals -ChangedPaths $ChangedPaths -DiffText $DiffText
    $recentText = ((@($RecentCommitSubjects | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join "`n")).ToLowerInvariant()

    if ($signals.DocsOnly) { return 'docs' }
    if ($signals.TestsOnly) { return 'test' }
    if ($signals.CiOnly) { return 'ci' }
    if ($signals.HasRustHelper) { return 'feat' }
    if ($signals.HasBuildFiles -and -not $signals.HasUserFacingCode) { return 'build' }
    if ($signals.HasPerfHints -and $recentText -match 'perf') { return 'perf' }
    if ($signals.ScriptsOnly) {
        if ($signals.HasBotCheck -or $signals.HasMenuFlow -or $signals.HasCommitHeuristics) { return 'fix' }
        if ($signals.HasReleaseFlow -or $signals.HasReleaseNotes) { return 'feat' }
        if ($signals.HasWrapperChanges) { return 'refactor' }
        return 'chore'
    }
    if ($signals.HasUserFacingCode) { return 'feat' }
    if ($signals.HasBuildFiles) { return 'build' }
    return 'refactor'
}

function Get-SuggestedCommitMessage {
    param(
        [string]$CommitType,
        [string[]]$ChangedPaths,
        [string[]]$RecentCommitSubjects,
        [string]$DiffText
    )

    $signals = Get-CommitHintSignals -ChangedPaths $ChangedPaths -DiffText $DiffText
    $normalized = @($signals.Normalized)

    if ($signals.HasRustHelper) {
        return 'add optional Rust-backed service helpers'
    }
    if ($signals.DocsOnly) {
        if ($signals.HasLicenseDocs) {
            return 'document AGPL licensing requirements'
        }
        if (@($normalized | Where-Object { $_ -eq 'docs/dev-helper.md' -or $_ -match '^scripts/' }).Count -gt 0) {
            return 'document developer helper workflow'
        }
        return 'update developer documentation'
    }
    if ($signals.TestsOnly) {
        $testPath = @($normalized | Where-Object { $_ -like 'tests/*' } | Select-Object -First 1)
        if ($testPath.Count -gt 0) {
            return ("add coverage for {0}" -f ([System.IO.Path]::GetFileNameWithoutExtension($testPath[0]).Replace('_', ' ')))
        }
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($signals.ScriptsOnly) {
        if ($signals.HasCommitHeuristics) {
            $candidates.Add('improve commit suggestion heuristics')
            $candidates.Add('fix developer console commit suggestions')
        }
        if ($signals.HasReleaseNotes) {
            $candidates.Add('generate GitHub release notes from commit history')
            $candidates.Add('improve generated release notes')
        }
        if ($signals.HasReleaseFlow) {
            $candidates.Add('restore guided release push and publish flow')
            $candidates.Add('improve developer console release flow')
        }
        if ($signals.HasBotCheck) {
            $candidates.Add('fix developer console bot check handling')
        }
        if ($signals.HasRustCheck) {
            $candidates.Add('improve Rust helper validation flow')
        }
        if ($signals.HasMenuFlow) {
            $candidates.Add('fix developer console menu action handling')
        }
        if ($signals.HasWrapperChanges) {
            $candidates.Add('align helper wrapper argument forwarding')
        }
    }

    switch ($CommitType) {
        'docs' { $candidates.Add('update project documentation') }
        'test' { $candidates.Add('add coverage for current changes') }
        'build' { $candidates.Add('update development dependencies') }
        'ci' { $candidates.Add('adjust CI workflow behavior') }
        'refactor' { $candidates.Add('refine developer console helper structure') }
        'chore' { $candidates.Add('refresh developer tooling') }
        'perf' { $candidates.Add('improve helper performance') }
        'fix' {
            $candidates.Add('fix developer console helper behavior')
            $candidates.Add('fix current helper flow')
        }
        default {
            $candidates.Add('add developer workflow improvements')
            $candidates.Add('expand developer console workflow')
        }
    }

    return Get-UniqueCommitSuggestion -Candidates @($candidates) -RecentCommitSubjects $RecentCommitSubjects
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
    $diffPreview = Get-TrackedDiffPreview
    $suggestedType = Get-SuggestedCommitType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits -DiffText $diffPreview
    $suggestedMessage = Get-SuggestedCommitMessage -CommitType $suggestedType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits -DiffText $diffPreview

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
    $diffPreview = Get-TrackedDiffPreview
    $suggestedType = Get-SuggestedCommitType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits -DiffText $diffPreview
    $suggestedMessage = Get-SuggestedCommitMessage -CommitType $suggestedType -ChangedPaths $changed.All -RecentCommitSubjects $recentCommits -DiffText $diffPreview

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

function Get-CurrentHeadCommit {
    $result = Invoke-Git -Arguments @('rev-parse', 'HEAD')
    $commit = (($result.Output | Select-Object -First 1) | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($commit)) {
        throw 'Unable to determine the current HEAD commit.'
    }
    return $commit
}

function Get-ShortCommitId {
    param([string]$Commit)

    if ([string]::IsNullOrWhiteSpace($Commit)) {
        return '(none)'
    }
    if ($Commit.Length -le 12) {
        return $Commit
    }
    return $Commit.Substring(0, 12)
}

function Get-LocalTagCommit {
    param([Parameter(Mandatory)][string]$Tag)

    $result = Invoke-Git -Arguments @('rev-list', '-n', '1', $Tag) -AllowFailure
    if ($result.ExitCode -ne 0) {
        return $null
    }

    $commit = (($result.Output | Select-Object -First 1) | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($commit)) {
        return $null
    }

    return $commit
}

function Get-RemoteTagCommit {
    param([Parameter(Mandatory)][string]$Tag)

    $result = Invoke-Git -Arguments @('ls-remote', '--tags', 'origin', "refs/tags/$Tag", "refs/tags/$Tag^{}") -AllowFailure
    if ($result.ExitCode -ne 0) {
        return $null
    }

    $lines = @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($lines.Count -eq 0) {
        return $null
    }

    foreach ($line in $lines) {
        $parts = $line -split '\s+'
        if ($parts.Count -ge 2 -and $parts[1].Trim() -eq "refs/tags/$Tag^{}") {
            return $parts[0].Trim()
        }
    }

    $firstParts = $lines[0] -split '\s+'
    if ($firstParts.Count -ge 1) {
        return $firstParts[0].Trim()
    }

    return $null
}

function Get-RemoteTagInfo {
    param([Parameter(Mandatory)][string]$Tag)

    $result = Invoke-Git -Arguments @('ls-remote', '--tags', 'origin', "refs/tags/$Tag", "refs/tags/$Tag^{}") -AllowFailure
    if ($result.ExitCode -ne 0) {
        return [pscustomobject]@{
            Checked = $false
            Exists = $false
            Commit = $null
            Status = 'unknown'
        }
    }

    $lines = @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($lines.Count -eq 0) {
        return [pscustomobject]@{
            Checked = $true
            Exists = $false
            Commit = $null
            Status = 'missing'
        }
    }

    $commit = $null
    foreach ($line in $lines) {
        $parts = $line -split '\s+'
        if ($parts.Count -ge 2 -and $parts[1].Trim() -eq "refs/tags/$Tag^{}") {
            $commit = $parts[0].Trim()
            break
        }
    }

    if ([string]::IsNullOrWhiteSpace($commit)) {
        $firstParts = $lines[0] -split '\s+'
        if ($firstParts.Count -ge 1) {
            $commit = $firstParts[0].Trim()
        }
    }

    return [pscustomobject]@{
        Checked = $true
        Exists = (-not [string]::IsNullOrWhiteSpace($commit))
        Commit = $commit
        Status = $(if ([string]::IsNullOrWhiteSpace($commit)) { 'missing' } else { 'present' })
    }
}

function Test-RemoteTagExists {
    param([Parameter(Mandatory)][string]$Tag)
    $remoteInfo = Get-RemoteTagInfo -Tag $Tag
    return ($remoteInfo.Checked -and $remoteInfo.Exists)
}

function Invoke-ReleasePush {
    param(
        [Parameter(Mandatory)][string]$Branch,
        [Parameter(Mandatory)][string]$Tag,
        [switch]$IncludeTags
    )

    $pushArgs = @('push', 'origin', $Branch)
    if ($IncludeTags) {
        $pushArgs += '--tags'
    }

    $result = Invoke-Git -Arguments $pushArgs -AllowFailure
    $combinedOutput = @($result.Output) -join "`n"
    $tagAvailableOnRemote = Test-RemoteTagExists -Tag $Tag
    $branchRejected = ($combinedOutput -match [regex]::Escape("$Branch -> $Branch") -and $combinedOutput -match 'rejected')

    return [pscustomobject]@{
        Succeeded = ($result.ExitCode -eq 0)
        ExitCode = $result.ExitCode
        Output = @($result.Output)
        TagAvailableOnRemote = $tagAvailableOnRemote
        BranchRejected = $branchRejected
    }
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
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string[]]$Notes,
        [switch]$UseTagNotesFallback
    )

    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-WarnLine 'GitHub CLI is not available. You can create the GitHub release manually later.'
        return $false
    }

    $noteLines = @($Notes)
    $hasVisibleNotes = @($noteLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -gt 0
    if (-not $hasVisibleNotes) {
        throw "Generated release notes for $Tag are empty. Aborting before calling gh release create."
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
            Set-Content -LiteralPath $notesPath -Value $noteLines -Encoding UTF8
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

function Get-BranchSyncStatus {
    param([Parameter(Mandatory)][string]$Branch)

    $remoteRef = "refs/remotes/origin/$Branch"
    $existsResult = Invoke-Git -Arguments @('show-ref', '--verify', $remoteRef) -AllowFailure
    if ($existsResult.ExitCode -ne 0) {
        return [pscustomobject]@{
            RemoteRef = "origin/$Branch"
            Exists = $false
            Ahead = 0
            Behind = 0
            Status = 'no-upstream'
        }
    }

    $countResult = Invoke-Git -Arguments @('rev-list', '--left-right', '--count', "$remoteRef...HEAD") -AllowFailure
    if ($countResult.ExitCode -ne 0) {
        return [pscustomobject]@{
            RemoteRef = "origin/$Branch"
            Exists = $true
            Ahead = 0
            Behind = 0
            Status = 'unknown'
        }
    }

    $raw = (($countResult.Output | Select-Object -First 1) | Out-String).Trim()
    $parts = @($raw -split '\s+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($parts.Count -lt 2) {
        return [pscustomobject]@{
            RemoteRef = "origin/$Branch"
            Exists = $true
            Ahead = 0
            Behind = 0
            Status = 'unknown'
        }
    }

    $behind = 0
    $ahead = 0
    [void][int]::TryParse($parts[0], [ref]$behind)
    [void][int]::TryParse($parts[1], [ref]$ahead)

    $status = 'aligned'
    if ($ahead -gt 0 -and $behind -gt 0) {
        $status = 'diverged'
    }
    elseif ($ahead -gt 0) {
        $status = 'ahead'
    }
    elseif ($behind -gt 0) {
        $status = 'behind'
    }

    return [pscustomobject]@{
        RemoteRef = "origin/$Branch"
        Exists = $true
        Ahead = $ahead
        Behind = $behind
        Status = $status
    }
}

function Get-GitHubReleaseStatus {
    param([Parameter(Mandatory)][string]$Tag)

    if (-not (Test-CommandAvailable -Name 'gh')) {
        return [pscustomobject]@{
            Checked = $false
            Exists = $false
            Status = 'unknown (gh unavailable)'
            Url = $null
        }
    }

    $stderrPath = [System.IO.Path]::GetTempFileName()
    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& gh release view $Tag --json tagName,url 2>$stderrPath)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }

    $stderrLines = @()
    if (Test-Path -LiteralPath $stderrPath) {
        $stderrLines = @(Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue)
        Remove-Item -LiteralPath $stderrPath -ErrorAction SilentlyContinue
    }

    if ($exitCode -eq 0) {
        $jsonText = ($output -join "`n").Trim()
        $url = $null
        if (-not [string]::IsNullOrWhiteSpace($jsonText)) {
            try {
                $json = $jsonText | ConvertFrom-Json
                $url = [string]$json.url
            }
            catch {
                $url = $null
            }
        }

        return [pscustomobject]@{
            Checked = $true
            Exists = $true
            Status = 'yes'
            Url = $url
        }
    }

    $stderrText = (($stderrLines -join "`n").Trim()).ToLowerInvariant()
    if ($stderrText -match 'release not found' -or $stderrText -match 'http 404') {
        return [pscustomobject]@{
            Checked = $true
            Exists = $false
            Status = 'no'
            Url = $null
        }
    }

    return [pscustomobject]@{
        Checked = $false
        Exists = $false
        Status = 'unknown (gh check failed)'
        Url = $null
    }
}

function Get-ReleaseStateSnapshot {
    param(
        [Parameter(Mandatory)][string]$Tag,
        [Parameter(Mandatory)][string]$Branch,
        [switch]$IsDetachedHead
    )

    $headCommit = Get-CurrentHeadCommit
    $localTagCommit = Get-LocalTagCommit -Tag $Tag
    $remoteTagInfo = Get-RemoteTagInfo -Tag $Tag
    $gitHubRelease = Get-GitHubReleaseStatus -Tag $Tag
    $branchSync = if ($IsDetachedHead) {
        [pscustomobject]@{
            RemoteRef = '(detached)'
            Exists = $false
            Ahead = 0
            Behind = 0
            Status = 'detached'
        }
    }
    else {
        Get-BranchSyncStatus -Branch $Branch
    }

    return [pscustomobject]@{
        Tag = $Tag
        HeadCommit = $headCommit
        LocalTagCommit = $localTagCommit
        LocalTagExists = (-not [string]::IsNullOrWhiteSpace($localTagCommit))
        RemoteTagCommit = $remoteTagInfo.Commit
        RemoteTagExists = $remoteTagInfo.Exists
        RemoteTagChecked = $remoteTagInfo.Checked
        RemoteTagStatus = $remoteTagInfo.Status
        GitHubRelease = $gitHubRelease
        BranchSync = $branchSync
    }
}

function Show-ReleaseState {
    param([Parameter(Mandatory)][pscustomobject]$ReleaseState)

    Write-Section 'Release Status'
    Write-InfoLine ("Current HEAD: {0}" -f (Get-ShortCommitId -Commit $ReleaseState.HeadCommit))
    Write-InfoLine ("Local tag target (peeled commit): {0}" -f $(if ($ReleaseState.LocalTagExists) { Get-ShortCommitId -Commit $ReleaseState.LocalTagCommit } else { '(missing)' }))
    Write-InfoLine ("Remote tag target (peeled commit): {0}" -f $(if (-not $ReleaseState.RemoteTagChecked) { '(unknown)' } elseif ($ReleaseState.RemoteTagExists) { Get-ShortCommitId -Commit $ReleaseState.RemoteTagCommit } else { '(missing)' }))
    Write-InfoLine ("GitHub release exists: {0}" -f $ReleaseState.GitHubRelease.Status)
    if (-not [string]::IsNullOrWhiteSpace($ReleaseState.GitHubRelease.Url)) {
        Write-InfoLine ("GitHub release URL: {0}" -f $ReleaseState.GitHubRelease.Url)
    }

    $branchStatus = switch ($ReleaseState.BranchSync.Status) {
        'aligned' { 'aligned with origin' }
        'ahead' { "ahead of origin by $($ReleaseState.BranchSync.Ahead)" }
        'behind' { "behind origin by $($ReleaseState.BranchSync.Behind)" }
        'diverged' { "diverged (ahead $($ReleaseState.BranchSync.Ahead), behind $($ReleaseState.BranchSync.Behind))" }
        'no-upstream' { 'no origin tracking branch found' }
        'detached' { 'detached HEAD' }
        default { 'unknown' }
    }
    Write-InfoLine ("Branch sync: {0}" -f $branchStatus)
}

function Assert-ReleaseTagMatchesHead {
    param(
        [Parameter(Mandatory)][string]$Tag,
        [Parameter(Mandatory)][string]$HeadCommit,
        [string]$LocalTagCommit,
        [string]$RemoteTagCommit
    )

    if (-not [string]::IsNullOrWhiteSpace($LocalTagCommit) -and $LocalTagCommit -ne $HeadCommit) {
        throw ("Local tag {0} points to {1}, but HEAD is {2}. Do not delete or move it automatically. Inspect with 'git show {0}' and choose a new version or fix the release state manually." -f $Tag, (Get-ShortCommitId -Commit $LocalTagCommit), (Get-ShortCommitId -Commit $HeadCommit))
    }

    if (-not [string]::IsNullOrWhiteSpace($RemoteTagCommit) -and $RemoteTagCommit -ne $HeadCommit) {
        throw ("Remote tag {0} on origin points to {1}, but HEAD is {2}. Do not force-push or delete tags automatically. Fetch, inspect 'git show {0}', and choose a new version or reconcile the release state manually." -f $Tag, (Get-ShortCommitId -Commit $RemoteTagCommit), (Get-ShortCommitId -Commit $HeadCommit))
    }
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

function ConvertFrom-SemVerTag {
    param([string]$Tag)

    if (-not (Test-IsSemVerTag -Tag $Tag)) {
        return $null
    }

    $parts = $Tag.TrimStart('v').Split('.')
    return [pscustomobject]@{
        Tag = $Tag
        Major = [int]$parts[0]
        Minor = [int]$parts[1]
        Patch = [int]$parts[2]
    }
}

function Compare-SemVerTags {
    param(
        [string]$LeftTag,
        [string]$RightTag
    )

    $left = ConvertFrom-SemVerTag -Tag $LeftTag
    $right = ConvertFrom-SemVerTag -Tag $RightTag

    if ($null -eq $left -or $null -eq $right) {
        throw 'Compare-SemVerTags requires two valid semver tags.'
    }

    if ($left.Major -ne $right.Major) {
        return [Math]::Sign($left.Major - $right.Major)
    }
    if ($left.Minor -ne $right.Minor) {
        return [Math]::Sign($left.Minor - $right.Minor)
    }
    return [Math]::Sign($left.Patch - $right.Patch)
}

function Get-HighestSemVerTag {
    param([string[]]$Tags)

    $validTags = @($Tags | Where-Object { Test-IsSemVerTag -Tag $_ } | Sort-Object -Unique)
    if ($validTags.Count -eq 0) {
        return $null
    }

    $highest = $validTags[0]
    foreach ($tag in $validTags[1..($validTags.Count - 1)]) {
        if ((Compare-SemVerTags -LeftTag $tag -RightTag $highest) -gt 0) {
            $highest = $tag
        }
    }
    return $highest
}

function Get-AllLocalSemVerTags {
    $result = Invoke-Git -Arguments @('tag', '--list') -AllowFailure
    if ($result.ExitCode -ne 0) {
        return @()
    }

    return @($result.Output | Where-Object { Test-IsSemVerTag -Tag $_ } | Sort-Object -Unique)
}

function Get-AllRemoteSemVerTags {
    $result = Invoke-Git -Arguments @('ls-remote', '--tags', 'origin') -AllowFailure
    if ($result.ExitCode -ne 0) {
        return [pscustomobject]@{
            Checked = $false
            Tags = @()
        }
    }

    $tags = New-Object System.Collections.Generic.List[string]
    foreach ($line in @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $parts = $line -split '\s+'
        if ($parts.Count -lt 2) {
            continue
        }

        $refName = $parts[1].Trim()
        if ($refName -notlike 'refs/tags/*') {
            continue
        }

        $tagName = $refName.Substring('refs/tags/'.Length)
        if ($tagName.EndsWith('^{}')) {
            $tagName = $tagName.Substring(0, $tagName.Length - 3)
        }

        if (Test-IsSemVerTag -Tag $tagName) {
            $tags.Add($tagName)
        }
    }

    return [pscustomobject]@{
        Checked = $true
        Tags = @($tags | Sort-Object -Unique)
    }
}

function Get-GitHubReleaseTags {
    if (-not (Test-CommandAvailable -Name 'gh')) {
        return [pscustomobject]@{
            Checked = $false
            Tags = @()
            Status = 'gh unavailable'
        }
    }

    $stderrPath = [System.IO.Path]::GetTempFileName()
    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& gh release list --limit 100 --json tagName 2>$stderrPath)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }

    $stderrLines = @()
    if (Test-Path -LiteralPath $stderrPath) {
        $stderrLines = @(Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue)
        Remove-Item -LiteralPath $stderrPath -ErrorAction SilentlyContinue
    }

    if ($exitCode -ne 0) {
        return [pscustomobject]@{
            Checked = $false
            Tags = @()
            Status = (($stderrLines -join ' ').Trim())
        }
    }

    $jsonText = ($output -join "`n").Trim()
    $tags = @()
    if (-not [string]::IsNullOrWhiteSpace($jsonText)) {
        try {
            $items = $jsonText | ConvertFrom-Json
            $tags = @($items | ForEach-Object { [string]$_.tagName } | Where-Object { Test-IsSemVerTag -Tag $_ } | Sort-Object -Unique)
        }
        catch {
            $tags = @()
        }
    }

    return [pscustomobject]@{
        Checked = $true
        Tags = @($tags)
        Status = 'ok'
    }
}

function Get-ReservedReleaseVersions {
    $localTags = @(Get-AllLocalSemVerTags)
    $remoteInfo = Get-AllRemoteSemVerTags
    $releaseInfo = Get-GitHubReleaseTags
    $allTags = @($localTags + @($remoteInfo.Tags) + @($releaseInfo.Tags) | Where-Object { Test-IsSemVerTag -Tag $_ } | Sort-Object -Unique)
    $highestReserved = Get-HighestSemVerTag -Tags $allTags

    return [pscustomobject]@{
        Tags = @($allTags)
        Highest = $highestReserved
        LocalTags = @($localTags)
        RemoteChecked = $remoteInfo.Checked
        RemoteTags = @($remoteInfo.Tags)
        GitHubChecked = $releaseInfo.Checked
        GitHubTags = @($releaseInfo.Tags)
        GitHubStatus = $releaseInfo.Status
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

function Get-NextAvailableVersion {
    param(
        [string]$BaseTag,
        [string]$BumpType,
        [string[]]$ReservedTags
    )

    $candidate = Get-NextVersion -LatestTag $BaseTag -BumpType $BumpType
    $reserved = @($ReservedTags | Where-Object { Test-IsSemVerTag -Tag $_ } | Sort-Object -Unique)
    while ($reserved -contains $candidate) {
        $candidate = Get-NextVersion -LatestTag $candidate -BumpType 'patch'
    }
    return $candidate
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
    $reservedVersions = Get-ReservedReleaseVersions

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
        HighestReservedVersion = $reservedVersions.Highest
        ReservedVersions = @($reservedVersions.Tags)
        RemoteVersionCheckSucceeded = $reservedVersions.RemoteChecked
        GitHubVersionCheckSucceeded = $reservedVersions.GitHubChecked
        GitHubVersionCheckStatus = $reservedVersions.GitHubStatus
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
        ProposedVersion = Get-NextAvailableVersion -BaseTag $latestTag -BumpType $bumpType -ReservedTags $reservedVersions.Tags
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
    $releaseState = Get-ReleaseStateSnapshot -Tag $analysis.ProposedVersion -Branch $analysis.Branch -IsDetachedHead:$analysis.IsDetachedHead

    Write-Header 'NightPaw Release Helper'
    Write-InfoLine ("Latest reachable tag: {0}" -f $(if ($analysis.LatestTag) { $analysis.LatestTag } else { 'none' }))
    Write-InfoLine ("Highest reserved version: {0}" -f $(if ($analysis.HighestReservedVersion) { $analysis.HighestReservedVersion } else { 'none' }))
    Write-InfoLine ("Current branch: {0}" -f $analysis.Branch)
    Write-InfoLine ("Working tree clean: {0}" -f $(if ($analysis.Status.IsClean) { 'yes' } else { 'no' }))
    Write-InfoLine ("Release recommended: {0}" -f $(if ($analysis.ReleaseRecommended) { 'yes' } else { 'no' }))
    Write-InfoLine ("Recommended bump: {0}" -f $analysis.BumpType)
    Write-InfoLine ("Proposed version: {0}" -f $analysis.ProposedVersion)
    if ($analysis.IsDetachedHead) {
        Write-WarnLine 'Detached HEAD detected. The helper will not push automatically from this state.'
    }
    Show-ReleaseState -ReleaseState $releaseState

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

    Assert-ReleaseTagMatchesHead -Tag $analysis.ProposedVersion -HeadCommit $releaseState.HeadCommit -LocalTagCommit $releaseState.LocalTagCommit -RemoteTagCommit $releaseState.RemoteTagCommit

    $releaseArtifactsExist = $releaseState.LocalTagExists -or $releaseState.RemoteTagExists -or $releaseState.GitHubRelease.Exists
    if ($releaseArtifactsExist) {
        Write-WarnLine ("Release artifacts for {0} already exist. The helper will not rewrite CHANGELOG.md automatically." -f $analysis.ProposedVersion)
    }

    if ($DryRunMode) {
        Write-WarnLine 'Dry run only. No tag was created.'
        return
    }
    if (-not $releaseState.RemoteTagChecked) {
        Write-WarnLine ("Remote tag state for {0} could not be verified. Resolve git remote access first, then rerun the release helper." -f $analysis.ProposedVersion)
        return
    }
    if ($releaseState.GitHubRelease.Exists) {
        Write-SuccessLine ("GitHub release for {0} already exists." -f $analysis.ProposedVersion)
        if (-not [string]::IsNullOrWhiteSpace($releaseState.GitHubRelease.Url)) {
            Write-InfoLine ("Release URL: {0}" -f $releaseState.GitHubRelease.Url)
        }
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
    if ($releaseState.BranchSync.Status -in @('behind', 'diverged')) {
        Write-WarnLine ("Current branch is {0} relative to {1}. Pull or rebase before creating or publishing this release." -f $releaseState.BranchSync.Status, $releaseState.BranchSync.RemoteRef)
        return
    }

    $tagExistsAtHead = ($releaseState.LocalTagExists -or $releaseState.RemoteTagExists)
    if ((-not $tagExistsAtHead) -and $changelogPreview.RequiresWrite) {
        if (-not (Confirm-Action -Prompt ("Write CHANGELOG.md entry for {0}? [y/N]" -f $analysis.ProposedVersion) -AssumeYes:$AssumeYes)) {
            Write-WarnLine 'Release canceled before CHANGELOG.md update.'
            return
        }

        Write-ChangelogFile -ChangelogPath $changelogPreview.Path -ContentLines $changelogPreview.UpdatedContent
        Write-WarnLine 'CHANGELOG.md was updated. Commit it before or with the release, then rerun the release command.'
        return
    }

    if ($releaseState.LocalTagExists) {
        Write-InfoLine ("Local tag {0} already points to HEAD. Skipping local tag creation." -f $analysis.ProposedVersion)
    }
    else {
        if ($releaseState.RemoteTagExists) {
            Write-InfoLine ("Remote tag {0} already points to HEAD. Skipping local tag creation." -f $analysis.ProposedVersion)
        }
        else {
            if (-not (Confirm-Action -Prompt ("Create annotated tag {0}? [y/N]" -f $analysis.ProposedVersion) -AssumeYes:$AssumeYes)) {
                Write-WarnLine 'Release canceled.'
                return
            }

            Invoke-Git -Arguments @('tag', '-a', $analysis.ProposedVersion, '-m', ("NightPaw {0}" -f $analysis.ProposedVersion)) | Out-Null
            Write-SuccessLine ("Created annotated tag {0}." -f $analysis.ProposedVersion)
            $releaseState = Get-ReleaseStateSnapshot -Tag $analysis.ProposedVersion -Branch $analysis.Branch -IsDetachedHead:$analysis.IsDetachedHead
            Assert-ReleaseTagMatchesHead -Tag $analysis.ProposedVersion -HeadCommit $releaseState.HeadCommit -LocalTagCommit $releaseState.LocalTagCommit -RemoteTagCommit $releaseState.RemoteTagCommit
        }
    }

    $didPush = $false
    $branchPushCompleted = $false
    $tagAvailableOnRemote = $false
    $shouldPush = $PushAfterTag
    if ($analysis.IsDetachedHead) {
        $shouldPush = $false
        Write-WarnLine 'Detached HEAD detected. Skipping push.'
    }
    elseif (-not $shouldPush) {
        $shouldPush = Confirm-Action -Prompt 'Push current branch and tags to origin now? [y/N]'
    }

    if ($shouldPush) {
        $includeTags = (-not $releaseState.RemoteTagExists)
        if ($releaseState.RemoteTagExists -and $releaseState.BranchSync.Status -eq 'aligned') {
            Write-InfoLine ("Remote tag {0} already exists and branch {1} is aligned with origin. No push was needed." -f $analysis.ProposedVersion, $analysis.Branch)
        }
        else {
            $pushResult = Invoke-ReleasePush -Branch $analysis.Branch -Tag $analysis.ProposedVersion -IncludeTags:$includeTags
            $didPush = $pushResult.Succeeded
            $tagAvailableOnRemote = $pushResult.TagAvailableOnRemote
            $releaseState = Get-ReleaseStateSnapshot -Tag $analysis.ProposedVersion -Branch $analysis.Branch -IsDetachedHead:$analysis.IsDetachedHead
            $branchPushCompleted = ($releaseState.BranchSync.Status -eq 'aligned')

            if ($pushResult.Succeeded) {
                if ($includeTags) {
                    Write-SuccessLine ("Pushed branch {0} and release tag {1} to origin." -f $analysis.Branch, $analysis.ProposedVersion)
                }
                else {
                    Write-SuccessLine ("Pushed branch {0} to origin. Release tag {1} was already present on origin." -f $analysis.Branch, $analysis.ProposedVersion)
                }
            }
            else {
                if ($pushResult.TagAvailableOnRemote) {
                    Write-WarnLine ("Tag {0} is available on origin, but branch {1} was not fully pushed." -f $analysis.ProposedVersion, $analysis.Branch)
                    if ($pushResult.BranchRejected -or $releaseState.BranchSync.Status -in @('behind', 'diverged')) {
                        Write-WarnLine ("Branch {0} is not aligned with origin. Pull or rebase, then push the branch separately before creating a GitHub release." -f $analysis.Branch)
                    }
                }
                else {
                    throw ("git push origin {0}{1} failed with exit code {2}." -f $analysis.Branch, $(if ($includeTags) { ' --tags' } else { '' }), $pushResult.ExitCode)
                }
            }
        }
    }
    else {
        Write-InfoLine 'No push was performed.'
        Write-InfoLine 'Next manual command:'
        if ($analysis.IsDetachedHead) {
            Write-InfoLine 'git push origin <branch-name> --tags'
        }
        elseif ($releaseState.RemoteTagExists) {
            Write-InfoLine ("git push origin {0}" -f $analysis.Branch)
        }
        else {
            Write-InfoLine ("git push origin {0} --tags" -f $analysis.Branch)
        }
    }
    elseif ($releaseState.RemoteTagExists -and $releaseState.BranchSync.Status -eq 'aligned') {
        $branchPushCompleted = $true
    }

    $shouldCreateGitHubRelease = $false
    $releaseState = Get-ReleaseStateSnapshot -Tag $analysis.ProposedVersion -Branch $analysis.Branch -IsDetachedHead:$analysis.IsDetachedHead
    if ($CreateReleaseAfterPush) {
        if ($releaseState.GitHubRelease.Exists) {
            Write-SuccessLine ("GitHub release for {0} already exists." -f $analysis.ProposedVersion)
            if (-not [string]::IsNullOrWhiteSpace($releaseState.GitHubRelease.Url)) {
                Write-InfoLine ("Release URL: {0}" -f $releaseState.GitHubRelease.Url)
            }
            return
        }
        if ($branchPushCompleted -and $releaseState.RemoteTagExists -and $releaseState.BranchSync.Status -eq 'aligned') {
            $shouldCreateGitHubRelease = $true
        }
        elseif ($releaseState.RemoteTagExists) {
            Write-WarnLine 'GitHub release creation was skipped because the branch is not aligned with origin.'
        }
        else {
            Write-WarnLine 'GitHub release creation was skipped because the release tag is not available on origin yet.'
        }
    }
    elseif ($shouldPush -and -not $branchPushCompleted) {
        Write-WarnLine 'GitHub release creation was skipped because the branch push did not complete cleanly.'
    }
    elseif ($releaseState.RemoteTagExists -and $releaseState.BranchSync.Status -eq 'aligned' -and (Test-CommandAvailable -Name 'gh')) {
        $shouldCreateGitHubRelease = Confirm-Action -Prompt 'Create GitHub release with gh now? [y/N]'
    }
    elseif ($releaseState.RemoteTagExists -and $releaseState.BranchSync.Status -eq 'aligned') {
        Write-WarnLine 'GitHub CLI is not available. You can create the GitHub release manually later.'
    }

    if ($shouldCreateGitHubRelease) {
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
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string[]]$ContentLines
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
    Write-Host ''
    Write-InfoLine 'Release validation commands:'
    Write-InfoLine '  Fresh release: .\scripts\nightpaw-dev.ps1 release -DryRun'
    Write-InfoLine '  Existing local tag: git tag --list v1.2.0; .\scripts\nightpaw-dev.ps1 release -DryRun'
    Write-InfoLine '  Existing remote tag: git ls-remote --tags origin refs/tags/v1.2.0*; .\scripts\nightpaw-dev.ps1 release -DryRun'
    Write-InfoLine '  Existing GitHub release: gh release view v1.2.0 --json tagName,url'
    Write-InfoLine '  Partial push success: inspect Release Status after a rejected branch push; tag should show on origin while branch sync is behind/diverged'
    Write-InfoLine '  Branch diverged: git rev-list --left-right --count refs/remotes/origin/<branch>...HEAD'
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
