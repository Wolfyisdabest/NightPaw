import asyncio
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from pathlib import Path
import random
import traceback

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from checks import check_already_responded
from config import wolf_wrap
from services.ai_state import ensure_schema as ensure_ai_schema
from services.db import ensure_data_dir
from services.guild_policy_service import get_blocked_guild
from services.startup_update_service import compare_and_store_snapshot


def _parse_level(name: str, default: int = logging.INFO) -> int:
    value = getattr(logging, str(name).upper(), None)
    return value if isinstance(value, int) else default


def _chunk_text(text: str, limit: int = 1800) -> list[str]:
    text = text or ''
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        piece = text[:limit]
        split_at = piece.rfind('\n')
        if split_at > limit * 0.6:
            piece = piece[:split_at]
        chunks.append(piece)
        text = text[len(piece):].lstrip('\n')
    return chunks


class RichFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, 'context'):
            record.context = ''
        return super().format(record)


class WebhookLogHandler(logging.Handler):
    """Send rich log records to a Discord webhook, including traceback chunks."""

    def __init__(self):
        super().__init__(level=_parse_level(getattr(config, 'BOT_LOG_WEBHOOK_LEVEL', 'INFO')))
        self._queue: list[logging.LogRecord] = []
        self._ready = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sending = False
        self._session: aiohttp.ClientSession | None = None

    def set_ready(self, loop: asyncio.AbstractEventLoop):
        self._ready = True
        self._loop = loop
        if self._queue:
            asyncio.run_coroutine_threadsafe(self._flush(), loop)

    def emit(self, record: logging.LogRecord):
        if not config.BOT_LOG_WEBHOOK:
            return
        if record.name.startswith('discord.http') and record.levelno < logging.ERROR:
            return
        self._queue.append(record)
        if self._ready and self._loop and self._loop.is_running() and not self._sending:
            asyncio.run_coroutine_threadsafe(self._flush(), self._loop)

    async def _flush(self):
        if not config.BOT_LOG_WEBHOOK or self._sending:
            return
        self._sending = True
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            while self._queue:
                record = self._queue.pop(0)
                try:
                    for payload in self._build_payloads(record):
                        async with self._session.post(config.BOT_LOG_WEBHOOK, json=payload) as resp:
                            await resp.read()
                except Exception:
                    # Last resort: keep console/file logging intact, do not recurse into logging here.
                    pass
        finally:
            self._sending = False

    async def close_session(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _build_payloads(self, record: logging.LogRecord) -> list[dict]:
        level_emoji = '🟢'
        color = 0x2ECC71
        if record.levelno >= logging.ERROR:
            level_emoji = '🔴'
            color = 0xE74C3C
        elif record.levelno >= logging.WARNING:
            level_emoji = '🟠'
            color = 0xF39C12
        elif record.levelno >= logging.INFO:
            level_emoji = '🔵'
            color = 0x3498DB

        message = record.getMessage()
        context = getattr(record, 'context', '') or ''
        location = f"{record.pathname}:{record.lineno}"
        header = {
            'title': f"{level_emoji} [{record.levelname}] {record.name}",
            'color': color,
            'fields': [
                {'name': 'Location', 'value': f'`{location}`', 'inline': False},
                {'name': 'Function', 'value': f'`{record.funcName}`', 'inline': True},
            ],
        }
        if context:
            header['fields'].append({'name': 'Context', 'value': f'```{context[:1000]}```', 'inline': False})

        payloads: list[dict] = []
        msg_chunks = _chunk_text(message or '(no message)', 1800)
        trace_text = ''
        if record.exc_info:
            trace_text = ''.join(traceback.format_exception(*record.exc_info)).strip()
        elif getattr(record, 'stack_info', None):
            trace_text = str(record.stack_info).strip()

        trace_chunks = _chunk_text(trace_text, 1800) if trace_text else []

        first_embed = dict(header)
        first_embed['description'] = f"```{msg_chunks[0]}```"
        payloads.append({'embeds': [first_embed]})

        for extra_chunk in msg_chunks[1:]:
            payloads.append({'embeds': [{
                'title': f'{level_emoji} [{record.levelname}] message (cont.)',
                'description': f'```{extra_chunk}```',
                'color': color,
            }]})

        for idx, tb_chunk in enumerate(trace_chunks, start=1):
            payloads.append({'embeds': [{
                'title': f'{level_emoji} traceback {idx}/{len(trace_chunks)}',
                'description': f'```{tb_chunk}```',
                'color': color,
            }]})

        return payloads


def _configure_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(_parse_level(getattr(config, 'LOG_LEVEL', 'INFO')))

    fmt = RichFormatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s%(context)s')

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(root.level)

    ensure_data_dir()
    log_path = Path(getattr(config, 'BOT_LOG_FILE', 'nightpaw.log'))
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=int(getattr(config, 'BOT_LOG_MAX_BYTES', 5_000_000)),
        backupCount=int(getattr(config, 'BOT_LOG_BACKUP_COUNT', 5)),
        encoding='utf-8',
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(root.level)

    root.addHandler(console)
    root.addHandler(file_handler)

    webhook = WebhookLogHandler()
    root.addHandler(webhook)

    logging.captureWarnings(True)
    logging.getLogger('discord.gateway').setLevel(logging.WARNING)
    logging.getLogger('discord.client').setLevel(logging.INFO)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
    logging.getLogger('aiosqlite').setLevel(logging.WARNING)


_configure_logging()
_webhook_handler = next(h for h in logging.getLogger().handlers if isinstance(h, WebhookLogHandler))
SYNC_STATE_PATH = Path("data/command_sync_state.json")
FAST_EXIT_GRACE_SECONDS = 1.25


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True
intents.presences = True

ensure_data_dir()

bot = commands.Bot(
    command_prefix=config.PREFIX,
    intents=intents,
    help_command=None
)
bot.launch_time = time.time()
bot._nightpaw_status_task = None
bot._nightpaw_startup_dm_sent = False
bot._nightpaw_restart_requested = False
bot._nightpaw_force_exit_code = None

OWNER_ID = config.OWNER_ID

config_errors = config.validate_config()
if config_errors:
    raise RuntimeError("Invalid NightPaw configuration: " + "; ".join(config_errors))


STATUSES = [
    ("online", "playing", "🌲 patrolling the forest edge"),
    ("online", "watching", "🌕 the full moon climb higher"),
    ("online", "listening", "🐺 to the pack settle for the night"),
    ("online", "playing", "🐾 tracking fresh prints in the mud"),
    ("online", "watching", "✨ stars appear one by one"),
    ("online", "listening", "🌊 to the river find its way"),
    ("online", "playing", "🏕️ keeping watch over the den"),
    ("online", "watching", "🌿 the undergrowth for movement"),
    ("online", "listening", "🌬️ to the forest breathe at dawn"),
    ("online", "playing", "🔥 beside the ember fire"),
    ("online", "watching", "🦌 a herd cross the valley floor"),
    ("online", "listening", "👑 to the Alpha give the signal"),
    ("online", "playing", "🌧️ in the rain without shelter"),
    ("online", "watching", "🌅 the horizon bleed into gold"),
    ("online", "playing", "⛰️ high above the treeline"),
    ("idle", "playing", "🌙 drifting between sleep and wake"),
    ("idle", "watching", "🌑 clouds swallow the moon slowly"),
    ("idle", "listening", "💤 to the den breathe at midnight"),
    ("idle", "playing", "🌫️ in the fog between the ash trees"),
    ("idle", "watching", "🕯️ the last ember fade to grey"),
    ("idle", "listening", "🌾 to the wind carry old names"),
    ("idle", "playing", "🏞️ along the quiet river alone"),
    ("idle", "watching", "🌌 the northern lights pulse slowly"),
    ("idle", "listening", "🍂 to leaves fall in the dark"),
    ("idle", "playing", "🧊 on the frozen lake at 3am"),
    ("idle", "watching", "👁️ something move at the treeline"),
    ("idle", "listening", "🌙 to silence that feels too deep"),
    ("idle", "playing", "🌁 where the fog never quite clears"),
    ("idle", "watching", "❄️ snow bury the old pawprints"),
    ("idle", "listening", "🔊 to a howl that stopped mid-breath"),
    ("dnd", "playing", "🩸 through the blood moon hunting ground"),
    ("dnd", "watching", "⚠️ the border for what crosses it"),
    ("dnd", "listening", "⛈️ to the storm tear through the pines"),
    ("dnd", "playing", "🌑 where the shadows move on their own"),
    ("dnd", "watching", "🔴 the crimson horizon with the pack"),
    ("dnd", "listening", "💀 to what the forest stopped saying"),
    ("dnd", "playing", "🏚️ in the ruins no wolf speaks about"),
    ("dnd", "watching", "🌩️ lightning split an ancient oak"),
    ("dnd", "listening", "🐺 for the howl that means run"),
    ("dnd", "playing", "⚡ through the storm without stopping"),
    ("dnd", "watching", "🦴 the hunt reach its bloody end"),
    ("dnd", "listening", "🌋 to something deep beneath the ground"),
    ("dnd", "playing", "🔥 as the forest burns at the edge"),
    ("dnd", "watching", "👁️ a pair of eyes that don't blink"),
    ("dnd", "playing", "🌑 on the wrong side of the ridge"),
]

async def run_status_loop(bot):
    recent: list[int] = []
    circle: list[int] = []
    while True:
        if not circle:
            indices = list(range(len(STATUSES)))
            random.shuffle(indices)
            blocked = set(recent[-10:])
            front = [i for i in indices if i not in blocked]
            back = [i for i in indices if i in blocked]
            circle = front + back
        idx = circle.pop(0)
        recent.append(idx)
        if len(recent) > 10:
            recent.pop(0)
        presence, activity_type, text = STATUSES[idx]
        if presence == "online":
            status = discord.Status.online
        elif presence == "idle":
            status = discord.Status.idle
        elif presence == "dnd":
            status = discord.Status.dnd
        else:
            status = discord.Status.online
        if activity_type == "playing":
            activity = discord.Game(name=text)
        elif activity_type == "watching":
            activity = discord.Activity(type=discord.ActivityType.watching, name=text)
        elif activity_type == "listening":
            activity = discord.Activity(type=discord.ActivityType.listening, name=text)
        else:
            activity = discord.Game(name=text)
        await bot.change_presence(status=status, activity=activity)
        await asyncio.sleep(300)


def _command_sync_signature(bot: commands.Bot) -> str:
    items: list[dict[str, str]] = []
    for cmd in sorted(bot.tree.get_commands(), key=lambda c: c.qualified_name):
        extras = getattr(cmd, "extras", {}) or {}
        params = []
        for param in getattr(cmd, "parameters", []) or []:
            params.append(
                {
                    "name": getattr(param, "name", ""),
                    "description": getattr(param, "description", "") or "",
                    "required": bool(getattr(param, "required", False)),
                    "default": repr(getattr(param, "default", None)),
                    "type": str(getattr(param, "type", "")),
                }
            )
        items.append(
            {
                "name": cmd.qualified_name,
                "description": getattr(cmd, "description", "") or "",
                "category": str(extras.get("category", "")),
                "params": params,
            }
        )
    raw = json.dumps(items, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_sync_state() -> dict[str, str]:
    if not SYNC_STATE_PATH.exists():
        return {}
    try:
        return json.loads(SYNC_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _store_sync_state(signature: str) -> None:
    SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_PATH.write_text(json.dumps({"signature": signature}, indent=2), encoding="utf-8")


async def _sync_tree_if_needed() -> bool:
    signature = _command_sync_signature(bot)
    previous = _load_sync_state().get("signature")
    synced = await bot.tree.sync()
    _store_sync_state(signature)
    logging.info(
        "Slash commands synced.",
        extra={"context": f" count={len(synced)} signature_changed={previous != signature}"},
    )
    return previous != signature


async def _post_startup_notifications() -> None:
    try:
        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(wolf_wrap(f"Back on my paws. {config.BOT_NAME} is online."))
        report = await asyncio.to_thread(compare_and_store_snapshot)
        if report:
            for chunk in _chunk_text(report, 1800):
                await owner.send(chunk)
    except Exception:
        pass


async def _background_ai_schema_prep() -> None:
    started = time.perf_counter()
    try:
        await ensure_ai_schema()
        logging.info(
            "Background AI schema prep complete.",
            extra={"context": f" seconds={time.perf_counter() - started:.2f}"},
        )
    except Exception as exc:
        logging.error("Background AI schema prep failed: %s", exc, exc_info=True)


async def _fast_shutdown(*, restart: bool = False) -> None:
    bot._nightpaw_restart_requested = restart
    bot._nightpaw_force_exit_code = 0

    status_task = getattr(bot, "_nightpaw_status_task", None)
    if status_task and not status_task.done():
        status_task.cancel()

    try:
        await asyncio.wait_for(bot.change_presence(status=discord.Status.invisible, activity=None), timeout=0.35)
    except Exception:
        pass

    try:
        await asyncio.wait_for(_webhook_handler.close_session(), timeout=0.35)
    except Exception:
        pass

    async def _close_bot():
        try:
            await bot.close()
        except Exception:
            pass

    close_task = asyncio.create_task(_close_bot())
    try:
        await asyncio.wait_for(close_task, timeout=FAST_EXIT_GRACE_SECONDS)
    except asyncio.TimeoutError:
        logging.warning(
            "Fast shutdown grace window exceeded; forcing process exit.",
            extra={"context": f" restart={restart}"},
        )
        if restart:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        os._exit(0)


bot._nightpaw_fast_shutdown = _fast_shutdown

# ── Error notification helper ─────────────────────────────────────────────────

async def _notify_error(ctx_or_interaction, error: Exception, cmd_name: str, is_slash: bool = False):
    """DM owner with full crash details. Only called for genuine unexpected errors."""
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    if len(tb) > 1000:
        tb = tb[-1000:]

    try:
        msg = wolf_wrap("Something went wrong in the den. The Alpha has been notified.")
        if is_slash:
            try:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                await ctx_or_interaction.followup.send(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
    except Exception:
        pass

    try:
        owner = await bot.fetch_user(OWNER_ID)
        user = ctx_or_interaction.user if is_slash else ctx_or_interaction.author
        embed = discord.Embed(
            title=f"⚠️ Error — `{'/' if is_slash else '!'}{cmd_name}`",
            color=discord.Color.red()
        )
        embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Command", value=f"`{'/' if is_slash else '!'}{cmd_name}`", inline=True)
        embed.add_field(name="Error", value=f"```{str(error)[:500]}```", inline=False)
        embed.add_field(name="Traceback", value=f"```{tb}```", inline=False)
        await owner.send(embed=embed)
    except Exception:
        pass

# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_error(event_method, *args, **kwargs):
    logging.error(
        f"[EVENT ERR] {event_method}",
        exc_info=True,
        extra={"context": f" args={len(args)} kwargs={list(kwargs.keys())}"},
    )

@bot.event
async def on_ready():
    _webhook_handler.set_ready(bot.loop)
    logging.info(
        f"🐺 {config.BOT_NAME} is online as {bot.user}",
        extra={
            "context": (
                f" guilds={len(bot.guilds)} cogs={len(bot.cogs)} "
                f"main_model={getattr(config, 'AI_MODEL', 'unknown')} "
                f"vision_model={getattr(config, 'AI_VISION_MODEL', 'none') or 'none'} "
                f"log_file={getattr(config, 'BOT_LOG_FILE', 'nightpaw.log')}"
            )
        },
    )
    await _sync_tree_if_needed()

    if bot._nightpaw_status_task is None or bot._nightpaw_status_task.done():
        bot._nightpaw_status_task = bot.loop.create_task(run_status_loop(bot))

    if bot._nightpaw_startup_dm_sent:
        return
    bot._nightpaw_startup_dm_sent = True
    bot.loop.create_task(_post_startup_notifications())

@bot.event
async def on_guild_join(guild: discord.Guild):
    blocked = await get_blocked_guild(guild.id)
    if blocked is None:
        logging.info(
            "Joined guild.",
            extra={"context": f" guild={guild.name} guild_id={guild.id} owner_id={getattr(guild, 'owner_id', None)}"},
        )
        return

    logging.warning(
        "Joined blocked guild; leaving immediately.",
        extra={"context": f" guild={guild.name} guild_id={guild.id} reason={blocked.get('reason', '')[:200]}"},
    )
    try:
        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(
            wolf_wrap(
                f"Blocked guild re-added me: {guild.name} (`{guild.id}`). Leaving again to honor the stored refusal."
            )
        )
    except Exception:
        pass
    try:
        await guild.leave()
    except Exception:
        logging.error("Failed to leave blocked guild after join.", exc_info=True, extra={"context": f" guild_id={guild.id}"})

@bot.event
async def on_command(ctx):
    logging.info(f"[CMD] {ctx.author} ({ctx.author.id}) used !{ctx.command}", extra={"context": f" guild={getattr(ctx.guild, 'name', 'DM')} channel={getattr(ctx.channel, 'id', None)} content={ctx.message.content[:1500]}"})

@bot.event
async def on_command_completion(ctx):
    logging.info(f"[CMD OK] !{ctx.command} completed for {ctx.author} ({ctx.author.id})", extra={"context": f" guild={getattr(ctx.guild, 'name', 'DM')} channel={getattr(ctx.channel, 'id', None)}"})

@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command: app_commands.Command):
    logging.info(f"[SLASH OK] /{command.name} completed for {interaction.user} ({interaction.user.id})", extra={"context": f" guild={getattr(interaction.guild, 'name', 'DM')} channel={getattr(interaction.channel, 'id', None)}"})

@bot.event
async def on_command_error(ctx, error):
    if hasattr(ctx.command, "on_error"):
        return
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        if check_already_responded(ctx):
            return
        logging.warning(f"[CMD DENIED] {ctx.author} ({ctx.author.id}) tried !{ctx.command} — check failed", extra={"context": f" guild={getattr(ctx.guild, 'name', 'DM')} channel={getattr(ctx.channel, 'id', None)} content={ctx.message.content[:1000]}"})
        await ctx.send(wolf_wrap("You don't have the authority to use that command."))
        return
    if isinstance(error, commands.MissingRequiredArgument):
        logging.warning(f"[CMD ARG] {ctx.author} missing arg `{error.param.name}` for !{ctx.command}", extra={"context": f" guild={getattr(ctx.guild, 'name', 'DM')} channel={getattr(ctx.channel, 'id', None)} content={ctx.message.content[:1000]}"})
        await ctx.send(wolf_wrap(f"Missing argument: `{error.param.name}`. Check your command usage."))
        return
    if isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions)):
        logging.warning(f"[CMD PERM] {ctx.author} missing permissions for !{ctx.command}", extra={"context": f" guild={getattr(ctx.guild, 'name', 'DM')} channel={getattr(ctx.channel, 'id', None)} content={ctx.message.content[:1000]}"})
        await ctx.send(wolf_wrap("You don't have the authority to use that command."))
        return
    if isinstance(error, commands.MemberNotFound):
        await ctx.send(wolf_wrap("Couldn't find that pack member."))
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(wolf_wrap(f"Invalid argument. Check your command usage."))
        return
    logging.error(f"[CMD ERR] !{ctx.command} by {ctx.author}: {error}", exc_info=True, extra={"context": f" guild={getattr(ctx.guild, 'name', 'DM')} channel={getattr(ctx.channel, 'id', None)} content={ctx.message.content[:1500]}"})
    await _notify_error(ctx, error, str(ctx.command), is_slash=False)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    cmd_name = interaction.command.name if interaction.command else "unknown"

    # Unwrap CommandInvokeError to get the real cause
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original

    # ── Handled errors — clean user message, no DM, no traceback ─────────────
    if isinstance(error, app_commands.MissingPermissions):
        missing = ", ".join(error.missing_permissions)
        logging.warning(f"[SLASH DENIED] {interaction.user} missing perms for /{cmd_name}: {missing}", extra={"context": f" guild={getattr(interaction.guild, 'name', 'DM')} channel={getattr(interaction.channel, 'id', None)}"})
        try:
            await interaction.response.send_message(
                wolf_wrap(f"You're missing the required permissions: `{missing}`."), ephemeral=True
            )
        except Exception:
            await interaction.followup.send(wolf_wrap(f"You're missing the required permissions: `{missing}`."), ephemeral=True)
        return

    if isinstance(error, app_commands.BotMissingPermissions):
        missing = ", ".join(error.missing_permissions)
        logging.warning(f"[SLASH BOT PERM] Bot missing perms for /{cmd_name}: {missing}", extra={"context": f" guild={getattr(interaction.guild, 'name', 'DM')} channel={getattr(interaction.channel, 'id', None)}"})
        try:
            await interaction.response.send_message(
                wolf_wrap(f"I'm missing the required permissions: `{missing}`."), ephemeral=True
            )
        except Exception:
            await interaction.followup.send(wolf_wrap(f"I'm missing the required permissions: `{missing}`."), ephemeral=True)
        return

    if isinstance(error, app_commands.CheckFailure):
        if check_already_responded(interaction):
            return
        logging.warning(f"[SLASH DENIED] {interaction.user} ({interaction.user.id}) tried /{cmd_name} — check failed", extra={"context": f" guild={getattr(interaction.guild, 'name', 'DM')} channel={getattr(interaction.channel, 'id', None)}"})
        try:
            await interaction.response.send_message(
                wolf_wrap("You don't have the authority to use that command."), ephemeral=True
            )
        except Exception:
            await interaction.followup.send(wolf_wrap("You don't have the authority to use that command."), ephemeral=True)
        return

    if isinstance(error, app_commands.CommandOnCooldown):
        try:
            await interaction.response.send_message(
                wolf_wrap(f"Slow down. Try again in `{error.retry_after:.1f}s`."), ephemeral=True
            )
        except Exception:
            pass
        return

    # ── Unexpected errors — log + DM owner ────────────────────────────────────
    logging.error(f"[SLASH ERR] /{cmd_name} by {interaction.user} ({interaction.user.id}): {error}", exc_info=True, extra={"context": f" guild={getattr(interaction.guild, 'name', 'DM')} channel={getattr(interaction.channel, 'id', None)}"})
    await _notify_error(interaction, error, cmd_name, is_slash=True)

@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    synced = await bot.tree.sync()
    await ctx.send(wolf_wrap(f"Synced {len(synced)} slash commands."))

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    loop = asyncio.get_running_loop()
    startup_started = time.perf_counter()

    def _loop_exception_handler(loop, context):
        exc = context.get("exception")
        msg = context.get("message", "Unhandled asyncio exception")
        logging.error(msg, exc_info=(type(exc), exc, exc.__traceback__) if exc else False, extra={"context": f" asyncio_keys={list(context.keys())}"})

    loop.set_exception_handler(_loop_exception_handler)

    async with bot:
        load_started = time.perf_counter()
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog = f"cogs.{filename[:-3]}"
                try:
                    await bot.load_extension(cog)
                    logging.info(f"Loaded: {cog}")
                except Exception as e:
                    logging.error(f"Failed to load {cog}: {e}", exc_info=True, extra={"context": f" cog={cog}"})
        logging.info("Cog loading complete.", extra={"context": f" seconds={time.perf_counter() - load_started:.2f}"})
        bot.loop.create_task(_background_ai_schema_prep())
        logging.info("Boot handoff to Discord login.", extra={"context": f" seconds_since_main_start={time.perf_counter() - startup_started:.2f}"})
        try:
            await bot.start(config.TOKEN)
        except asyncio.CancelledError:
            pass
    if getattr(bot, "_nightpaw_restart_requested", False):
        logging.info("Restart requested; relaunching NightPaw.")
        os.execv(sys.executable, [sys.executable] + sys.argv)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🐺 NightPaw is going dark. Pack dismissed.")
