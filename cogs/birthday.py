from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime, timezone
import config
from config import wolf_wrap

OWNER_ID = config.OWNER_ID
BIRTHDAY_MONTH = 3
BIRTHDAY_DAY = 21

BIRTHDAY_MESSAGES = [
    "🎂 The pack howls in celebration — the Alpha was born on this day!",
    "🐺 Another year, another ring on the great tree. The pack remembers.",
    "🌕 The moon shines a little brighter tonight. Happy birthday, Wolfy.",
    "🔥 The ember fire burns high tonight — the pack celebrates their own.",
    "❄️ Even the frost bows today. The Alpha walks another year stronger.",
    "🎉 AWOOOOOOOO! The whole forest knows — today belongs to you.",
    "🐾 Another year of tracking, hunting, and leading. The pack salutes you.",
    "👑 The diamond badge catches the light today. Curiosity led you here. Loyalty followed.",
]

class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._birthday_task = None

    async def cog_load(self):
        self._birthday_task = self.bot.loop.create_task(self._birthday_loop())

    async def cog_unload(self):
        if self._birthday_task:
            self._birthday_task.cancel()

    async def _birthday_loop(self):
        await self.bot.wait_until_ready()
        while True:
            now = datetime.now(timezone.utc)
            # Check if today is the birthday
            if now.month == BIRTHDAY_MONTH and now.day == BIRTHDAY_DAY:
                await self._send_birthday()
                # Sleep until next day to avoid re-triggering
                await asyncio.sleep(86400)
            else:
                # Sleep 1 hour and check again
                await asyncio.sleep(3600)

    async def _send_birthday(self):
        import random
        message = random.choice(BIRTHDAY_MESSAGES)
        embed = discord.Embed(
            title="🎂 Happy Birthday, Sander!",
            description=message,
            color=config.BOT_COLOR
        )
        embed.set_footer(text="🐺 From NightPaw and the whole pack.")

        # DM the owner
        try:
            owner = await self.bot.fetch_user(OWNER_ID)
            await owner.send(embed=embed)
        except Exception:
            pass

        # Post in birthday channel if configured
        if config.BIRTHDAY_CHANNEL_ID:
            try:
                channel = self.bot.get_channel(config.BIRTHDAY_CHANNEL_ID)
                if channel:
                    await channel.send(f"<@{OWNER_ID}>", embed=embed)
            except Exception:
                pass

    # ── Manual trigger ────────────────────────────────────────────────────────

    @commands.command(name="birthday", help="Trigger the birthday message (Owner only)")
    @commands.check(lambda ctx: ctx.author.id == OWNER_ID)
    async def birthday_prefix(self, ctx):
        await self._send_birthday()
        await ctx.send(wolf_wrap("Birthday howl sent! 🎂"), delete_after=5)

    @app_commands.command(name="birthday", description="Trigger the birthday message (Owner only)", extras={"category": "owner"})
    @app_commands.check(lambda i: i.user.id == OWNER_ID)
    async def birthday_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap("Birthday howl sent! 🎂"), ephemeral=ephemeral)
        await self._send_birthday()



async def setup(bot):
    await bot.add_cog(Birthday(bot))
