from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import discord

import config
from services.ai_media import AttachmentBatch, describe_attachment_capability
from services.ai_state import get_history, get_memories, get_recent_channel_messages, get_user_note
from services.feature_intelligence import build_feature_snapshot
from services.trust_service import is_trusted_user, list_trusted
from services.db import connect


@dataclass(slots=True)
class RuntimeFacts:
    identity_text: str
    user_text: str
    guild_text: str
    creator_text: str
    personality_text: str
    memory_text: str
    health_text: str
    automod_text: str
    pack_text: str
    conversation_text: str
    feature_text: str


OWNER_DEV_FALLBACK = "the configured owner"


BLOCKED_WORD_SUMMARY = (
    "invite link blocking, mass-mention handling, blocked slur filtering, spam cleanup, excessive-caps cleanup, "
    "and repeated-character cleanup"
)


QUESTIONS_OWNER_DEV = (
    "who made you",
    "who created you",
    "who is the owner",
    "who is your owner",
    "who is the developer",
    "who developed you",
    "owner and developer",
)


QUESTIONS_MEMORY_RECALL = (
    "what do you know about me",
    "who am i to you",
    "what do you know of me",
)


QUESTIONS_USER_IDENTITY = (
    "who am i",
    "who am i?",
    "what is my name",
    "what's my name",
    "what is my username",
    "what's my username",
    "what is my display name",
    "what's my display name",
    "who do you think i am",
)


QUESTIONS_ATTACHMENTS = (
    "read attachments",
    "read attachment",
    "read images",
    "read image",
    "able to read attachments",
    "able to read images",
    "can you read attachments",
    "can you read images",
    "can you see attachments",
    "can you see images",
    "read files",
)

QUESTIONS_COMMAND_ABILITY = (
    "are you able to run commands",
    "can you run commands",
    "can you execute commands",
    "do you run commands",
    "are you able to execute commands",
)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _base_model_identity(model_name: str) -> str:
    lowered = (model_name or "").casefold()
    if "llama" in lowered:
        return "LLaMA family by Meta"
    return model_name or "unknown base model"


async def _resolve_owner_label(bot: discord.Client) -> str:
    owner_id = config.OWNER_ID
    if not owner_id:
        return OWNER_DEV_FALLBACK
    owner_obj = bot.get_user(owner_id)
    if owner_obj is None:
        try:
            owner_obj = await bot.fetch_user(owner_id)
        except Exception:
            owner_obj = None
    if owner_obj is None:
        return f"the configured owner ({owner_id})"
    return f"{owner_obj.display_name if hasattr(owner_obj, 'display_name') else owner_obj.name} ({owner_obj.id})"


async def _trusted_names() -> list[str]:
    trusted = await list_trusted()
    names = [member.username for member in trusted]
    return names[:12]


async def _health_stats(bot: discord.Client) -> dict[str, Any]:
    counts = {
        "warnings": 0,
        "reminders": 0,
        "trusted": 0,
        "automod_strikes": 0,
    }
    async with connect() as db:
        queries = {
            "warnings": "SELECT COUNT(*) FROM warnings",
            "reminders": "SELECT COUNT(*) FROM reminders",
            "trusted": "SELECT COUNT(*) FROM trusted",
            "automod_strikes": "SELECT COALESCE(SUM(strikes), 0) FROM automod_strikes",
        }
        for key, query in queries.items():
            try:
                async with db.execute(query) as cursor:
                    row = await cursor.fetchone()
                    counts[key] = row[0] if row else 0
            except Exception:
                counts[key] = 0
    counts["guilds"] = len(bot.guilds)
    counts["cogs"] = len(bot.cogs)
    counts["latency_ms"] = round(bot.latency * 1000)
    automod_cog = bot.cogs.get("AutoMod")
    counts["automod_enabled"] = bool(automod_cog and getattr(automod_cog, "enabled", False))
    return counts


