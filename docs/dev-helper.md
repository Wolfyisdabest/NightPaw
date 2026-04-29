# NightPaw Unified Developer Helper

NightPaw uses one local PowerShell entrypoint:

```powershell
.\scripts\nightpaw-dev.ps1
```

The helper is rule-based only. There is no local AI, Ollama, or suggestion-model path in the developer console anymore.

## Commands

```powershell
.\scripts\nightpaw-dev.ps1 status
.\scripts\nightpaw-dev.ps1 context
.\scripts\nightpaw-dev.ps1 commit
.\scripts\nightpaw-dev.ps1 commit -Type feat -Message "add optional Rust-backed service helpers" -Yes
.\scripts\nightpaw-dev.ps1 release -DryRun
.\scripts\nightpaw-dev.ps1 release
.\scripts\nightpaw-dev.ps1 release -Type patch
.\scripts\nightpaw-dev.ps1 release -Push
.\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease
.\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease -UseTagNotes
.\scripts\nightpaw-dev.ps1 tests
.\scripts\nightpaw-dev.ps1 bot-check
.\scripts\nightpaw-dev.ps1 rust-check
```

Legacy-style flags such as `--dry-run`, `--push`, and `--help` are also accepted.

## Status And Commit Context

The helper does not trust `git diff --stat` alone.

It combines:

- `git status --porcelain=v1`
- `git diff --name-status`
- `git diff --cached --name-status`
- `git ls-files --others --exclude-standard`

Status and context output now separates:

- modified tracked files
- staged files
- untracked files that are not ignored
- deleted files
- renamed files

Commit context also shows:

- every file that would be committed by the helper
- explicit untracked files
- a small untracked directory preview when files are clustered inside folders such as `crates/`, `docs/`, `scripts/`, or `tests/`

## Commit Flow

- shows grouped working-tree status first
- suggests a commit type from file-based rules
- includes untracked files in commit-type detection
- suggests a default subject and lets Enter accept it
- stages with `git add --all`
- never pushes automatically

## Release Flow

The release helper uses the latest reachable semver tag plus the current branch name.

- branch detection uses `git rev-parse --abbrev-ref HEAD`
- it never assumes `main`
- detached `HEAD` is called out and automatic push is skipped
- `release -DryRun` previews the release analysis without creating a tag
- real `release` creates only a local annotated tag after confirmation
- after a local tag, it asks whether to push the current branch and tags to `origin`
- if `gh` is available after a successful push, it asks whether to create the GitHub release
- `-Push` and `-CreateGitHubRelease` stay explicit flags
- `-UseTagNotes` keeps `gh --notes-from-tag` as an explicit fallback only
- `-Yes` skips local changelog/tag confirmations only; it does not imply push or GitHub release creation

## Release Analysis Sources

Committed release-range data comes from:

- `git diff --name-status <previousTag>..HEAD`
- `git log <previousTag>..HEAD`

That analysis is shown separately from pending working-tree files so the helper does not blur committed release contents with uncommitted local work.

## Release Notes And Changelog

Generated release notes now include:

- grouped commit sections: `Breaking Changes`, `Added`, `Fixed`, `Changed`, `Performance`, `Docs`, `Build`, `Tests`, `Chore`
- a `Commits` section with `short-hash + subject` for every commit in the release range
- a `Changed Files` section from the actual release diff range
- `Changed Areas` derived from important paths
- a `Pending Working Tree Changes` section in previews when local work is not committed yet

Breaking changes are detected from:

- `BREAKING CHANGE`
- `breaking:`
- conventional commit types with `!`

`CHANGELOG.md` is now part of the release flow:

- dry-run previews the exact changelog section that would be added
- the helper avoids duplicating an existing version section
- if the version section is missing, the helper can write `CHANGELOG.md`
- after writing `CHANGELOG.md`, the helper stops and tells you to commit it before or with the release, then rerun release

## Version Bump Rules

- breaking markers -> major
- `feat` -> minor
- `fix`, `perf`, `refactor`, `build`, `test`, `docs`, `chore`, `ci` -> patch
- docs-only changes recommend no release by default
- script and helper updates after `v1.1.0` now recommend `v1.1.1` instead of being treated as no-op release noise

## Checks

`tests`

- runs `uv run python -m pytest` when `tests/` exists and `uv` is available

`bot-check`

- runs Python `compileall` over `main.py`, `config.py`, `checks.py`, `services`, and `cogs`

`rust-check`

- runs `cargo test` in `crates/nightpaw_rs` when Cargo is available
- checks whether a `maturin` workflow is reachable through `uv`
- attempts a Python import probe for `nightpaw_rs`

## Compatibility Wrappers

These scripts still forward into the unified helper:

- `.\scripts\dev.ps1`
- `.\scripts\commit.ps1`
- `.\scripts\commit_context.ps1`
- `.\scripts\release.ps1`
