from __future__ import annotations

import asyncio
import copy
import contextlib
from datetime import timedelta
import re
import time
import logging

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.view import StringView

import config
from config import wolf_wrap
from checks import allow_everywhere_slash, user_is_trusted
from services.ai_media import collect_message_attachments, process_discord_attachments
from services.ai_service import AIService
from services.ai_state import (
    clear_history,
    clear_user_note,
    ensure_schema,
    get_guild_settings,
    get_user_note,
    record_channel_message,
    set_user_note,
    upsert_guild_settings,
)
from services.feature_intelligence import build_feature_snapshot, infer_command_category, render_feature_embed


logger = logging.getLogger(__name__)


class AI(commands.Cog):
    """Local AI chat, DM auto-replies, guild AI channels, and runtime-aware self-knowledge."""

    GREETINGS = {"hi", "hello", "hey", "yo", "sup", "hiya", "heya", "pawy", "nightpaw"}
    LOW_VALUE = {
        "k", "kk", "ok", "okay", "lol", "lmao", "xd", "fr", "real", "same", "true", "thanks", "thx", "ty",
        "nice", "cool", "damn", "bro", "hmm", "hmmm", "alr", "aight",
    }
    DIRECT_OPENERS = (
        "can you", "could you", "would you", "do you", "what do", "what's", "what is", "why do", "how do",
        "who are", "who is", "where is", "when is", "tell me", "explain", "list", "show", "check", "give me",
        "summarize", "summary", "opinion", "thoughts on", "feedback on",
    )
    ACTION_ALLOWLIST = {
        "help",
        "status", "remind", "remindlist", "remindclear", "weather", "moonphase", "moonrise", "moonset",
        "avatar", "wolfy", "packbios", "resonance", "moonlore", "blaze", "kael", "matthijs",
        "wolffact", "wolfmemory", "wolfdream", "wolfsign", "track", "scout", "fortune", "quote",
        "hunttips", "howl", "growl", "shift", "lonewolf", "wag", "moodtail", "moonhowl",
        "musicpicks", "fursona", "wolfpackstats",
        "trustlist", "packhealth",
        "userinfo", "warnings",
        "aistatus", "aidiag", "aisetchannel", "aiclearchannel", "aienable", "aidisable",
        "aimentions", "aismart", "aiprompt", "aiclearhistory",
        "botping", "debugreport",
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = AIService(bot)
        self.cooldowns: dict[tuple[int, int], float] = {}
        self.error_cooldowns: dict[int, float] = {}
        self.started_at = discord.utils.utcnow()

    async def cog_load(self):
        self.started_at = discord.utils.utcnow()
        await ensure_schema()

    async def cog_unload(self):
        await self.service.close()

    def _cooldown_ok(self, user_id: int, scope_id: int, seconds: float) -> bool:
        key = (user_id, scope_id)
        now = time.monotonic()
        last = self.cooldowns.get(key, 0.0)
        if now - last < seconds:
            return False
        self.cooldowns[key] = now
        return True

    def _log_auto_reply(self, message: discord.Message, event: str, *, level: int = logging.DEBUG, **fields) -> None:
        preview = " ".join((message.content or "").split())[:80]
        context = {
            "event": event,
            "message_id": message.id,
            "author_id": getattr(message.author, "id", 0),
            "guild_id": getattr(message.guild, "id", None),
            "channel_id": getattr(message.channel, "id", None),
            "attachments": len(message.attachments),
            "preview": preview or "(empty)",
        }
        for key, value in fields.items():
            context[key] = value
        rendered = " ".join(f"{key}={value}" for key, value in context.items())
        logger.log(level, "AI auto-response decision", extra={"context": f" {rendered}"})

    async def _starts_with_real_command(self, message: discord.Message) -> bool:
        content = (message.content or "").lstrip()
        if not content.startswith(config.PREFIX):
            return False
        ctx = await self.bot.get_context(message)
        return bool(getattr(ctx, "valid", False))

    async def _is_admin_here(self, source) -> bool:
        if isinstance(source, commands.Context):
            if not source.guild:
                return source.author.id == config.OWNER_ID
            perms = getattr(source.author.guild_permissions, "manage_guild", False) or source.author.id == config.OWNER_ID
            return bool(perms)
        if not source.guild:
            return source.user.id == config.OWNER_ID
        perms = getattr(source.user.guild_permissions, "manage_guild", False) or source.user.id == config.OWNER_ID
        return bool(perms)

    async def _send_text(self, target, text: str, *, ephemeral: bool = False):
        if isinstance(target, commands.Context):
            return await target.send(text)
        if not target.response.is_done():
            return await target.response.send_message(text, ephemeral=ephemeral)
        return await target.followup.send(text, ephemeral=ephemeral)

    async def _require_guild_admin(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            await ctx.send(wolf_wrap("This command can only be used inside a server."))
            return False
        if not await self._is_admin_here(ctx):
            await ctx.send(wolf_wrap("You need Manage Server permission for that here."))
            return False
        return True

    async def _require_guild_admin_interaction(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await self._send_text(interaction, wolf_wrap("This command can only be used inside a server."), ephemeral=True)
            return False
        if not await self._is_admin_here(interaction):
            await self._send_text(interaction, wolf_wrap("You need Manage Server permission for that here."), ephemeral=True)
            return False
        return True

    async def _send_with_typing(
        self,
        destination: discord.abc.Messageable,
        *,
        text: str | None = None,
        embed: discord.Embed | None = None,
        delay: float = 0.55,
    ):
        async with destination.typing():
            if delay > 0:
                await asyncio.sleep(delay)
        return await destination.send(text, embed=embed)

    async def _typing_loop(self, destination: discord.abc.Messageable, *, interval: float = 8.0):
        try:
            while True:
                async with destination.typing():
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    @contextlib.asynccontextmanager
    async def _processing_feedback(self, destination: discord.abc.Messageable, *, enabled: bool = True):
        typing_task = asyncio.create_task(self._typing_loop(destination)) if enabled else None
        try:
            yield
        finally:
            if typing_task is not None:
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task

    async def _attachment_progress_task(self, message: discord.Message, attachment_count: int):
        frames = [
            f"📎 Received {attachment_count} attachment{'s' if attachment_count != 1 else ''}. [██░░░░] Reading…",
            f"📎 Received {attachment_count} attachment{'s' if attachment_count != 1 else ''}. [████░░] Parsing…",
            f"📎 Received {attachment_count} attachment{'s' if attachment_count != 1 else ''}. [██████] Analyzing…",
            f"📎 Received {attachment_count} attachment{'s' if attachment_count != 1 else ''}. [████████] Finishing…",
        ]
        status = await message.channel.send(frames[0])
        try:
            idx = 1
            while True:
                await asyncio.sleep(1.0)
                await status.edit(content=frames[min(idx, len(frames) - 1)])
                if idx < len(frames) - 1:
                    idx += 1
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await status.delete()
            raise
        except Exception:
            return

    async def _send_error_once(self, destination: discord.abc.Messageable, scope_id: int, exc: Exception):
        logger.error("AI reply failure", exc_info=(type(exc), exc, exc.__traceback__))
        now = time.monotonic()
        if now - self.error_cooldowns.get(scope_id, 0.0) < 12.0:
            return
        self.error_cooldowns[scope_id] = now
        message = str(exc)
        if "ollama" in message.casefold() or "model `" in message.casefold():
            wrapped = wolf_wrap(f"AI is unavailable right now: {message}")
        else:
            wrapped = wolf_wrap(f"AI is currently unavailable: {message}")
        await self._send_with_typing(destination, text=wrapped, delay=0.85)

    async def _action_rank(self, user: discord.abc.User, guild: discord.Guild | None) -> str:
        if user.id == config.OWNER_ID:
            return "owner"
        if await user_is_trusted(user.id):
            return "trusted"
        if guild is not None:
            member = guild.get_member(user.id)
            if member and getattr(member.guild_permissions, "manage_guild", False):
                return "serveradmin"
        return "general"

    async def _allowed_action_commands(self, user: discord.abc.User, guild: discord.Guild | None) -> list[dict[str, str]]:
        rank = await self._action_rank(user, guild)
        allowed_categories = {"general"}
        if rank in {"trusted", "owner"}:
            allowed_categories.add("trusted")
        # AI config commands are server-admin gated and only make sense inside guilds.
        if rank in {"serveradmin", "owner"} and guild is not None:
            allowed_categories.add("serveradmin")
            allowed_categories.add("aiconfig")
        if rank == "owner":
            allowed_categories.add("owner")

        commands_out: list[dict[str, str]] = []
        seen: set[str] = set()
        for cmd in self.bot.commands:
            if cmd.hidden:
                continue
            if cmd.name in seen or cmd.name not in self.ACTION_ALLOWLIST:
                continue
            category = infer_command_category(prefix_cmd=cmd)
            if category not in allowed_categories:
                continue
            commands_out.append(
                {
                    "name": cmd.name,
                    "usage": f"{config.PREFIX}{cmd.qualified_name}",
                    "description": " ".join((cmd.help or "").split())[:220] or "No description provided.",
                    "category": category,
                }
            )
            seen.add(cmd.name)
        return commands_out

    async def _invoke_action_command(self, source_message: discord.Message, command_name: str, args_text: str) -> dict[str, object]:
        command = self.bot.get_command(command_name)
        if command is None:
            return {"text": f"Action command `{command_name}` was not found.", "visible_output": False}

        base_ctx = await self.bot.get_context(source_message)
        action_ctx = copy.copy(base_ctx)
        action_ctx.command = command
        action_ctx.invoked_with = command.name
        action_ctx.prefix = config.PREFIX
        action_ctx.view = StringView(args_text or "")

        captured: list[str] = []
        visible_output = False

        async def capture_send(content=None, **kwargs):
            nonlocal visible_output
            parts: list[str] = []
            if content:
                parts.append(str(content))
            embed = kwargs.get("embed")
            if embed is not None:
                embed_bits: list[str] = []
                if getattr(embed, "title", None):
                    embed_bits.append(f"title={embed.title}")
                if getattr(embed, "description", None):
                    embed_bits.append(f"description={embed.description}")
                for field in getattr(embed, "fields", [])[:6]:
                    embed_bits.append(f"{field.name}: {field.value}")
                if embed_bits:
                    parts.append("embed[" + " | ".join(embed_bits) + "]")
            if kwargs.get("file") is not None or kwargs.get("files"):
                parts.append("file attachment sent")
            if parts:
                captured.append(" ".join(parts)[:1200])
            visible_output = True
            return await source_message.channel.send(content, **kwargs)

        action_ctx.send = capture_send
        try:
            await command.invoke(action_ctx)
        except commands.CommandError as exc:
            detail = captured[-1] if captured else str(exc)
            return {"text": f"Action `{command_name}` failed: {detail}", "visible_output": visible_output}
        except Exception as exc:
            detail = captured[-1] if captured else str(exc)
            return {"text": f"Action `{command_name}` failed: {detail}", "visible_output": visible_output}

        if captured:
            return {
                "text": f"Ran `{config.PREFIX}{command_name} {args_text}`.\nResult: " + "\n".join(captured[:4]),
                "visible_output": visible_output,
            }
        return {
            "text": f"Ran `{config.PREFIX}{command_name} {args_text}` successfully.",
            "visible_output": visible_output,
        }

    async def _maybe_run_ai_action(
        self,
        *,
        prompt: str,
        user: discord.abc.User,
        guild: discord.Guild | None,
        source_message: discord.Message | None,
        custom_prompt: str,
    ) -> tuple[str, bool, str, dict[str, str]]:
        if source_message is None:
            return "", False, "", {}
        if guild is not None:
            settings = await get_guild_settings(guild.id)
            if not bool(settings.get("actions_enabled")):
                if self.service._looks_like_action_request(prompt):
                    self._log_auto_reply(source_message, "ignored_because_actions_disabled")
                return "", False, "", {}

        allowed_commands = await self._allowed_action_commands(user, guild)
        plan = await self.service.resolve_action_plan(prompt=prompt, allowed_commands=allowed_commands)
        if not plan:
            return "", False, "", {}

        confidence = str(plan.get("confidence") or "weak")
        command_name = str(plan["command"])
        planner = str(plan.get("planner") or "llm")
        if planner == "llm" and confidence == "weak" and command_name in {"aienable", "aidisable", "aisetchannel", "aiclearchannel", "aiprompt", "aiclearhistory"}:
            logger.info("AI action plan refused due to weak confidence for elevated command", extra={"context": f" command={command_name}"})
            return "", False, "", {}

        logger.info(
            "AI action plan selected",
            extra={"context": f" planner={planner} confidence={confidence} command={command_name} args={plan['args'][:200]}"},
        )
        result = await self._invoke_action_command(source_message, command_name, plan["args"])
        meta = {
            "planner": planner,
            "confidence": confidence,
            "command": command_name,
            "reason": str(plan.get("reason") or "action executed"),
        }
        return (
            f"{result['text']}\nVisible Discord output already sent: {bool(result['visible_output'])}\nPlanner reason: {plan['reason'] or 'none'}",
            bool(result["visible_output"]),
            command_name,
            meta,
        )

    def _strip_bot_mention(self, message: discord.Message) -> str:
        content = message.content
        if self.bot.user:
            content = content.replace(self.bot.user.mention, "").replace(f"<@!{self.bot.user.id}>", "")
        return content.strip()

    def _is_reply_to_me(self, message: discord.Message) -> bool:
        ref = message.reference
        resolved = getattr(ref, "resolved", None)
        if isinstance(resolved, discord.Message) and self.bot.user:
            return resolved.author.id == self.bot.user.id
        return False

    def _should_auto_reply(self, message: discord.Message) -> bool:
        content = self._strip_bot_mention(message)
        normalized = " ".join(content.casefold().split())
        if not normalized:
            return bool(message.attachments)
        if message.attachments and not content.strip():
            return True
        if self._is_reply_to_me(message):
            return True
        if "?" in content:
            return True
        words = normalized.split()
        if len(words) <= 3 and normalized in self.LOW_VALUE:
            return False
        if any(opener in normalized for opener in self.DIRECT_OPENERS):
            return True
        if any(word in normalized for word in ("you", "your", "nightpaw", "pawy", "bot")):
            return True
        if len(words) <= 6 and any(word in self.GREETINGS for word in words):
            return True
        other_mentions = [m for m in message.mentions if not self.bot.user or m.id != self.bot.user.id]
        if other_mentions and not (self.bot.user and self.bot.user in message.mentions):
            return False
        if len(words) < 4:
            return False
        return normalized.endswith(("help", "thoughts", "opinion", "explain", "summary"))

    async def _record_context(self, message: discord.Message, settings: dict | None = None):
        if not message.guild:
            return
        summary_text = message.content.strip()
        if message.attachments:
            attachment_names = ', '.join(att.filename for att in message.attachments[:4])
            summary_text = (summary_text + ' ' if summary_text else '') + f"[attachments: {attachment_names}]"
        if not summary_text.strip():
            return
        if settings is None:
            settings = await get_guild_settings(message.guild.id)
        if not settings["enabled"]:
            return
        await record_channel_message(
            message.guild.id,
            message.channel.id,
            message.author.id,
            getattr(message.author, "display_name", message.author.name),
            summary_text,
        )

    async def _maybe_handle_avatar_request(self, message: discord.Message, prompt: str) -> bool:
        normalized = " ".join(prompt.casefold().split())
        if not any(word in normalized for word in ("avatar", "banner", "profile image", "profile pic", "profile picture", "pfp")):
            return False
        if not any(word in normalized for word in ("show", "get", "fetch", "extract", "lookup", "display", "see")):
            return False

        avatar_cog = self.bot.cogs.get("Avatar")
        if avatar_cog is None:
            return False

        target = None
        non_bot_mentions = [m for m in message.mentions if not self.bot.user or m.id != self.bot.user.id]
        if non_bot_mentions:
            target = non_bot_mentions[0]
        else:
            id_match = re.search(r"\b\d{15,22}\b", prompt)
            if id_match:
                user_id = int(id_match.group(0))
                if message.guild:
                    try:
                        target = await message.guild.fetch_member(user_id)
                    except discord.NotFound:
                        target = None
                    except discord.HTTPException:
                        target = None
                if target is None:
                    try:
                        target = await self.bot.fetch_user(user_id)
                    except discord.HTTPException:
                        target = None
            elif re.search(r"\bmy\b", normalized):
                target = message.author

        if target is None:
            return False

        try:
            embed = await avatar_cog._profile_embed(target)
            await self._send_with_typing(message.channel, embed=embed, delay=0.45)
            return True
        except Exception:
            await self._send_with_typing(
                message.channel,
                text=wolf_wrap("I couldn't complete that avatar lookup cleanly. Try `!avatar <user or id>` for the direct command path."),
                delay=0.35,
            )
            return True


    async def _collect_processed_attachments(self, message: discord.Message):
        entries = await collect_message_attachments(message)
        if not entries:
            return None
        return await process_discord_attachments(entries)

    async def _chat_and_send(
        self,
        destination: discord.abc.Messageable,
        *,
        prompt: str,
        user: discord.abc.User,
        guild: discord.Guild | None = None,
        channel: discord.abc.Messageable | None = None,
        custom_prompt: str = "",
        attachments=None,
        source_message: discord.Message | None = None,
        manage_typing: bool = True,
    ):
        chat_started = time.perf_counter()
        if isinstance(channel, discord.Message) and channel.guild:
            channel = channel.channel
        scope_type = "dm" if guild is None else "guild"
        scope_id = user.id if guild is None else guild.id
        progress_task = None
        typing_task = asyncio.create_task(self._typing_loop(destination)) if manage_typing else None
        if attachments and getattr(attachments, 'attachments', None) and source_message is not None:
            progress_task = asyncio.create_task(self._attachment_progress_task(source_message, len(attachments.attachments)))
        try:
            action_result_text, action_visible_output, action_command_name, action_meta = await self._maybe_run_ai_action(
                prompt=prompt,
                user=user,
                guild=guild,
                source_message=source_message,
                custom_prompt=custom_prompt,
            )
            reply = await self.service.reply(
                user_text=prompt,
                scope_type=scope_type,
                scope_id=scope_id,
                user_id=user.id,
                display_name=getattr(user, "display_name", user.name),
                user=user,
                guild=guild,
                channel=channel,
                custom_prompt=custom_prompt,
                attachments=attachments,
                action_result_text=action_result_text,
                action_meta=action_meta,
            )
        finally:
            if typing_task is not None:
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task
            if progress_task is not None:
                progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await progress_task
        send_started = time.perf_counter()
        try:
            if action_visible_output and action_result_text:
                if action_command_name == "help":
                    if source_message is not None:
                        self._log_auto_reply(
                            source_message,
                            "message_send_succeeded",
                            level=logging.INFO,
                            send_ms=round((time.perf_counter() - send_started) * 1000, 2),
                            total_ms=round((time.perf_counter() - chat_started) * 1000, 2),
                            mode="help_action_output_already_sent",
                        )
                    return
                await destination.send(reply if len(reply) < 500 else "I ran it above. The command output is already in chat.")
            else:
                await destination.send(reply)
        except Exception as exc:
            if source_message is not None:
                self._log_auto_reply(
                    source_message,
                    "message_send_failed",
                    level=logging.ERROR,
                    send_ms=round((time.perf_counter() - send_started) * 1000, 2),
                    total_ms=round((time.perf_counter() - chat_started) * 1000, 2),
                    error=type(exc).__name__,
                )
            raise
        if source_message is not None:
            self._log_auto_reply(
                source_message,
                "message_send_succeeded",
                level=logging.INFO,
                send_ms=round((time.perf_counter() - send_started) * 1000, 2),
                total_ms=round((time.perf_counter() - chat_started) * 1000, 2),
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        decision_started = time.perf_counter()
        self._log_auto_reply(message, "message_received")
        if message.author.bot:
            self._log_auto_reply(message, "ignored_because_author_is_bot")
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            self._log_auto_reply(message, "ignored_because_author_is_bot")
            return
        if getattr(message, "created_at", None) and message.created_at < (self.started_at - timedelta(seconds=1)):
            self._log_auto_reply(message, "ignored_because_pre_startup_message")
            return

        # DMs always respond unless a normal command is being used.
        if isinstance(message.channel, discord.DMChannel):
            if await self._starts_with_real_command(message):
                self._log_auto_reply(
                    message,
                    "ignored_because_command",
                    decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
                )
                return
            prompt_text = message.content.strip()
            if await self._maybe_handle_avatar_request(message, prompt_text):
                return
            try:
                async with self._processing_feedback(message.channel):
                    attachments = await self._collect_processed_attachments(message)
                    if not prompt_text and attachments and attachments.attachments:
                        prompt_text = "Please analyze the attached content."
                    if not prompt_text:
                        return
                    if not self._cooldown_ok(message.author.id, message.author.id, 2.0):
                        self._log_auto_reply(message, "ignored_because_cooldown")
                        return
                    self._log_auto_reply(
                        message,
                        "accepted_dm_reply",
                        level=logging.INFO,
                        decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
                    )
                    await self._chat_and_send(
                        message.channel,
                        prompt=prompt_text,
                        user=message.author,
                        channel=message.channel,
                        attachments=attachments,
                        source_message=message,
                        manage_typing=False,
                    )
            except Exception as exc:
                await self._send_error_once(message.channel, message.author.id, exc)
            return

        guild = message.guild
        if guild is None:
            return

        settings = await get_guild_settings(guild.id)
        await self._record_context(message, settings)
        if not settings["enabled"]:
            self._log_auto_reply(
                message,
                "ignored_because_ai_disabled",
                decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
            )
            return
        if await self._starts_with_real_command(message):
            self._log_auto_reply(
                message,
                "ignored_because_command",
                decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
            )
            return

        mentioned = self.bot.user in message.mentions if self.bot.user else False
        in_ai_channel = bool(settings["channel_id"] and message.channel.id == settings["channel_id"])
        trigger = False
        trigger_reason = ""
        if mentioned and settings["mention_enabled"]:
            trigger = True
            trigger_reason = "accepted_for_mention_reply"
        elif mentioned and not settings["mention_enabled"]:
            self._log_auto_reply(message, "ignored_because_mentions_disabled")
            return
        elif settings["channel_id"] and not in_ai_channel:
            self._log_auto_reply(
                message,
                "ignored_because_wrong_channel",
                decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
                configured_channel_id=settings["channel_id"],
            )
            return
        elif in_ai_channel and not settings["channel_chat_enabled"]:
            self._log_auto_reply(message, "ignored_because_channel_chat_disabled")
            return
        elif in_ai_channel and not settings["smart_replies_enabled"]:
            self._log_auto_reply(
                message,
                "ignored_because_smart_auto_replies_disabled",
                decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
            )
            return
        elif in_ai_channel and self._should_auto_reply(message):
            trigger = True
            trigger_reason = "accepted_for_set_auto_chat_channel"

        if not trigger:
            self._log_auto_reply(
                message,
                "ignored_because_not_eligible",
                decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
            )
            return
        stripped_prompt = self._strip_bot_mention(message)
        if await self._maybe_handle_avatar_request(message, stripped_prompt):
            return

        self._log_auto_reply(
            message,
            trigger_reason,
            level=logging.INFO,
            decision_ms=round((time.perf_counter() - decision_started) * 1000, 2),
        )
        try:
            async with self._processing_feedback(message.channel):
                attachments = await self._collect_processed_attachments(message)
                cooldown_seconds = float(settings.get("reply_cooldown_seconds", 3) or 3)
                if not self._cooldown_ok(message.author.id, guild.id, cooldown_seconds):
                    self._log_auto_reply(message, "ignored_because_cooldown")
                    return

                content = stripped_prompt
                if not content and attachments and attachments.attachments:
                    content = "Please analyze the attached content."
                if not content:
                    content = "What do you need?"

                await self._chat_and_send(
                    message.channel,
                    prompt=content,
                    user=message.author,
                    guild=guild,
                    channel=message.channel,
                    custom_prompt=str(settings.get("custom_prompt", "")),
                    attachments=attachments,
                    source_message=message,
                    manage_typing=False,
                )
        except Exception as exc:
            await self._send_error_once(message.channel, guild.id, exc)

    @commands.command(name="ai", help="Ask NightPaw AI something")
    async def ai_prefix(self, ctx: commands.Context, *, prompt: str = ""):
        if ctx.guild:
            settings = await get_guild_settings(ctx.guild.id)
            await self._record_context(ctx.message, settings)
            if not settings["enabled"] or not settings["commands_enabled"]:
                await ctx.send(wolf_wrap("AI command mode is disabled in this server."))
                return
            custom_prompt = str(settings.get("custom_prompt", ""))
        else:
            custom_prompt = ""

        try:
            if await self._maybe_handle_avatar_request(ctx.message, prompt):
                return
            async with self._processing_feedback(ctx.channel):
                attachments = await self._collect_processed_attachments(ctx.message)
                prompt_text = prompt.strip()
                if not prompt_text and attachments and attachments.attachments:
                    prompt_text = "Please analyze the attached content."
                if not prompt_text:
                    await ctx.send(wolf_wrap("Give me a prompt or attach something for me to read."))
                    return
                await self._chat_and_send(
                    ctx.channel,
                    prompt=prompt_text,
                    user=ctx.author,
                    guild=ctx.guild,
                    channel=ctx.channel,
                    custom_prompt=custom_prompt,
                    attachments=attachments,
                    source_message=ctx.message,
                    manage_typing=False,
                )
        except Exception as exc:
            await self._send_error_once(ctx.channel, ctx.author.id if ctx.guild is None else ctx.guild.id, exc)

    @app_commands.command(name="ai", description="Ask NightPaw AI something", extras={"category": "general"})
    @allow_everywhere_slash()
    async def ai_slash(
        self,
        interaction: discord.Interaction,
        prompt: str = "",
        attachment: discord.Attachment | None = None,
        ephemeral: bool = False,
    ):
        custom_prompt = ""
        if interaction.guild:
            settings = await get_guild_settings(interaction.guild.id)
            if not settings["enabled"] or not settings["commands_enabled"]:
                await interaction.response.send_message(wolf_wrap("AI command mode is disabled in this server."), ephemeral=True)
                return
            custom_prompt = str(settings.get("custom_prompt", ""))
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)
        try:
            attachments = None
            if attachment is not None:
                attachments = await process_discord_attachments([(attachment, 'message')])
            prompt_text = prompt.strip()
            if not prompt_text and attachments and attachments.attachments:
                prompt_text = "Please analyze the attached content."
            if not prompt_text:
                await interaction.followup.send(wolf_wrap("Give me a prompt or attach something for me to read."), ephemeral=True)
                return
            reply = await self.service.reply(
                user_text=prompt_text,
                scope_type="dm" if interaction.guild is None else "guild",
                scope_id=interaction.user.id if interaction.guild is None else interaction.guild.id,
                user_id=interaction.user.id,
                display_name=getattr(interaction.user, "display_name", interaction.user.name),
                user=interaction.user,
                guild=interaction.guild,
                channel=interaction.channel,
                custom_prompt=custom_prompt,
                attachments=attachments,
            )
            await interaction.followup.send(reply, ephemeral=ephemeral)
        except Exception as exc:
            await interaction.followup.send(wolf_wrap(f"AI is unavailable right now: {exc}"), ephemeral=True)

    @commands.command(name="aistatus", help="Show live AI feature awareness and config status")
    async def aistatus_prefix(self, ctx: commands.Context):
        snapshot = build_feature_snapshot(self.bot)
        embed = render_feature_embed(snapshot)
        if ctx.guild:
            settings = await get_guild_settings(ctx.guild.id)
            embed.add_field(
                name="Guild AI",
                value=(
                    f"Enabled: `{bool(settings['enabled'])}`\n"
                    f"Channel: `{settings['channel_id']}`\n"
                    f"Mentions: `{bool(settings['mention_enabled'])}`\n"
                    f"Smart replies: `{bool(settings['smart_replies_enabled'])}`"
                ),
                inline=False,
            )
        ok, err = await self.service.is_available()
        embed.add_field(name="Local model", value="Online" if ok else f"Offline: {err}", inline=False)
        embed.add_field(name="Attachment support", value=f"Text/code attachments: `on`\nVision model: `{getattr(config, 'AI_VISION_MODEL', 'none') or 'none'}`", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="aistatus", description="Show live AI feature awareness and config status", extras={"category": "general"})
    @allow_everywhere_slash()
    async def aistatus_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        snapshot = build_feature_snapshot(self.bot)
        embed = render_feature_embed(snapshot)
        if interaction.guild:
            settings = await get_guild_settings(interaction.guild.id)
            embed.add_field(
                name="Guild AI",
                value=(
                    f"Enabled: `{bool(settings['enabled'])}`\n"
                    f"Channel: `{settings['channel_id']}`\n"
                    f"Mentions: `{bool(settings['mention_enabled'])}`\n"
                    f"Smart replies: `{bool(settings['smart_replies_enabled'])}`"
                ),
                inline=False,
            )
        ok, err = await self.service.is_available()
        embed.add_field(name="Local model", value="Online" if ok else f"Offline: {err}", inline=False)
        embed.add_field(name="Attachment support", value=f"Text/code attachments: `on`\nVision model: `{getattr(config, 'AI_VISION_MODEL', 'none') or 'none'}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    def _aidiag_embed(self) -> discord.Embed:
        info = self.service.get_last_run_info()
        embed = discord.Embed(title="AI Diagnostics", color=config.BOT_COLOR)
        if not info.get("timestamp"):
            embed.description = "No AI turn has been recorded yet in this session."
            return embed
        embed.add_field(name="Timestamp", value=str(info.get("timestamp")), inline=False)
        embed.add_field(name="Scope", value=f"{info.get('scope_type')}:{info.get('scope_id')}", inline=True)
        embed.add_field(name="User", value=str(info.get("user_id")), inline=True)
        embed.add_field(name="Route", value=str(info.get("route_used") or "idle"), inline=True)
        embed.add_field(name="Reason", value=str(info.get("route_reason") or "none"), inline=True)
        embed.add_field(name="Planner", value=str(info.get("action_planner_used") or "none"), inline=True)
        embed.add_field(name="Confidence", value=str(info.get("action_confidence") or "none"), inline=True)
        embed.add_field(name="Action", value=str(info.get("action_command") or "none"), inline=True)
        embed.add_field(name="Fallback", value=str(info.get("fallback_used") or "none"), inline=True)
        embed.add_field(name="Memory Stored", value="yes" if info.get("memory_stored_this_turn") else "no", inline=True)
        embed.add_field(name="Memories Loaded", value=f"{info.get('memories_loaded_count', 0)} ({info.get('memory_types_loaded') or 'none'})", inline=True)
        embed.add_field(name="History Loaded", value=str(info.get("history_loaded_count", 0)), inline=True)
        embed.add_field(name="Runtime Sections", value=str(info.get("runtime_sections_included") or "none"), inline=False)
        embed.add_field(name="Feature Summary", value="yes" if info.get("used_feature_summary") else "no", inline=True)
        embed.add_field(name="Attachment Context", value="yes" if info.get("used_attachment_context") else "no", inline=True)
        embed.add_field(name="Vision Prepass", value="yes" if info.get("vision_prepass_used") else "no", inline=True)
        embed.add_field(name="Chat Model", value=str(info.get("chat_model_used") or "none"), inline=True)
        embed.add_field(name="Vision Model", value=str(info.get("vision_model_used") or "none"), inline=True)
        embed.add_field(name="Attachments", value=f"{info.get('attachment_count', 0)} / {info.get('attachment_focus', 'none')}", inline=True)
        embed.set_footer(text="Latest AI turn routing snapshot.")
        return embed

    @commands.command(name="aidiag", help="Show the latest AI routing/model diagnostics")
    async def aidiag_prefix(self, ctx: commands.Context):
        await ctx.send(embed=self._aidiag_embed())

    @app_commands.command(name="aidiag", description="Show the latest AI routing/model diagnostics", extras={"category": "general"})
    @allow_everywhere_slash()
    async def aidiag_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._aidiag_embed(), ephemeral=ephemeral)

    @commands.command(name="aisetchannel", help="Set the server AI auto-chat channel")
    async def aisetchannel_prefix(self, ctx: commands.Context, channel: discord.TextChannel):
        if not await self._require_guild_admin(ctx):
            return
        await upsert_guild_settings(ctx.guild.id, channel_id=channel.id, enabled=1)
        await ctx.send(wolf_wrap(f"AI auto-chat channel set to {channel.mention}."))

    @app_commands.command(name="aisetchannel", description="Set the server AI auto-chat channel", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aisetchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        await upsert_guild_settings(interaction.guild.id, channel_id=channel.id, enabled=1)
        await interaction.response.send_message(wolf_wrap(f"AI auto-chat channel set to {channel.mention}."), ephemeral=ephemeral)

    @commands.command(name="aiclearchannel", help="Clear the server AI auto-chat channel")
    async def aiclearchannel_prefix(self, ctx: commands.Context):
        if not await self._require_guild_admin(ctx):
            return
        await upsert_guild_settings(ctx.guild.id, channel_id=None)
        await ctx.send(wolf_wrap("AI auto-chat channel cleared."))

    @app_commands.command(name="aiclearchannel", description="Clear the server AI auto-chat channel", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aiclearchannel_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        await upsert_guild_settings(interaction.guild.id, channel_id=None)
        await interaction.response.send_message(wolf_wrap("AI auto-chat channel cleared."), ephemeral=ephemeral)

    @commands.command(name="aienable", help="Enable AI in this server")
    async def aienable_prefix(self, ctx: commands.Context):
        if not await self._require_guild_admin(ctx):
            return
        await upsert_guild_settings(ctx.guild.id, enabled=1)
        await ctx.send(wolf_wrap("AI has been enabled in this server."))

    @app_commands.command(name="aienable", description="Enable AI in this server", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aienable_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        await upsert_guild_settings(interaction.guild.id, enabled=1)
        await interaction.response.send_message(wolf_wrap("AI has been enabled in this server."), ephemeral=ephemeral)

    @commands.command(name="aidisable", help="Disable AI in this server")
    async def aidisable_prefix(self, ctx: commands.Context):
        if not await self._require_guild_admin(ctx):
            return
        await upsert_guild_settings(ctx.guild.id, enabled=0)
        await ctx.send(wolf_wrap("AI has been disabled in this server."))

    @app_commands.command(name="aidisable", description="Disable AI in this server", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aidisable_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        await upsert_guild_settings(interaction.guild.id, enabled=0)
        await interaction.response.send_message(wolf_wrap("AI has been disabled in this server."), ephemeral=ephemeral)

    @commands.command(name="aimentions", help="Enable or disable mention replies: on/off")
    async def aimentions_prefix(self, ctx: commands.Context, state: str):
        if not await self._require_guild_admin(ctx):
            return
        value = state.lower() in {"on", "true", "yes", "1"}
        await upsert_guild_settings(ctx.guild.id, mention_enabled=int(value))
        await ctx.send(wolf_wrap(f"Mention replies {'enabled' if value else 'disabled'}."))

    @app_commands.command(name="aimentions", description="Enable or disable mention replies", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aimentions_slash(self, interaction: discord.Interaction, state: str, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        value = state.lower() in {"on", "true", "yes", "1"}
        await upsert_guild_settings(interaction.guild.id, mention_enabled=int(value))
        await interaction.response.send_message(wolf_wrap(f"Mention replies {'enabled' if value else 'disabled'}."), ephemeral=ephemeral)

    @commands.command(name="aismart", aliases=["aismartreplies"], help="Enable or disable smart auto replies: on/off")
    async def aismart_prefix(self, ctx: commands.Context, state: str):
        if not await self._require_guild_admin(ctx):
            return
        value = state.lower() in {"on", "true", "yes", "1"}
        await upsert_guild_settings(ctx.guild.id, smart_replies_enabled=int(value))
        await ctx.send(wolf_wrap(f"Smart auto replies {'enabled' if value else 'disabled'}."))

    @app_commands.command(name="aismart", description="Enable or disable smart auto replies", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aismart_slash(self, interaction: discord.Interaction, state: str, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        value = state.lower() in {"on", "true", "yes", "1"}
        await upsert_guild_settings(interaction.guild.id, smart_replies_enabled=int(value))
        await interaction.response.send_message(wolf_wrap(f"Smart auto replies {'enabled' if value else 'disabled'}."), ephemeral=ephemeral)

    @commands.command(name="aiactions", help="Enable or disable AI command actions in this server: on/off")
    async def aiactions_prefix(self, ctx: commands.Context, state: str):
        if not await self._require_guild_admin(ctx):
            return
        value = state.lower() in {"on", "true", "yes", "1"}
        await upsert_guild_settings(ctx.guild.id, actions_enabled=int(value))
        await ctx.send(wolf_wrap(f"AI command actions {'enabled' if value else 'disabled'} for this server."))

    @app_commands.command(name="aiactions", description="Enable or disable AI command actions in this server", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aiactions_slash(self, interaction: discord.Interaction, state: str, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        value = state.lower() in {"on", "true", "yes", "1"}
        await upsert_guild_settings(interaction.guild.id, actions_enabled=int(value))
        await interaction.response.send_message(wolf_wrap(f"AI command actions {'enabled' if value else 'disabled'} for this server."), ephemeral=ephemeral)

    @commands.command(name="aiprompt", help="Set a server-specific AI instruction")
    async def aiprompt_prefix(self, ctx: commands.Context, *, prompt: str = ""):
        if not await self._require_guild_admin(ctx):
            return
        await upsert_guild_settings(ctx.guild.id, custom_prompt=prompt.strip())
        await ctx.send(wolf_wrap("Server-specific AI prompt updated." if prompt.strip() else "Server-specific AI prompt cleared."))

    @app_commands.command(name="aiprompt", description="Set a server-specific AI instruction", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aiprompt_slash(self, interaction: discord.Interaction, prompt: str = "", ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        await upsert_guild_settings(interaction.guild.id, custom_prompt=prompt.strip())
        await interaction.response.send_message(
            wolf_wrap("Server-specific AI prompt updated." if prompt.strip() else "Server-specific AI prompt cleared."),
            ephemeral=ephemeral,
        )

    @commands.command(name="aiclearhistory", help="Clear AI chat history and explicit remembered facts for this server")
    async def aiclearhistory_prefix(self, ctx: commands.Context):
        if not await self._require_guild_admin(ctx):
            return
        removed = await clear_history("guild", ctx.guild.id)
        await ctx.send(wolf_wrap(f"Cleared {removed} AI chat history entries and reset explicit remembered facts for this server."))

    @app_commands.command(name="aiclearhistory", description="Clear AI chat history and explicit remembered facts for this server", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aiclearhistory_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        removed = await clear_history("guild", interaction.guild.id)
        await interaction.response.send_message(
            wolf_wrap(f"Cleared {removed} AI chat history entries and reset explicit remembered facts for this server."),
            ephemeral=ephemeral,
        )

    @commands.command(name="aisetnote", help="Store a persistent AI note about a user")
    async def aisetnote_prefix(self, ctx: commands.Context, member: discord.User | discord.Member, *, note: str):
        if not await self._require_guild_admin(ctx):
            return
        await set_user_note(member.id, note)
        await ctx.send(wolf_wrap(f"Stored AI note for <@{member.id}>."))

    @app_commands.command(name="aisetnote", description="Store a persistent AI note about a user", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aisetnote_slash(self, interaction: discord.Interaction, member: discord.User, note: str, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        await set_user_note(member.id, note)
        await interaction.response.send_message(wolf_wrap(f"Stored AI note for <@{member.id}>."), ephemeral=ephemeral)

    @commands.command(name="aigetnote", help="View a stored persistent AI note for a user")
    async def aigetnote_prefix(self, ctx: commands.Context, member: discord.User | discord.Member):
        if not await self._require_guild_admin(ctx):
            return
        note = await get_user_note(member.id)
        if not note:
            await ctx.send(wolf_wrap(f"No AI note is stored for <@{member.id}>."))
            return
        await ctx.send(wolf_wrap(f"AI note for <@{member.id}>: {note}"))

    @app_commands.command(name="aigetnote", description="View a stored persistent AI note for a user", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aigetnote_slash(self, interaction: discord.Interaction, member: discord.User, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        note = await get_user_note(member.id)
        if not note:
            await interaction.response.send_message(wolf_wrap(f"No AI note is stored for <@{member.id}>."), ephemeral=True)
            return
        await interaction.response.send_message(wolf_wrap(f"AI note for <@{member.id}>: {note}"), ephemeral=ephemeral)

    @commands.command(name="aiclearnote", help="Remove a stored persistent AI note for a user")
    async def aiclearnote_prefix(self, ctx: commands.Context, member: discord.User | discord.Member):
        if not await self._require_guild_admin(ctx):
            return
        removed = await clear_user_note(member.id)
        await ctx.send(wolf_wrap("AI note cleared." if removed else "There was no AI note to clear."))

    @app_commands.command(name="aiclearnote", description="Remove a stored persistent AI note for a user", extras={"category": "aiconfig"})
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def aiclearnote_slash(self, interaction: discord.Interaction, member: discord.User, ephemeral: bool = False):
        if not await self._require_guild_admin_interaction(interaction):
            return
        removed = await clear_user_note(member.id)
        await interaction.response.send_message(wolf_wrap("AI note cleared." if removed else "There was no AI note to clear."), ephemeral=ephemeral)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