async def _recent_topic_summary(scope_type: str, scope_id: int) -> str:
    history = await get_history(scope_type, scope_id, limit=12)
    user_texts = [row["content"] for row in history if row["role"] == "user"]
    if not user_texts:
        return "We don't have much saved conversation context yet."

    joined = " \n".join(user_texts).casefold()
    topics: list[str] = []
    if any(word in joined for word in ("ai", "prompt", "personality", "self-knowledge", "self knowledge")):
        topics.append("my AI behaviour, personality, and self-knowledge")
    if any(word in joined for word in ("avatar", "banner", "id")):
        topics.append("avatar/banner lookups and identity lookups")
    if any(word in joined for word in ("automod", "moderation", "warn", "purge", "kick", "ban")):
        topics.append("moderation and AutoMod behaviour")
    if any(word in joined for word in ("pack", "trust", "trusted")):
        topics.append("pack/trusted-member access and pack status")
    if any(word in joined for word in ("server", "guild", "servers")):
        topics.append("server awareness and guild visibility")
    if any(word in joined for word in ("ollama", "model")):
        topics.append("my local model backend and origin")
    if not topics:
        preview = "; ".join(text[:70] for text in user_texts[-3:])
        return f"Recently we've been talking about: {preview}"
    deduped: list[str] = []
    for topic in topics:
        if topic not in deduped:
            deduped.append(topic)
    if len(deduped) == 1:
        return f"Recently we've mainly been talking about {deduped[0]}."
    return "Recently we've been talking about " + ", ".join(deduped[:-1]) + f", and {deduped[-1]}."


async def _channel_context_summary(guild: discord.Guild | None, channel: discord.abc.Messageable | None) -> str:
    if guild is None or not isinstance(channel, discord.abc.GuildChannel):
        return "No guild channel context."
    rows = await get_recent_channel_messages(guild.id, channel.id, limit=10)
    if not rows:
        return "No recent multi-user channel context stored yet."
    rendered = []
    for row in rows[-6:]:
        rendered.append(f"{row['author_name']}: {row['content'][:180]}")
    return "Recent channel context:\n" + "\n".join(rendered)


