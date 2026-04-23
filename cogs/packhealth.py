from __future__ import annotations

import os
import time
import platform
import math

import discord
import psutil
from discord import app_commands
from discord.ext import commands

import config
from checks import is_owner_or_trusted_dm, is_owner_or_trusted_dm_slash, is_owner_or_trusted_slash
from services.db import connect, DB_PATH

START_TIME = time.time()


class PackHealth(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _latency_text(self) -> str:
        latency = getattr(self.bot, "latency", float("nan"))
        if isinstance(latency, float) and math.isnan(latency):
            return "unavailable"
        return f"{round(latency * 1000)}ms"

    async def _build_health_embed(self) -> discord.Embed:
        uptime_seconds = int(time.time() - START_TIME)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

        warn_count = 0
        reminder_count = 0
        trusted_count = 0
        strike_count = 0
        try:
            async with connect() as db:
                async with db.execute("SELECT COUNT(*) FROM warnings") as c:
                    warn_count = (await c.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM reminders") as c:
                    reminder_count = (await c.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM trusted") as c:
                    trusted_count = (await c.fetchone())[0]
                async with db.execute("SELECT COALESCE(SUM(strikes), 0) FROM automod_strikes") as c:
                    strike_count = (await c.fetchone())[0]
        except Exception:
            pass

        automod_cog = self.bot.cogs.get("AutoMod")
        automod_status = "✅ Active" if (automod_cog and automod_cog.enabled) else "❌ Disabled"
        ai_cog = self.bot.cogs.get("AI")
        ai_diag = ai_cog.service.get_last_run_info() if ai_cog and hasattr(ai_cog, "service") else {}

        proc = psutil.Process(os.getpid())
        cpu = proc.cpu_percent(interval=0.3)
        mem = proc.memory_info().rss / 1024 / 1024
        log_path = getattr(config, "BOT_LOG_FILE", "nightpaw.log")
        log_size_mb = 0.0
        try:
            if os.path.exists(log_path):
                log_size_mb = os.path.getsize(log_path) / 1024 / 1024
        except OSError:
            log_size_mb = 0.0

        guild = self.bot.guilds[0] if self.bot.guilds else None
        bot_member = guild.me if guild else None
        activity_str = "None"
        status_str = "Unknown"
        if bot_member:
            status_str = str(bot_member.status).capitalize()
            if bot_member.activity:
                act = bot_member.activity
                activity_str = f"{str(act.type).split('.')[-1].capitalize()} {act.name}"

        embed = discord.Embed(title="🐺 NightPaw — Pack Health", color=config.BOT_COLOR)
        embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)
        embed.add_field(name="📡 Latency", value=self._latency_text(), inline=True)
        embed.add_field(name="🧩 Cogs Loaded", value=str(len(self.bot.cogs)), inline=True)
        embed.add_field(name="🌐 Status", value=status_str, inline=True)
        embed.add_field(name="🎮 Activity", value=activity_str, inline=True)
        embed.add_field(name="🖥️ Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="⚠️ Total Warns", value=str(warn_count), inline=True)
        embed.add_field(name="⏰ Pending Reminders", value=str(reminder_count), inline=True)
        embed.add_field(name="🤝 Trusted Members", value=str(trusted_count), inline=True)
        embed.add_field(name="🛡️ AutoMod", value=automod_status, inline=True)
        embed.add_field(name="🔥 AutoMod Strikes", value=str(strike_count), inline=True)
        embed.add_field(name="​", value="​", inline=True)
        embed.add_field(name="🔧 Bot CPU", value=f"{cpu}%", inline=True)
        embed.add_field(name="💾 Bot RAM", value=f"{mem:.1f} MB", inline=True)
        embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)
        embed.add_field(name="🗃️ DB", value=DB_PATH.name, inline=True)
        embed.add_field(name="📝 Log File", value=f"{log_size_mb:.2f} MB", inline=True)
        embed.add_field(name="🤖 AI Model", value=getattr(config, "AI_MODEL", "unknown"), inline=True)
        embed.add_field(name="👁️ Vision Model", value=getattr(config, "AI_VISION_MODEL", "none") or "none", inline=True)
        route = str(ai_diag.get("route_used") or "idle")
        route_reason = str(ai_diag.get("route_reason") or "not used yet this session")
        planner = str(ai_diag.get("action_planner_used") or "none")
        confidence = str(ai_diag.get("action_confidence") or "none")
        memory_usage = f"stored={bool(ai_diag.get('memory_stored_this_turn'))}, loaded={ai_diag.get('memories_loaded_count', 0)}"
        last_age = "not used yet this session"
        ts = ai_diag.get("timestamp")
        if ts:
            try:
                age_seconds = max(0.0, time.time() - discord.utils.parse_time(str(ts)).timestamp())
                last_age = f"{int(age_seconds)}s ago"
            except Exception:
                last_age = "timestamp parse unavailable"
        embed.add_field(name="📎 Last AI Route", value=route, inline=True)
        embed.add_field(name="🧭 Last Reason", value=route_reason[:120], inline=True)
        embed.add_field(name="🧠 Planner", value=f"{planner} / {confidence}", inline=True)
        embed.add_field(name="🗂️ Memory Usage", value=memory_usage, inline=True)
        embed.add_field(name="🧯 Last Fallback", value=str(ai_diag.get("fallback_used") or "none"), inline=True)
        embed.add_field(name="🔍 Vision Prepass", value="Yes" if ai_diag.get("vision_prepass_used") else "No", inline=True)
        embed.add_field(name="💬 Last Chat Model", value=str(ai_diag.get("chat_model_used") or "none"), inline=True)
        embed.add_field(name="🕒 Last AI Turn", value=last_age, inline=True)
        embed.add_field(name="🧩 Runtime", value=str(ai_diag.get("runtime_sections_included") or "none")[:200], inline=False)
        embed.set_footer(text="🐺 Curiosity leads, loyalty follows, strength protects.")
        return embed

    @commands.command(name="packhealth", help="Show full bot health status (Owner/Trusted DM only)")
    @is_owner_or_trusted_dm()
    async def packhealth_prefix(self, ctx):
        await ctx.send(embed=await self._build_health_embed())

    @app_commands.command(name="packhealth", description="Show full bot health status (Owner/Trusted only)", extras={"category": "trusted"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_or_trusted_slash()
    async def packhealth_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await interaction.followup.send(embed=await self._build_health_embed(), ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(PackHealth(bot))
