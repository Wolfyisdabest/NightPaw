# NightPaw

NightPaw is a local-first Discord bot built around `discord.py`, SQLite, and Ollama. It mixes practical server tools, moderation, diagnostics, wolf-themed lore, and an AI layer that stays inspectable instead of hiding what it is doing.

This project is built for a private or controlled rollout first. It has owner tooling, server control tooling, persistent local state, and an AI system that is tuned for local use rather than hosted API usage.

## Legal

- [Terms of Service](./docs/legal/terms-of-service.md)
- [Privacy Policy](./docs/legal/privacy-policy.md)
- [Legal publishing notes](./docs/legal/README.md)

## License

NightPaw is licensed under the GNU Affero General Public License v3.0.

If you modify and run NightPaw as a public or hosted bot/service, you must make the corresponding source code available under the same license.

See [LICENSE](./LICENSE) for the full official license text.

## Current State

- Local-first runtime
  - Discord bot runs on your own machine
  - AI uses local Ollama models
  - Persistence uses SQLite in `data/nightpaw.db`
- Mixed command surface
  - Prefix commands via `!`
  - Slash commands across the bot
  - Most slash commands support an optional `ephemeral` flag
  - `avatar` is the only slash command hidden by default
- Access-aware help and command routing
  - `General`
  - `Pack`
  - `ServerAdmin`
  - `Alpha`
- AI routing with diagnostics
  - standard chat generation
  - attachment-aware handling
  - deterministic action routing before LLM planning
  - per-turn diagnostics via `aidiag`

## Requirements

