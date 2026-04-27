# NightPaw Privacy Policy

Last updated: 2026-04-27

This document is a developer-prepared template for NightPaw based on the current repository code. It is not legal advice and does not guarantee Discord app verification.

## 1. Overview

NightPaw is a local-first Discord bot. Based on the current code, it primarily stores persistent data in a local SQLite database at `data/nightpaw.db`, writes local log files, and uses local Ollama AI processing by default unless the operator changes the configuration.

## 2. What NightPaw Processes

Depending on which features are used, NightPaw may process:

- Discord user IDs
- guild/server IDs
- channel IDs
- usernames and display names
- message content sent to commands or AI features
- AI conversation content and AI replies
- explicit AI memory content such as facts a user asks the bot to remember
- reminder text and reminder schedule times
- moderation reasons and moderation actions
- trusted-user settings
- blocked-guild settings
- attachments that users intentionally send for AI/file/image analysis, including images and readable text/code files
- log and diagnostics data related to bot actions, command use, errors, and moderation events

NightPaw requests Discord intents that include message content, members, DM messages, and presences.

## 3. What NightPaw Stores

Based on the current code, NightPaw stores the following categories of data locally when the related feature is used.

### AI settings and history

NightPaw stores AI configuration and AI-related records in SQLite tables including:

- `ai_guild_settings`
  - stores guild/server AI settings such as guild ID, configured AI channel ID, enable/disable flags, and server-specific AI prompt text
- `ai_history`
  - stores scoped AI chat history including scope type, scope ID, user ID, author name, role, message content, and timestamp
- `ai_channel_messages`
  - stores recent channel message summaries for AI context including guild ID, channel ID, user ID, author name, content, and timestamp
- `ai_memories`
  - stores explicit remembered facts for a user within a DM or guild scope
- `ai_user_notes`
  - stores operator/admin notes about a user when those commands are used

The current code trims stored AI history and channel-context rows to recent rolling limits, but those records still persist until replaced, cleared, or deleted.

### Reminders

If reminder features are used, NightPaw stores:

- user ID
- channel ID when applicable
- reminder message
- scheduled fire time

### Warnings and moderation records

If warning features are used, NightPaw stores:

- target user ID
- warning reason
- moderator ID
- moderator name
- timestamp

AutoMod also stores a local strike count per user ID in `automod_strikes`.

### Trusted-user settings

If trust features are used, NightPaw stores:

- trusted user ID
- username string
- who added that user

The project also includes an owner-only export command that can write a JSON backup of trusted-user records to `data/trust_backup.json`.

### Blocked guilds

If server blocking features are used, NightPaw stores:

- guild/server ID
- guild name
- block reason
- actor user ID
- creation timestamp

### Birthdays

The repository contains a `birthdays` SQLite table and a birthday storage service for user ID plus day/month values. However, during this audit I did not identify an active public birthday command that currently writes normal user birthdays. If your deployment enables or adds that feature, birthday-related data may be stored in SQLite.

### Logs

NightPaw writes local logs, and the current code can also send logs to a configured Discord webhook.

Logs may include:

- usernames and user IDs involved in commands or errors
- guild names and channel IDs
- command names
- portions of command message content
- stack traces and diagnostics
- moderation log embeds
- AutoMod log embeds

If `BOT_LOG_WEBHOOK` is configured, log payloads may also be forwarded to that webhook destination.

## 4. Why NightPaw Uses This Data

NightPaw uses data to:

- respond to commands and slash commands
- provide AI chat and AI-assisted replies
- maintain short-term and explicit persistent AI context
- read attachments users intentionally submit for analysis
- schedule and deliver reminders
- support moderation, warnings, and AutoMod behavior
- manage trusted-user and blocked-guild access settings
- troubleshoot failures and monitor bot health

## 5. AI and Attachment Processing

NightPaw includes AI chat features that may process message content you send to the AI.

The current code shows that:

- AI chat may process prompt text and related conversation history
- explicit memories may be stored when a user asks the bot to remember something
- recent AI chat history may be stored and re-used for later replies in the same DM or server scope
- recent channel messages may be stored for channel-context replies
- attached images may be base64-encoded in memory and sent to the configured Ollama model for the current request
- attached text/code files may be read and included in the AI prompt context for the current request

By default, NightPaw is configured for local Ollama processing at `http://127.0.0.1:11434` unless the operator changes the configuration.

## 6. Storage Location

Based on the current code, NightPaw primarily stores persistent structured data in:

- `data/nightpaw.db`

It also stores local runtime/support files such as:

- rotating local log files, including `nightpaw.log` by default
- `data/command_sync_state.json`
- `data/startup_snapshot.json`
- optional trusted-user export JSON files when that owner-only export command is used

## 7. Deletion and Clearing Options

The current code includes the following user/admin deletion or clearing paths:

- `aiclearhistory`
  - clears AI chat history and explicit remembered facts for the current DM or server scope
- `aiclearnote`
  - removes a stored persistent AI note for a user
- `remindclear`
  - clears one reminder by ID or all reminders for the requesting user
- `clearwarnings`
  - clears all stored warnings for a member
- `remtrust`
  - removes a user from the trusted list
- `cleartrust`
  - clears the trusted-user list
- `serverallow`
  - removes a guild from the blocked-guild list

For birthday data, the repository includes a `delete_birthday` service function, but I did not identify an active public user-facing birthday deletion command in the current command set.

Because some deletion features are admin-only or owner-only, users may need to contact the bot operator or relevant server admin to request deletion help.

## 8. Data Sharing

Based on the current repository code, NightPaw does not appear to be designed as a cloud SaaS that automatically sends all bot data to a hosted third-party backend. However:

- Discord itself necessarily processes Discord messages, IDs, and metadata as part of using the platform
- Ollama requests are sent to the configured AI endpoint
- if the operator changes the AI endpoint away from local Ollama, AI data may be sent wherever that endpoint is configured
- if `BOT_LOG_WEBHOOK` is configured, some log data may be sent to that webhook destination

## 9. Security

NightPaw is local-first, but no Discord bot system can guarantee perfect security. Local databases, logs, operator machines, Discord itself, configured webhooks, and any changed AI endpoints all carry risk.

You should not assume that any message, attachment, memory, or stored record is perfectly secure.

## 10. Children's Privacy

This template does not make any special claim that NightPaw is directed to children. Server operators are responsible for deciding where and how to deploy it.

## 11. Changes to This Policy

This policy may be updated as NightPaw changes. Because the codebase is still evolving, operators should review this document again before public rollout or Discord verification submission.

## 12. Contact

Questions, privacy requests, or deletion requests can be sent to:

- Discord: `wolfy213`
- E-mail: `wolfydabest.dev@gmail.com`