async def build_runtime_facts(
    bot: discord.Client,
    *,
    user: discord.abc.User,
    guild: discord.Guild | None,
    channel: discord.abc.Messageable | None,
    custom_prompt: str,
    scope_type: str,
    scope_id: int,
) -> RuntimeFacts:
    snapshot = build_feature_snapshot(bot)
    owner_label = await _resolve_owner_label(bot)
    trusted = await is_trusted_user(user.id, config.OWNER_ID)
    note = await get_user_note(user.id)
    memories = await get_memories(scope_type, scope_id, user.id, limit=8)
    health = await _health_stats(bot)
    trusted_names = await _trusted_names()
    conversation_summary = await _recent_topic_summary(scope_type, scope_id)
    channel_summary = await _channel_context_summary(guild, channel)

    bot_name = getattr(bot.user, "name", config.BOT_NAME)
    personality = custom_prompt.strip() or "No server-specific override is configured right now."
    text_model = getattr(config, "AI_MODEL", "unknown")
    origin = (
        f"Local Ollama-backed chat via text model `{text_model}`. "
        f"Configured vision model: `{getattr(config, 'AI_VISION_MODEL', 'none') or 'none'}`. "
        "Local endpoint details are private operational config."
    )
    identity_text = (
        "Identity boundaries:\n"
        f"- primary identity/application: {bot_name} (the Discord bot)\n"
        f"- creator/developer here: {owner_label}\n"
        f"- runtime environment: Ollama\n"
        f"- underlying base model family: {_base_model_identity(text_model)}\n"
        "- keep these roles separate; do not collapse them into one identity\n"
        "- tone may change, identity does not\n"
        f"- implementation summary: {origin}"
    )
    creator_text = (
        "Creator facts:\n"
        f"- configured owner/developer user: {owner_label}\n"
        f"- bot identity name: {bot_name}"
    )
    personality_text = (
        "Personality facts:\n"
        f"- server-specific override present: {'yes' if custom_prompt.strip() else 'no'}\n"
        "- adapt tone and style when asked, but keep the same NightPaw identity"
    )
    memory_lines = [
        "Memory facts:",
        "- explicit remembered facts for the current user can be stored persistently for this DM/server scope",
        "- stored scope memories are re-injected on each reply",
        "- scope memories survive restarts until they are cleared",
        "- `aiclearhistory` clears chat history and these stored scope memories",
        "- this is scoped persistent memory, not unlimited global autobiographical memory",
    ]
    if memories:
        memory_lines.append("- currently stored scope memories:")
        memory_lines.extend(f"  - {item}" for item in memories)
    else:
        memory_lines.append("- currently stored scope memories: none")
    memory_text = "\n".join(memory_lines)

    role_bits = []
    if user.id == config.OWNER_ID:
        role_bits.append("configured owner")
        role_bits.append("primary developer/operator")
    elif trusted:
        role_bits.append("trusted pack member")
    else:
        role_bits.append("regular user unless guild permissions say otherwise")
    user_text = (
        f"Current user: {getattr(user, 'display_name', user.name)} ({user.id}). "
        f"Relationship to bot: {', '.join(role_bits)}."
    )
    if note:
        user_text += " There is an operator note on file for this user; only use it when the prompt is directly about the user."

    if guild is None:
        guild_text = "Current location: direct messages. No guild-specific channel/member counts here."
    else:
        ai_channel_name = None
        try:
            ai_cog = bot.cogs.get("AI")
            if ai_cog and hasattr(ai_cog, "service"):
                pass
        except Exception:
            pass
        text_channels = len(getattr(guild, "text_channels", []))
        voice_channels = len(getattr(guild, "voice_channels", []))
        guild_text = (
            f"Current guild: {guild.name} ({guild.id}), approximately {guild.member_count or 'unknown'} members, "
            f"{text_channels} text channels, {voice_channels} voice channels."
        )

    health_text = (
        f"Live health: {health['cogs']} loaded cogs, {health['guilds']} guilds, latency {health['latency_ms']}ms, "
        f"AutoMod {'enabled' if health['automod_enabled'] else 'disabled'}, {health['warnings']} warnings stored, "
        f"{health['reminders']} reminders pending, {health['trusted']} trusted members, {health['automod_strikes']} total automod strikes."
    )
    automod_text = (
        "AutoMod capabilities: blocks Discord invite links, blocks @everyone/@here abuse and heavy mass mentions, "
        "filters blocked slurs/abusive words with strike escalation, cleans obvious spam bursts, trims excessive caps, "
        "and deletes unreadable repeated-character spam. Trusted users are exempt."
    )
    pack_text = (
        "Trusted pack summary: " + (", ".join(trusted_names) if trusted_names else "no trusted members are currently stored.")
    )
    feature_text = (
        f"Live feature snapshot: {snapshot['cog_count']} cogs, {snapshot['command_count']} commands. "
        "Use command names from the feature snapshot instead of inventing capabilities."
    )
    conversation_text = conversation_summary + "\n" + channel_summary
    return RuntimeFacts(
        identity_text=identity_text,
        user_text=user_text,
        guild_text=guild_text,
        creator_text=creator_text,
        personality_text=personality_text,
        memory_text=memory_text,
        health_text=health_text,
        automod_text=automod_text,
        pack_text=pack_text,
        conversation_text=conversation_text,
        feature_text=feature_text,
    )


async def _build_owner_fact(bot: discord.Client, user: discord.abc.User) -> str:
    owner_label = await _resolve_owner_label(bot)
    if user.id == config.OWNER_ID:
        return f"Configured owner/developer: {owner_label}"
    return f"Created by: {owner_label}"


async def _build_memory_recall(
    *,
    user: discord.abc.User,
    scope_type: str,
    scope_id: int,
) -> str:
    trusted = await is_trusted_user(user.id, config.OWNER_ID)
    note = await get_user_note(user.id)
    memories = await get_memories(scope_type, scope_id, user.id, limit=8)
    facts: list[str] = [f"Current user: {getattr(user, 'display_name', user.name)} ({user.id})"]
    if user.id == config.OWNER_ID:
        facts.append("Relationship: owner/developer")
    elif trusted:
        facts.append("Relationship: trusted pack member")
    else:
        facts.append("Relationship: regular user")
    if memories:
        facts.append("Stored memories: " + "; ".join(memories[:4]))
    else:
        facts.append("Stored memories: none")
    if note:
        facts.append(f"Operator note: {note}")
    return "\n".join(facts)


async def _build_attachment_capability_fact(attachments: AttachmentBatch | None = None) -> str:
    capability = describe_attachment_capability()
    if attachments and attachments.attachments:
        names = ", ".join(att.filename for att in attachments.attachments[:4])
        readable = []
        if attachments.has_text:
            readable.append('readable text attachment content')
        if attachments.has_images:
            readable.append('image input for the vision path')
        detail = ''
        if readable:
            detail = ' On this turn I already received ' + ' and '.join(readable) + '.'
        return f"{capability} For this message I can currently see these attachments: {names}.{detail}"
    return capability