- Python 3.14+
- [uv](https://github.com/astral-sh/uv)
- A Discord application and bot token
- A local Ollama install if you want NightPaw AI features

## Dependencies

Declared in [pyproject.toml](./pyproject.toml):

- `discord-py[voice]`
- `python-dotenv`
- `aiosqlite`
- `aiohttp`
- `psutil`
- `ephem`

Development helpers:

- `pytest`
- `maturin`

## Setup

Install dependencies:

```powershell
uv sync
```

Create a `.env` file in the project root:

```env
DISCORD_TOKEN=your_bot_token_here
PREFIX=!
OWNER_ID=your_discord_user_id

BIRTHDAY_CHANNEL_ID=
AUTOMOD_LOG_CHANNEL_ID=
MOD_LOG_CHANNEL_ID=
BOT_LOG_CHANNEL_ID=
BOT_LOG_WEBHOOK=

LOG_LEVEL=INFO
BOT_LOG_WEBHOOK_LEVEL=INFO
BOT_LOG_FILE=nightpaw.log
BOT_LOG_MAX_BYTES=5000000
BOT_LOG_BACKUP_COUNT=5

AI_OLLAMA_URL=http://127.0.0.1:11434
AI_MODEL=llama3.1:8b
AI_VISION_MODEL=gemma3:4b
AI_ATTACHMENT_MAX_BYTES=3500000
AI_MAX_INLINE_ATTACHMENT_CHARS=12000
AI_MAX_ATTACHMENTS=4
AI_TEMPERATURE=0.35
```

Run the bot:

```powershell
uv run main.py
```

## Optional Rust Acceleration

NightPaw stays a Python bot. Rust is only used for small pure helper functions where faster text and filename processing is useful.

Current Rust helpers live in [crates/nightpaw_rs](./crates/nightpaw_rs/):

- `normalize_message(text: str) -> str`
- `chunk_text(text: str, max_chars: int) -> list[str]`
- `classify_attachment(filename: str) -> str`

Python integration lives in [services/rust_bridge.py](./services/rust_bridge.py).

Important behavior:

- Python remains the main application
- if `nightpaw_rs` is not installed, NightPaw falls back to Python implementations automatically
- Discord logic stays in Python; Rust only handles pure utility work

Build the Rust module into the project virtualenv:

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
uv sync --group dev
Push-Location .\crates\nightpaw_rs
..\..\.venv\Scripts\maturin.exe develop
Pop-Location
```

Verify the Rust module is importable:

```powershell
.\.venv\Scripts\python.exe -c "import nightpaw_rs; print(nightpaw_rs.normalize_message('  Hello   WORLD  '))"
```

Run NightPaw with Rust enabled:

```powershell
.\.venv\Scripts\python.exe main.py
```

When to use Rust vs Python:

- use Rust for tight, reusable helpers with measurable text or filename processing cost
- keep Discord API access, service orchestration, database logic, and bot behavior in Python
- prefer Python when the logic is IO-bound, rarely called, or easier to inspect there

## Windows Startup

You can use [start_nightpaw.bat](./start_nightpaw.bat) with Task Scheduler.

Example batch file:

```bat
@echo off
cd /d "%~dp0"
uv run main.py
```

Recommended Task Scheduler settings:

- Run whether user is logged on or not
- Run with highest privileges
- Trigger at startup
- Optional delay: 30 seconds
- Restart on failure

## Project Layout

```text
NightPaw/
├── main.py
├── config.py
├── checks.py
├── pyproject.toml
├── uv.lock
├── start_nightpaw.bat
├── data/
│   ├── nightpaw.db
│   └── startup_snapshot.json
├── cogs/
│   ├── ai.py
│   ├── automod.py
│   ├── avatar.py
│   ├── birthday.py
│   ├── blaze.py
│   ├── cogmanager.py
│   ├── help.py
│   ├── kael.py
│   ├── lore.py
│   ├── matthijs.py
│   ├── moderation.py
│   ├── pack.py
│   ├── packhealth.py
│   ├── sysadmin.py
│   ├── utility.py
│   └── wolf_lore.py
└── services/
    ├── ai_media.py
    ├── ai_service.py
    ├── ai_state.py
    ├── birthday_service.py
    ├── db.py
    ├── feature_intelligence.py
    ├── guild_policy_service.py
    ├── reminder_service.py
    ├── runtime_intelligence.py
    ├── startup_update_service.py
    ├── trust_service.py
    └── warning_service.py
```

## Access Model

NightPaw currently uses four practical access tiers:

- `General`
  - normal public usage
- `Pack`
  - trusted users from the persistent trust list
- `ServerAdmin`
  - server-side authority based on Discord permissions
- `Alpha`
  - owner-only access

This affects help output, AI action routing, and command visibility.

## Core Features

### AI

Main AI behavior lives in:

- [cogs/ai.py](./cogs/ai.py)
- [services/ai_service.py](./services/ai_service.py)
- [services/runtime_intelligence.py](./services/runtime_intelligence.py)
- [services/ai_state.py](./services/ai_state.py)

Current AI capabilities include:

- local Ollama chat model support
- optional local vision model support
- attachment-aware text and image handling
- deterministic-first command/action routing
- persistent scoped chat history
- explicit remembered facts
- per-turn diagnostics via `aidiag`
- runtime identity/context injection without exposing private internals

Important behavior:

- NightPaw is the bot identity
- Ollama is the runtime
- the underlying model is not treated as the bot’s identity
- sensitive internal details like localhost endpoints and hidden prompts are not meant to be exposed in normal chat

### Diagnostics and Observability

- `aidiag`
  - shows latest AI route, planner, fallback, memory usage, runtime sections, model path, and attachment handling
- `packhealth`
  - system-style health dashboard with uptime, latency, DB counts, automod state, AI route snapshot, and model info
- `debugreport`
  - owner-focused operational report
- log file + webhook logging
  - rotating local log file
  - optional Discord webhook log sink

### Help System

The help system is interactive and access-aware.

Current help sections include:

- Overview
- Ranks
- AI
- Utility
- Lore
- Pack
- ServerAdmin
- Moderation
- System
- Help

It is generated from live loaded commands rather than a static command list.

### Moderation and AutoMod

Moderation commands in [cogs/moderation.py](./cogs/moderation.py):

- `kick`
- `ban`
- `unban`
- `timeout`
- `untimeout`
- `warn`
- `warnings`
- `clearwarnings`
- `purge`
- `addrole`
- `removerole`
- `userinfo`

AutoMod in [cogs/automod.py](./cogs/automod.py):

- invite link blocking
- mass mention detection
- blocked word detection
- spam tracking
- excessive caps detection
- repeated character detection
- persistent strike storage
- owner/trusted exemption path

### Trust / Pack Features

Pack and trusted-user behavior is backed by SQLite.

Commands:

- `addtrust`
- `remtrust`
- `trustlist`
- `cleartrust`
- `backuptrust`

Trusted users affect:

- help visibility
- pack access
- AI behavior in some access checks
- AutoMod exemptions

### Utility / Daily Use

In [cogs/utility.py](./cogs/utility.py):

- `status`
- `remind`
- `remindlist`
- `remindclear`
- `weather`
- `moonphase`
- `moonrise`
- `moonset`
- `echo`
- `say`
- `restart`
- `stop`

Reminders persist across restarts and are restored on boot.

### Owner / System Control

In [cogs/sysadmin.py](./cogs/sysadmin.py):

- `sysinfo`
- `ls`
- `readfile`
- `botping`
- `debugreport`
- `serverlist`
- `serverleave`
- `serverban`
- `serverallow`
- `serverleaveall`
- `serverblocked`
- `serverinvite`

Guild policy behavior:

- the bot can keep a persistent blocked guild list
- blocked guilds are left automatically if the bot is re-added

`serverinvite` currently supports:

- `minimal`
- `required`
- `full`
- `custom`

And slash custom mode uses an interactive permission UI.

### Cog Management

In [cogs/cogmanager.py](./cogs/cogmanager.py):

- `cogload`
- `cogunload`
- `cogreload`
- `cogreloadall`
- `cogloadnew`
- `cogstatus`

NightPaw supports live cog loading and reloading without a full process restart.

### Lore / Character Cogs

Lore and profile cogs:

- [cogs/lore.py](./cogs/lore.py)
- [cogs/wolf_lore.py](./cogs/wolf_lore.py)
- [cogs/kael.py](./cogs/kael.py)
- [cogs/blaze.py](./cogs/blaze.py)
- [cogs/matthijs.py](./cogs/matthijs.py)

These cover:

- Wolfy profile/lore
- pack bios
- resonance and moon lore
- random wolf-themed flavor commands
- character/profile embeds

## Startup and Runtime Behavior

Current startup flow includes:

- cog loading with logging
- background AI schema prep
- slash command sync on ready
- rotating status loop
- startup DM notification to owner
- file change snapshot reporting with impact hints

The startup update report uses deterministic file-path mapping, not AI generation.

## Discord Application Setup

In the Discord Developer Portal:

1. Create or open the application
2. Under `Bot`, enable the required privileged intents:
   - Server Members Intent
   - Message Content Intent
   - Presence Intent
3. Under OAuth2, use scopes:
   - `bot`
   - `applications.commands`

NightPaw’s own `serverinvite` command can also generate invite URLs with preset or custom permissions.

## Notes

- This bot is not an OpenAI API bot.
- AI is built for local Ollama models.
- `data/nightpaw.db` is part of the bot’s real state and should not be deleted casually.
- `nightpaw.log` is safe to rotate or remove while the bot is stopped.
- Prefix and slash coverage overlaps in many places, but not every internal/admin command has both forms.
- Some owner prefix commands are intentionally described as DM-focused in their help text, while slash owner tools are usable more broadly with owner checks.

## GitHub Safety

Use GitHub for source code and version history, not for live runtime state.

- Safe to commit:
  - source files
  - `README.md`
  - `pyproject.toml`
  - `uv.lock`
  - `.env.example`
- Do not commit:
  - `.env`
  - local virtual environments
  - logs
  - database files
  - startup snapshot/runtime state
  - archive/backup files

Important details:

- Real runtime state lives in `data/nightpaw.db`
- `.env.example` is safe to commit
- `.env` is not safe to commit
- If a real Discord token, webhook URL, or other private data was ever committed, rotate it first and clean git history before making any repository public

Recommended use:

- keep NightPaw as a private GitHub repository
- use GitHub as source storage and change history
- keep local runtime data on the machine that runs the bot

## Creating Releases

NightPaw now uses a unified local developer helper:

- [scripts/nightpaw-dev.ps1](./scripts/nightpaw-dev.ps1)
- [docs/dev-helper.md](./docs/dev-helper.md)

Release usage:

```powershell
.\scripts\nightpaw-dev.ps1 release -DryRun
.\scripts\nightpaw-dev.ps1 release
.\scripts\nightpaw-dev.ps1 release -Push
.\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease
.\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease -UseTagNotes
```

What it does:

- checks the latest reachable semver tag
- detects the current branch safely with `git rev-parse --abbrev-ref HEAD`
- analyzes committed release-range changes with `git diff --name-status <previousTag>..HEAD` and `git log <previousTag>..HEAD`
- analyzes local working-tree changes with combined git status, staged diff, unstaged diff, and untracked-file sources
- recommends whether a release is needed
- recommends a major, minor, or patch bump
- previews grouped GitHub release notes including commits and changed files
- previews the `CHANGELOG.md` section that would be written
- can write `CHANGELOG.md` first and then stop so it can be committed before or with the release
- creates a local annotated tag only after confirmation or `-Yes`
- asks whether to push the current branch and tags to `origin` after a successful tag
- can optionally create the GitHub release with `gh` after a successful push
- generates GitHub release notes from commits since the previous tag by default, with explicit grouped sections plus a full commit list
- never pushes or creates a GitHub release silently
- does not auto-push from detached `HEAD`
- treats docs-only changes as a possible no-release case

Version bump rules:

- `BREAKING CHANGE`, `breaking:`, or conventional commit `!` markers -> major
- `feat:` or a feature-shaped working tree -> minor
- `fix:`, `perf:`, `refactor:`, `build:`, `test:`, `docs:`, `chore:`, `ci:` -> patch
- docs-only changes recommend no release unless you force one with `-Type`

Examples:

```powershell
.\scripts\nightpaw-dev.ps1 release -DryRun
.\scripts\nightpaw-dev.ps1 release
.\scripts\nightpaw-dev.ps1 release -Push
.\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease
.\scripts\nightpaw-dev.ps1 release -Push -CreateGitHubRelease -UseTagNotes
.\scripts\release.ps1 -DryRun
```

Important detail:

- releases are still manual source snapshots and milestones
- `-Yes` skips only local changelog/tag confirmations
- pushes and GitHub release creation remain explicit through prompts or `-Push` / `-CreateGitHubRelease`
- release notes include grouped changes, a `Commits` section, and a `Changed Files` section from the real release range
- `CHANGELOG.md` is maintained by the release helper and must be committed before or with the release when it is newly written
- release notes are generated from commit history by default, with `-UseTagNotes` available as the fallback path
- if you skip the push, the helper prints `git push origin <current-branch> --tags` as the next manual step

## Dev Helper

Usage:

```powershell
.\scripts\nightpaw-dev.ps1
.\scripts\dev.ps1
```

This opens the unified NightPaw developer console for common local tasks:

- show project status
- show commit context
- commit changes
- dry-run a release
- create a release tag
- run tests
- run a bot syntax/import check
- run a Rust helper check

Developer-helper behavior:

- local, rule-based only
- no helper-side AI or Ollama support
- accurate status/context output for modified, staged, untracked, deleted, and renamed files
- release previews include commits, changed files, changed areas, and changelog content

Compatibility wrappers still exist:

- [scripts/dev.ps1](./scripts/dev.ps1)
- [scripts/commit.ps1](./scripts/commit.ps1)
- [scripts/commit_context.ps1](./scripts/commit_context.ps1)
- [scripts/release.ps1](./scripts/release.ps1)

Windows note:

- git LF or CRLF warnings are usually harmless unless you also see unexpected line-ending churn in the diff

## Recommended First Checks After Setup

1. Run `uv sync`
2. Start the bot with `uv run main.py`
3. Verify the bot logs in successfully
4. Open `/help`
5. Run `/status`
6. If AI is enabled locally, run `/aistatus`
7. After the first AI interaction, run `/aidiag`

## Current README Scope

This README is meant to describe the bot as it exists now, not to document every historical version. If behavior changes, the best sources of truth are:

- [main.py](./main.py)
- [cogs](./cogs/)
- [services](./services/)
