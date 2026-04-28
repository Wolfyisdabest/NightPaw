# NightPaw Unified Developer Helper

NightPaw now uses one main PowerShell entrypoint:

```powershell
.\scripts\nightpaw-dev.ps1
```

It replaces the older fragmented helper workflow with one menu-driven developer console plus direct command mode.

## Commands

```powershell
.\scripts\nightpaw-dev.ps1 status
.\scripts\nightpaw-dev.ps1 context
.\scripts\nightpaw-dev.ps1 commit
.\scripts\nightpaw-dev.ps1 commit -Type feat -Message "add optional Rust-backed service helpers" -Yes
.\scripts\nightpaw-dev.ps1 release -DryRun
.\scripts\nightpaw-dev.ps1 release
.\scripts\nightpaw-dev.ps1 tests
.\scripts\nightpaw-dev.ps1 bot-check
.\scripts\nightpaw-dev.ps1 rust-check
```

It also accepts legacy-style flags such as `--dry-run` and `--help`.

## Commit Flow

- shows git status, grouped changed files, and diff stat first
- suggests a commit type using repo-aware rules
- suggests a default subject and lets Enter accept it
- confirms before staging and committing
- stages tracked and untracked files with normal git ignore rules
- never pushes automatically

For the current Rust-helper subsystem work, the helper should suggest:

```text
feat: add optional Rust-backed service helpers
```

## Release Flow

The release helper now treats release creation as a local annotated tag only.

- `release -DryRun` analyzes the repo and shows what would happen
- real `release` asks for confirmation before tagging
- it never pushes automatically
- after tagging, it prints the next manual command:

```powershell
git push origin main --tags
```

Release recommendations consider the latest semver tag, commits since that tag, current working tree changes, and important paths like `main.py`, `pyproject.toml`, `services/*.py`, `cogs/*.py`, `crates/**`, `README.md`, and `docs/**`.

Version bump rules:

- breaking markers like `BREAKING CHANGE` or `!:` -> major
- `feat` -> minor
- `fix`, `perf`, `refactor`, `build`, `test`, `docs`, `chore` -> patch
- docs-only changes can recommend no release

## Checks

`tests`

- runs `uv run pytest` when `tests/` exists and `uv` is available
- calls out `tests/test_rust_bridge.py` when present

`bot-check`

- prefers a syntax/import safety pass instead of starting the live Discord bot
- runs Python `compileall` over `main.py`, `config.py`, `checks.py`, `services`, and `cogs`

`rust-check`

- runs `cargo test` in `crates/nightpaw_rs` when Cargo is available
- checks whether a `maturin` workflow is reachable through `uv`
- attempts a Python import probe for `nightpaw_rs`

## Compatibility Wrappers

These older scripts stay in place as thin wrappers:

- `.\scripts\dev.ps1`
- `.\scripts\commit.ps1`
- `.\scripts\commit_context.ps1`
- `.\scripts\release.ps1`

## Windows Note

If git warns about LF or CRLF line endings on Windows, that is usually harmless. It only becomes a real concern when files were unexpectedly reformatted or noisy line-ending churn appears in the diff.