async def _build_command_ability_fact() -> str:
    return (
        "Command execution is limited to the allowlisted action bridge with normal permission checks. "
        "Most actions still require the real command path."
    )

def _contains_any(normalized_prompt: str, needles: tuple[str, ...]) -> bool:
    return any(needle in normalized_prompt for needle in needles)


async def direct_answer(
    bot: discord.Client,
    *,
    prompt: str,
    user: discord.abc.User,
    guild: discord.Guild | None,
    channel: discord.abc.Messageable | None,
    custom_prompt: str,
    scope_type: str,
    scope_id: int,
    attachments: AttachmentBatch | None = None,
) -> dict[str, str] | None:
    text = _normalize(prompt)

    if _contains_any(text, QUESTIONS_OWNER_DEV):
        return {
            "route": "system_query",
            "reason": "explicit owner/developer query",
            "text": await _build_owner_fact(bot, user),
        }
    if _contains_any(text, QUESTIONS_MEMORY_RECALL) or _contains_any(text, QUESTIONS_USER_IDENTITY):
        return {
            "route": "memory_recall",
            "reason": "explicit memory or user-identity recall query",
            "text": await _build_memory_recall(user=user, scope_type=scope_type, scope_id=scope_id),
        }
    if _contains_any(text, QUESTIONS_ATTACHMENTS):
        return {
            "route": "system_query",
            "reason": "explicit attachment capability query",
            "text": await _build_attachment_capability_fact(attachments),
        }
    if _contains_any(text, QUESTIONS_COMMAND_ABILITY):
        return {
            "route": "system_query",
            "reason": "explicit command capability query",
            "text": await _build_command_ability_fact(),
        }
    return None


def _prompt_wants(normalized_prompt: str, *keywords: str) -> bool:
    return any(keyword in normalized_prompt for keyword in keywords)


async def render_runtime_block(facts: RuntimeFacts, prompt: str = "") -> tuple[str, list[str]]:
    normalized = _normalize(prompt) if prompt else ""

    parts = []
    included = ["identity", "user", "guild", "memory"]
    parts.extend([facts.identity_text, facts.user_text, facts.guild_text, facts.memory_text])

    include_creator = not normalized or _prompt_wants(
        normalized,
        "owner", "developer", "who made you", "who created you", "who is your owner", "who is the developer",
    )
    include_personality = not normalized or _prompt_wants(
        normalized,
        "personality", "configured personality", "custom prompt", "server prompt", "behaviour override",
    )
    include_conversation = not normalized or _prompt_wants(
        normalized,
        "remember", "history", "talked about", "discuss", "aware", "currently", "right now",
    )
    include_features = not normalized or _prompt_wants(
        normalized,
        "command", "commands", "features", "function", "functionalities", "what can you do", "capabilities",
    )

    include_health = not normalized or _prompt_wants(
        normalized,
        "status", "stats", "health", "latency", "uptime", "warning", "warnings", "reminder", "reminders",
        "guilds", "servers", "cogs", "loaded", "online", "offline", "packhealth",
    )
    include_automod = not normalized or _prompt_wants(
        normalized,
        "automod", "moderation", "moderate", "warn", "warnings", "purge", "kick", "ban", "timeout", "slur", "spam",
    )
    include_pack = not normalized or _prompt_wants(
        normalized,
        "pack", "trusted", "trust", "owner", "developer", "who made you", "who created you",
    )

    if include_health:
        included.append("health")
        parts.append(facts.health_text)
    if include_automod:
        included.append("automod")
        parts.append(facts.automod_text)
    if include_pack:
        included.append("pack")
        parts.append(facts.pack_text)
    if include_creator:
        included.append("creator")
        parts.append(facts.creator_text)
    if include_personality:
        included.append("personality")
        parts.append(facts.personality_text)
    if include_conversation:
        included.append("conversation")
        parts.append(facts.conversation_text)
    if include_features:
        included.append("features")
        parts.append(facts.feature_text)

    deduped_included: list[str] = []
    for item in included:
        if item not in deduped_included:
            deduped_included.append(item)
    return "\n\n".join(part for part in parts if part), deduped_included
