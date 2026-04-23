# NightPaw

NightPaw is a local-first Discord bot built around `discord.py`, SQLite, and Ollama. It mixes practical server tools, moderation, diagnostics, wolf-themed lore, and an AI layer that stays inspectable instead of hiding what it is doing.

This project is built for a private or controlled rollout first. It has owner tooling, server control tooling, persistent local state, and an AI system that is tuned for local use rather than hosted API usage.

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

Declared in [pyproject.toml](/C:/Users/loene/OneDrive/discord/NightPaw/pyproject.toml):

- `discord-py[voice]`
- `python-dotenv`
- `aiosqlite`
- `aiohttp`
- `psutil`
- `ephem`

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

## Windows Startup

You can use [start_nightpaw.bat](/C:/Users/loene/OneDrive/discord/NightPaw/start_nightpaw.bat) with Task Scheduler.

Example batch file:

```bat
@echo off
cd /d "C:\Users\loene\OneDrive\discord\NightPaw"
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

- [cogs/ai.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/ai.py)
- [services/ai_service.py](/C:/Users/loene/OneDrive/discord/NightPaw/services/ai_service.py)
- [services/runtime_intelligence.py](/C:/Users/loene/OneDrive/discord/NightPaw/services/runtime_intelligence.py)
- [services/ai_state.py](/C:/Users/loene/OneDrive/discord/NightPaw/services/ai_state.py)

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

Moderation commands in [cogs/moderation.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/moderation.py):

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

AutoMod in [cogs/automod.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/automod.py):

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

In [cogs/utility.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/utility.py):

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

In [cogs/sysadmin.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/sysadmin.py):

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

In [cogs/cogmanager.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/cogmanager.py):

- `cogload`
- `cogunload`
- `cogreload`
- `cogreloadall`
- `cogloadnew`
- `cogstatus`

NightPaw supports live cog loading and reloading without a full process restart.

### Lore / Character Cogs

Lore and profile cogs:

- [cogs/lore.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/lore.py)
- [cogs/wolf_lore.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/wolf_lore.py)
- [cogs/kael.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/kael.py)
- [cogs/blaze.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/blaze.py)
- [cogs/matthijs.py](/C:/Users/loene/OneDrive/discord/NightPaw/cogs/matthijs.py)

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

NightPaw includes a local release helper script for safe source snapshots:

- [scripts/release.ps1](/C:/Users/loene/OneDrive/discord/NightPaw/scripts/release.ps1)

What it does:

- defaults to an automatic release check when run with no arguments
- refuses to run if the git working tree is dirty
- checks commits, changed files, and changed lines since the latest tag
- uses commit messages to choose an automatic version bump
- creates an annotated git tag only after confirmation or `-Yes`
- pushes that tag to `origin`
- creates a GitHub release when `gh` is available
- supports explicit scheduled/background mode through `-Scheduled`
- keeps git tags simple and uses a version + date title for GitHub releases

Examples:

```powershell
.\scripts\release.ps1
.\scripts\release.ps1 -DryRun
.\scripts\release.ps1 -Yes
.\scripts\release.ps1 -Bump minor
.\scripts\release.ps1 -Version v2.0.0
.\scripts\release.ps1 -Scheduled
```

Release modes:

- Default run
  - checks whether a release is recommended
  - proposes a version automatically
  - asks for confirmation before creating anything
- `-DryRun`
  - prints the report only
  - never creates a tag or release
- `-Yes`
  - skips the confirmation prompt
- `-Bump major|minor|patch`
  - overrides the automatic bump choice
- `-Version vX.Y.Z`
  - overrides the automatic version entirely
- `-ReleaseDate "dd/MM/yyyy"`
  - overrides the GitHub release title date manually
- `-Scheduled`
  - explicit non-interactive mode for Task Scheduler or hidden/background runs
  - never prompts
  - only creates a release when the script recommends one
  - exits cleanly when no release is recommended or when the working tree is dirty

Important detail:

- the date is only used in the GitHub release title
- the git tag remains plain, for example `v1.0.0`
- the script only checks when you run it manually
- it does not monitor the repo automatically
- scheduled mode is explicit because the script cannot reliably know whether Task Scheduler launched it hidden
- commit messages influence automatic bumping:
  - `BREAKING CHANGE`, `breaking:`, or `!:` -> major
  - `feat:` -> minor
  - `fix:`, `docs:`, `refactor:`, `chore:`, `style:`, `test:` -> patch

Logging and scheduled use:

- the helper writes to `logs/release-helper.log`
- scheduled mode still prints normal output if visible, but also logs its decisions
- if run hidden or with `-NonInteractive`, use `-Scheduled` so it never waits for input

Recommended Task Scheduler PowerShell arguments:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File "C:\Users\loene\OneDrive\discord\NightPaw\scripts\release.ps1" -Scheduled
```

Task Scheduler note:

- your current NightPaw bot task uses a boot trigger with a 30 second delay and launches [start_nightpaw.bat](/C:/Users/loene/OneDrive/discord/NightPaw/start_nightpaw.bat)
- for scheduled release checks, use a separate task that calls `pwsh` directly with `-Scheduled`

These releases are source snapshots and milestones. They are not backups of `.env`, `data/`, logs, archives, or other ignored runtime files.

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

- [main.py](/C:/Users/loene/OneDrive/discord/NightPaw/main.py)
- [cogs](/C:/Users/loene/OneDrive/discord/NightPaw/cogs)
- [services](/C:/Users/loene/OneDrive/discord/NightPaw/services)
