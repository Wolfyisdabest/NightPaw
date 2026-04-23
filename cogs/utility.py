from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
import time

import aiohttp
import discord
import ephem
from discord import app_commands
from discord.ext import commands

import config
from checks import is_owner, is_owner_slash
from config import wolf_wrap
from services.reminder_service import (
    create_reminder,
    delete_all_reminders,
    delete_reminder,
    delete_reminder_any,
    ensure_schema,
    list_all_reminders,
    list_reminders,
    reminder_belongs_to_user,
)

logger = logging.getLogger(__name__)


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_tasks: dict[int, asyncio.Task] = {}
        self._http_session: aiohttp.ClientSession | None = None
        self._geo_cache: dict[str, tuple[float, tuple[float | None, float | None, str | None]]] = {}

    async def cog_load(self):
        await ensure_schema()
        asyncio.create_task(self._restore_reminders())

    async def cog_unload(self):
        for task in self.reminder_tasks.values():
            task.cancel()
        self.reminder_tasks.clear()
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._http_session = aiohttp.ClientSession(timeout=timeout)
        return self._http_session

    async def _fetch_json(self, url: str) -> dict:
        session = await self._get_http_session()
        async with session.get(url) as resp:
            resp.raise_for_status()
            payload = await resp.json()
        return payload if isinstance(payload, dict) else {}

    def _format_duration(self, seconds: int) -> str:
        remaining = max(0, int(seconds))
        days, remaining = divmod(remaining, 86400)
        hours, remaining = divmod(remaining, 3600)
        minutes, seconds = divmod(remaining, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    def _schedule_reminder(self, reminder_id: int, user_id: int, channel_id: int | None, message: str, delay: float) -> None:
        existing = self.reminder_tasks.pop(reminder_id, None)
        if existing:
            existing.cancel()
        self.reminder_tasks[reminder_id] = asyncio.create_task(
            self._fire_reminder(reminder_id, user_id, channel_id, message, delay)
        )

    def _cancel_reminder_task(self, reminder_id: int) -> None:
        task = self.reminder_tasks.pop(reminder_id, None)
        if task:
            task.cancel()

    async def _restore_reminders(self):
        await self.bot.wait_until_ready()
        now = datetime.utcnow()
        reminders = await list_all_reminders()
        for reminder in reminders:
            try:
                fire_at = datetime.fromisoformat(reminder.fire_at)
                delay = max(0, (fire_at - now).total_seconds())
                self._schedule_reminder(reminder.id, reminder.user_id, reminder.channel_id, reminder.message, delay)
            except ValueError:
                await delete_reminder_any(reminder.id)
                logger.warning("Removed malformed reminder %s during startup restore.", reminder.id)

    async def _fire_reminder(self, rid: int, user_id: int, channel_id: int | None, message: str, delay: float):
        try:
            await asyncio.sleep(delay)
            deleted = await delete_reminder_any(rid)
            if not deleted:
                return

            if channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"🐺 <@{user_id}> — Reminder: *{message}*")
                    return

            user = await self.bot.fetch_user(user_id)
            await user.send(f"🐺 Reminder: *{message}*")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Failed to deliver reminder %s", rid, exc_info=True)
        finally:
            self.reminder_tasks.pop(rid, None)

    def _status_embed(self) -> discord.Embed:
        latency = round(self.bot.latency * 1000)
        guilds = len(self.bot.guilds)
        users = sum(g.member_count or 0 for g in self.bot.guilds)
        uptime = self._format_duration(int(time.time() - self.bot.launch_time)) if hasattr(self.bot, "launch_time") else "unavailable"
        embed = discord.Embed(title="🐺 NightPaw Status", color=config.BOT_COLOR)
        embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
        embed.add_field(name="Servers", value=str(guilds), inline=True)
        embed.add_field(name="Users", value=str(users), inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        embed.add_field(name="Commands", value=str(len(self.bot.commands)), inline=True)
        embed.add_field(name="Reminders", value=str(len(self.reminder_tasks)), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.set_footer(text="The pack is strong.")
        return embed

    @commands.command(name="status", help="Show bot stats and latency")
    async def status_prefix(self, ctx):
        await ctx.send(embed=self._status_embed())

    @app_commands.command(name="status", description="Show bot stats and latency", extras={"category": "general"})
    async def status_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._status_embed(), ephemeral=ephemeral)

    def _parse_time(self, time_str: str) -> int | None:
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        if not time_str:
            return None
        if time_str[-1] in units:
            try:
                value = int(time_str[:-1])
                if value <= 0:
                    return None
                return value * units[time_str[-1]]
            except ValueError:
                return None
        return None

    async def _create_reminder(self, user_id: int, channel_id: int | None, time_text: str, message: str) -> tuple[int, int] | None:
        seconds = self._parse_time(time_text)
        if seconds is None:
            return None
        fire_at = datetime.utcnow().replace(microsecond=0) + timedelta(seconds=seconds)
        reminder_id = await create_reminder(user_id, channel_id, message, fire_at.isoformat())
        self._schedule_reminder(reminder_id, user_id, channel_id, message, seconds)
        return reminder_id, seconds

    @commands.command(name="remind", help="Set a reminder (e.g. 10m, 2h) and a message")
    async def remind_prefix(self, ctx, time: str, *, message: str = "No message set."):
        created = await self._create_reminder(ctx.author.id, ctx.channel.id, time, message)
        if created is None:
            await ctx.send(wolf_wrap("Invalid time format. Use something like `10m`, `2h`, `30s`."))
            return
        reminder_id, seconds = created
        await ctx.send(
            wolf_wrap(
                f"Got it. Reminder `#{reminder_id}` is set for {self._format_duration(seconds)} from now: *{message}*"
            )
        )

    @app_commands.command(name="remind", description="Set a reminder (e.g. 10m, 2h) and a message", extras={"category": "general"})
    async def remind_slash(self, interaction: discord.Interaction, time: str, message: str = "No message set.", ephemeral: bool = False):
        channel_id = interaction.channel.id if interaction.channel else None
        created = await self._create_reminder(interaction.user.id, channel_id, time, message)
        if created is None:
            await interaction.response.send_message(
                wolf_wrap("Invalid time format. Use something like `10m`, `2h`, `30s`."),
                ephemeral=True,
            )
            return
        reminder_id, seconds = created
        await interaction.response.send_message(
            wolf_wrap(
                f"Got it. Reminder `#{reminder_id}` is set for {self._format_duration(seconds)} from now: *{message}*"
            ),
            ephemeral=ephemeral,
        )

    @commands.command(name="remindlist", help="Show your pending reminders")
    async def remindlist_prefix(self, ctx):
        await ctx.send(embed=await self._remindlist_embed(ctx.author.id))

    @app_commands.command(name="remindlist", description="Show your pending reminders", extras={"category": "general"})
    async def remindlist_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=await self._remindlist_embed(interaction.user.id), ephemeral=ephemeral)

    async def _remindlist_embed(self, user_id: int) -> discord.Embed:
        reminders = await list_reminders(user_id)
        embed = discord.Embed(title="⏰ Your Pending Reminders", color=config.BOT_COLOR)
        if not reminders:
            embed.description = "No pending reminders. The den is quiet."
        else:
            for reminder in reminders:
                try:
                    fire_at = datetime.fromisoformat(reminder.fire_at)
                    when = f"<t:{int(fire_at.timestamp())}:R> (`{fire_at.strftime('%Y-%m-%d %H:%M UTC')}`)"
                except ValueError:
                    when = f"`{reminder.fire_at} UTC`"
                embed.add_field(name=f"#{reminder.id} — {when}", value=f"*{reminder.message}*", inline=False)
        embed.set_footer(text=f"{len(reminders)} reminder(s) pending.")
        return embed

    @commands.command(name="remindclear", help="Clear a reminder by ID or all your reminders")
    async def remindclear_prefix(self, ctx, rid: str = "all"):
        await ctx.send(wolf_wrap(await self._remindclear(ctx.author.id, rid)))

    @app_commands.command(name="remindclear", description="Clear a reminder by ID or all your reminders", extras={"category": "general"})
    async def remindclear_slash(self, interaction: discord.Interaction, rid: str = "all", ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(await self._remindclear(interaction.user.id, rid)), ephemeral=ephemeral)

    async def _remindclear(self, user_id: int, rid: str) -> str:
        if rid.lower() == "all":
            reminders = await list_reminders(user_id)
            removed = await delete_all_reminders(user_id)
            for reminder in reminders:
                self._cancel_reminder_task(reminder.id)
            return "All your reminders have been cleared." if removed else "You had no reminders to clear."

        try:
            rid_int = int(rid)
        except ValueError:
            return "Invalid ID. Use a number or `all`."

        if not await reminder_belongs_to_user(rid_int, user_id):
            return f"Reminder #{rid_int} not found or doesn't belong to you."

        deleted = await delete_reminder(rid_int, user_id)
        if deleted:
            self._cancel_reminder_task(rid_int)
            return f"Reminder #{rid_int} cleared."
        return f"Reminder #{rid_int} not found or doesn't belong to you."

    async def _get_weather(self, city: str) -> discord.Embed:
        lat, lon, name = await self._get_coords(city)
        if lat is None or lon is None or name is None:
            return discord.Embed(description=wolf_wrap(f"Couldn't find {city} on the map."), color=config.BOT_COLOR)
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,apparent_temperature,weathercode,"
            f"windspeed_10m,relativehumidity_2m,precipitation"
            f"&wind_speed_unit=ms"
        )
        try:
            data = await self._fetch_json(weather_url)
            current = data["current"]
        except Exception:
            logger.warning("Weather lookup failed for %s", city, exc_info=True)
            return discord.Embed(description=wolf_wrap(f"Weather data for {city} is unavailable right now."), color=config.BOT_COLOR)
        condition, emoji = self._weather_code(current["weathercode"])
        embed = discord.Embed(title=f"{emoji} Weather in {name}", color=config.BOT_COLOR)
        embed.add_field(name="🌡️ Temperature", value=f"{current['temperature_2m']}°C (feels like {current['apparent_temperature']}°C)", inline=True)
        embed.add_field(name="💨 Wind", value=f"{current['windspeed_10m']} m/s", inline=True)
        embed.add_field(name="💧 Humidity", value=f"{current['relativehumidity_2m']}%", inline=True)
        embed.add_field(name="🌧️ Precipitation", value=f"{current['precipitation']}mm", inline=True)
        embed.add_field(name="🌤️ Condition", value=condition, inline=True)
        embed.set_footer(text="Data from Open-Meteo • The pack watches the skies.")
        return embed

    def _weather_code(self, code: int) -> tuple[str, str]:
        codes = {
            0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"),
            2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁️"),
            45: ("Foggy", "🌫️"), 48: ("Icy fog", "🌫️"),
            51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"),
            61: ("Light rain", "🌧️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
            71: ("Light snow", "🌨️"), 73: ("Snow", "❄️"), 75: ("Heavy snow", "❄️"),
            80: ("Rain showers", "🌦️"), 81: ("Heavy showers", "🌧️"),
            95: ("Thunderstorm", "⛈️"), 99: ("Hail storm", "⛈️"),
        }
        return codes.get(code, ("Unknown", "🌡️"))

    @commands.command(name="weather", help="Get local weather info")
    async def weather_prefix(self, ctx, *, city: str = "Venlo"):
        embed = await self._get_weather(city)
        await ctx.send(embed=embed)

    @app_commands.command(name="weather", description="Get local weather info", extras={"category": "general"})
    async def weather_slash(self, interaction: discord.Interaction, city: str = "Venlo", ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        embed = await self._get_weather(city)
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    def _moon_phase_name(self, phase: float) -> tuple[str, str]:
        if phase < 1:
            return "New Moon", "🌑"
        elif phase < 25:
            return "Waxing Crescent", "🌒"
        elif phase < 50:
            return "First Quarter", "🌓"
        elif phase < 75:
            return "Waxing Gibbous", "🌔"
        elif phase < 99:
            return "Waning Gibbous", "🌖"
        else:
            return "Full Moon", "🌕"

    async def _get_coords(self, city: str):
        key = " ".join((city or "").strip().casefold().split())
        cached = self._geo_cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < 900:
            return cached[1]

        try:
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1"
            geo = await self._fetch_json(url)
        except Exception:
            logger.warning("Geocoding lookup failed for %s", city, exc_info=True)
            result = (None, None, None)
            self._geo_cache[key] = (now, result)
            return result
        if not geo.get("results"):
            result = (None, None, None)
            self._geo_cache[key] = (now, result)
            return result
        match = geo["results"][0]
        country = str(match.get("country", "")).strip()
        name = str(match.get("name", city)).strip()
        display = f"{name}, {country}" if country else name
        result = (match["latitude"], match["longitude"], display)
        self._geo_cache[key] = (now, result)
        return result

    def _moon_embed(self) -> discord.Embed:
        moon = ephem.Moon()
        moon.compute(datetime.utcnow())
        phase = moon.phase
        phase_name, emoji = self._moon_phase_name(phase)
        embed = discord.Embed(title=f"{emoji} Current Moon Phase", color=config.BOT_COLOR)
        embed.add_field(name="Phase", value=phase_name, inline=True)
        embed.add_field(name="Illumination", value=f"{phase:.1f}%", inline=True)
        embed.set_footer(text="The moon guides the pack.")
        return embed

    @commands.command(name="moonphase", help="Show the current moon phase")
    async def moonphase_prefix(self, ctx):
        await ctx.send(embed=self._moon_embed())

    @app_commands.command(name="moonphase", description="Show the current moon phase", extras={"category": "general"})
    async def moonphase_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await interaction.followup.send(embed=self._moon_embed(), ephemeral=ephemeral)

    async def _moonrise_embed(self, city: str) -> discord.Embed:
        lat, lon, name = await self._get_coords(city)
        if lat is None:
            return discord.Embed(description=wolf_wrap(f"Couldn't find {city}."), color=config.BOT_COLOR)
        observer = ephem.Observer()
        observer.lat, observer.lon = str(lat), str(lon)
        observer.date = ephem.now()
        try:
            time_str = observer.next_rising(ephem.Moon()).datetime().strftime("%Y-%m-%d %H:%M UTC")
        except ephem.NeverUpError:
            time_str = "Moon never rises at this location tonight"
        except ephem.AlwaysUpError:
            time_str = "Moon is always up at this location"
        except Exception as exc:
            time_str = f"Calculation failed: {exc}"
        embed = discord.Embed(title=f"🌕 Next Moonrise — {name}", color=config.BOT_COLOR)
        embed.add_field(name="Time", value=time_str)
        embed.set_footer(text="The moon calls the pack.")
        return embed

    @commands.command(name="moonrise", help="Show next moonrise time")
    async def moonrise_prefix(self, ctx, *, city: str = "Venlo"):
        await ctx.send(embed=await self._moonrise_embed(city))

    @app_commands.command(name="moonrise", description="Show next moonrise time", extras={"category": "general"})
    async def moonrise_slash(self, interaction: discord.Interaction, city: str = "Venlo", ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await interaction.followup.send(embed=await self._moonrise_embed(city), ephemeral=ephemeral)

    async def _moonset_embed(self, city: str) -> discord.Embed:
        lat, lon, name = await self._get_coords(city)
        if lat is None:
            return discord.Embed(description=wolf_wrap(f"Couldn't find {city}."), color=config.BOT_COLOR)
        observer = ephem.Observer()
        observer.lat, observer.lon = str(lat), str(lon)
        observer.date = ephem.now()
        try:
            time_str = observer.next_setting(ephem.Moon()).datetime().strftime("%Y-%m-%d %H:%M UTC")
        except ephem.NeverUpError:
            time_str = "Moon never sets at this location tonight"
        except ephem.AlwaysUpError:
            time_str = "Moon is always up at this location"
        except Exception as exc:
            time_str = f"Calculation failed: {exc}"
        embed = discord.Embed(title=f"🌑 Next Moonset — {name}", color=config.BOT_COLOR)
        embed.add_field(name="Time", value=time_str)
        embed.set_footer(text="Rest now, the pack will watch.")
        return embed

    @commands.command(name="moonset", help="Show next moonset time")
    async def moonset_prefix(self, ctx, *, city: str = "Venlo"):
        await ctx.send(embed=await self._moonset_embed(city))

    @app_commands.command(name="moonset", description="Show next moonset time", extras={"category": "general"})
    async def moonset_slash(self, interaction: discord.Interaction, city: str = "Venlo", ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await interaction.followup.send(embed=await self._moonset_embed(city), ephemeral=ephemeral)

    @commands.command(name="echo", help="Echo your message (Owner only)")
    @is_owner()
    async def echo_prefix(self, ctx, *, message: str):
        await ctx.message.delete()
        await ctx.send(message)

    @app_commands.command(name="echo", description="Echo your message (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def echo_slash(self, interaction: discord.Interaction, message: str, ephemeral: bool = False):
        await interaction.response.send_message(message, ephemeral=ephemeral)

    @commands.command(name="say", help="Make the bot say something in an embed (Owner only)")
    @is_owner()
    async def say_prefix(self, ctx, *, message: str):
        await ctx.message.delete()
        embed = discord.Embed(description=message, color=config.BOT_COLOR)
        await ctx.send(embed=embed)

    @app_commands.command(name="say", description="Make the bot say something in an embed (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def say_slash(self, interaction: discord.Interaction, message: str, ephemeral: bool = False):
        embed = discord.Embed(description=message, color=config.BOT_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    @commands.command(name="reboot", aliases=["restart"], help="Restart the bot (Owner only)")
    @is_owner()
    async def reboot_prefix(self, ctx):
        await ctx.send(wolf_wrap("The pack is regrouping... brb."))
        shutdown = getattr(self.bot, "_nightpaw_fast_shutdown", None)
        if shutdown is not None:
            await shutdown(restart=True)
            return
        self.bot._nightpaw_restart_requested = True
        await self.bot.close()

    @app_commands.command(name="restart", description="Restart the bot (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def restart_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap("The pack is regrouping... brb."), ephemeral=ephemeral)
        shutdown = getattr(self.bot, "_nightpaw_fast_shutdown", None)
        if shutdown is not None:
            await shutdown(restart=True)
            return
        self.bot._nightpaw_restart_requested = True
        await self.bot.close()

    @commands.command(name="stop", aliases=["shutdown"], help="Stop the bot cleanly (Owner only)")
    @is_owner()
    async def stop_prefix(self, ctx):
        await ctx.send(wolf_wrap("Going dark. Pack dismissed."))
        shutdown = getattr(self.bot, "_nightpaw_fast_shutdown", None)
        if shutdown is not None:
            await shutdown(restart=False)
            return
        self.bot._nightpaw_restart_requested = False
        await self.bot.close()

    @app_commands.command(name="stop", description="Stop the bot cleanly (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def stop_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap("Going dark. Pack dismissed."), ephemeral=ephemeral)
        shutdown = getattr(self.bot, "_nightpaw_fast_shutdown", None)
        if shutdown is not None:
            await shutdown(restart=False)
            return
        self.bot._nightpaw_restart_requested = False
        await self.bot.close()


async def setup(bot):
    await bot.add_cog(Utility(bot))
