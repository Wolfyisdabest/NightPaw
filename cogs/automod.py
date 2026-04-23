from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
from datetime import timedelta, datetime, timezone
import config
from config import wolf_wrap

OWNER_ID = config.OWNER_ID

# ── Blocked words ─────────────────────────────────────────────────────────────
# Add or remove words here. All checked case-insensitively.
BLOCKED_WORDS = [
    "nigger", "nigga", "faggot", "fag", "tranny", "chink", "spic", "kike",
    "retard", "retarded", "cunt", "whore", "slut", "rape", "raping",
    "nonce", "pedo", "paedophile", "pedophile",
]

# ── Spam tracking ─────────────────────────────────────────────────────────────
# user_id -> list of message timestamps
SPAM_TRACKER: dict[int, list[datetime]] = {}
SPAM_THRESHOLD = 5       # messages
SPAM_WINDOW = 5          # seconds


from checks import user_is_trusted
from services.db import connect


async def _is_exempt(user_id: int) -> bool:
    return await user_is_trusted(user_id)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled: bool = True

    async def cog_load(self):
        async with connect() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS automod_strikes (
                    user_id INTEGER PRIMARY KEY,
                    strikes INTEGER DEFAULT 0
                )
            """)
            await db.commit()

    async def _get_strikes(self, user_id: int) -> int:
        async with connect() as db:
            async with db.execute("SELECT strikes FROM automod_strikes WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else 0

    async def _add_strike(self, user_id: int) -> int:
        async with connect() as db:
            await db.execute("""
                INSERT INTO automod_strikes (user_id, strikes) VALUES (?, 1)
                ON CONFLICT(user_id) DO UPDATE SET strikes = strikes + 1
            """, (user_id,))
            await db.commit()
            async with db.execute("SELECT strikes FROM automod_strikes WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else 1

    async def _clear_strikes(self, user_id: int):
        async with connect() as db:
            await db.execute("DELETE FROM automod_strikes WHERE user_id = ?", (user_id,))
            await db.commit()

    # ── Log helper ────────────────────────────────────────────────────────────

    async def _log(self, action: str, user: discord.Member, reason: str, channel: discord.TextChannel):
        if not config.AUTOMOD_LOG_CHANNEL_ID:
            return
        log_channel = self.bot.get_channel(config.AUTOMOD_LOG_CHANNEL_ID)
        if not log_channel:
            return
        embed = discord.Embed(
            title=f"🛡️ AutoMod — {action}",
            color=config.BOT_COLOR,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="User", value=f"<@{user.id}> (`{user}`)", inline=True)
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"ID: {user.id}")
        await log_channel.send(embed=embed)

    # ── Warn helper (uses moderation warn_db if available) ────────────────────

    async def _auto_warn(self, member: discord.Member, reason: str, channel: discord.TextChannel):
        mod_cog = self.bot.cogs.get("Moderation")
        if mod_cog:
            await mod_cog._add_warn(member.id, f"[AutoMod] {reason}", self.bot.user.id, "AutoMod")
            count = await mod_cog._warn_count(member.id)
            try:
                await channel.send(
                    wolf_wrap(f"<@{member.id}> — AutoMod warning ({count} total): {reason}"),
                    delete_after=8
                )
            except Exception:
                pass
        await self._log("Warning Issued", member, reason, channel)

    # ── Main listener ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.enabled:
            return
        # Ignore DMs, bots, and system messages
        if not message.guild or message.author.bot or message.type != discord.MessageType.default:
            return

        # Ignore exempt users
        if await _is_exempt(message.author.id):
            return

        content = message.content
        member = message.author
        channel = message.channel

        # Run all checks — first match wins and returns
        if await self._check_invite(message, content, member, channel):
            return
        if await self._check_mass_mention(message, content, member, channel):
            return
        if await self._check_blocked_words(message, content, member, channel):
            return
        if await self._check_spam(message, member, channel):
            return
        if await self._check_caps(message, content, member, channel):
            return
        if await self._check_repeated_chars(message, content, member, channel):
            return

    # ── Check: Discord invite links ───────────────────────────────────────────

    async def _check_invite(self, message, content, member, channel) -> bool:
        invite_pattern = re.compile(
            r"(discord\.gg|discord\.com/invite|discordapp\.com/invite)/[\w-]+",
            re.IGNORECASE
        )
        if invite_pattern.search(content):
            try:
                await message.delete()
            except Exception:
                pass
            await self._auto_warn(member, "Posting Discord invite links is not allowed.", channel)
            return True
        return False

    # ── Check: Mass mentions ──────────────────────────────────────────────────

    async def _check_mass_mention(self, message, content, member, channel) -> bool:
        # @everyone/@here OR 4+ individual mentions
        has_everyone = message.mention_everyone
        mention_count = len(message.mentions) + len(message.role_mentions)

        if has_everyone or mention_count >= 4:
            try:
                await message.delete()
            except Exception:
                pass
            reason = "@everyone/@here abuse" if has_everyone else f"Mass mention ({mention_count} mentions)"
            try:
                await member.timeout(timedelta(minutes=5), reason=f"[AutoMod] {reason}")
                await channel.send(
                    wolf_wrap(f"<@{member.id}> has been silenced for 5 minutes. Reason: {reason}"),
                    delete_after=10
                )
            except Exception:
                pass
            await self._log("Timeout (5 min)", member, reason, channel)
            return True
        return False

    # ── Check: Blocked words ──────────────────────────────────────────────────

    async def _check_blocked_words(self, message, content, member, channel) -> bool:
        content_lower = content.lower()
        for word in BLOCKED_WORDS:
            # Word boundary check to avoid false positives
            if re.search(rf"\b{re.escape(word)}\b", content_lower):
                try:
                    await message.delete()
                except Exception:
                    pass

                strikes = await self._add_strike(member.id)

                await self._auto_warn(member, f"Blocked word used.", channel)

                # Timeout on second+ offence
                if strikes >= 2:
                    try:
                        await member.timeout(timedelta(minutes=10), reason="[AutoMod] Repeated blocked word use")
                        await channel.send(
                            wolf_wrap(f"<@{member.id}> silenced for 10 minutes. Repeated blocked word use."),
                            delete_after=10
                        )
                        await self._log("Timeout (10 min)", member, "Repeated blocked word use", channel)
                    except Exception:
                        pass
                return True
        return False

    # ── Check: Spam ───────────────────────────────────────────────────────────

    async def _check_spam(self, message, member, channel) -> bool:
        uid = member.id
        now = datetime.now(timezone.utc)

        if uid not in SPAM_TRACKER:
            SPAM_TRACKER[uid] = []

        # Prune old timestamps outside the window
        SPAM_TRACKER[uid] = [
            t for t in SPAM_TRACKER[uid]
            if (now - t).total_seconds() < SPAM_WINDOW
        ]
        SPAM_TRACKER[uid].append(now)

        if len(SPAM_TRACKER[uid]) >= SPAM_THRESHOLD:
            SPAM_TRACKER[uid] = []  # Reset after triggering
            try:
                # Delete last 5 messages from this user in the channel
                def is_spammer(m):
                    return m.author == member

                await channel.purge(limit=10, check=is_spammer)
            except Exception:
                pass
            await self._auto_warn(member, "Sending messages too fast.", channel)
            return True
        return False

    # ── Check: Excessive caps ─────────────────────────────────────────────────

    async def _check_caps(self, message, content, member, channel) -> bool:
        # Only check messages longer than 8 chars
        letters = [c for c in content if c.isalpha()]
        if len(letters) < 8:
            return False
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio >= 0.75:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await channel.send(
                    wolf_wrap(f"<@{member.id}> — ease up on the caps."),
                    delete_after=6
                )
            except Exception:
                pass
            await self._log("Deleted (Excessive Caps)", member, f"{int(caps_ratio * 100)}% caps", channel)
            return True
        return False

    # ── Check: Repeated characters ────────────────────────────────────────────

    async def _check_repeated_chars(self, message, content, member, channel) -> bool:
        # 6+ of the same character in a row
        if re.search(r"(.)\1{5,}", content):
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await channel.send(
                    wolf_wrap(f"<@{member.id}> — keep it readable."),
                    delete_after=6
                )
            except Exception:
                pass
            await self._log("Deleted (Repeated Chars)", member, "Excessive repeated characters", channel)
            return True
        return False

    # ── Toggle commands ───────────────────────────────────────────────────────

    async def _announce_toggle(self, channel: discord.TextChannel, state: bool):
        embed = discord.Embed(
            title="🛡️ AutoMod " + ("Enabled" if state else "Disabled"),
            description=(
                "AutoMod is now **active**. The den is protected." if state
                else "AutoMod is now **disabled**. The pack watches manually."
            ),
            color=discord.Color.green() if state else discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="NightPaw AutoMod")
        await channel.send(embed=embed)

    @commands.command(name="automod", help="Toggle AutoMod on or off (Owner only)")
    @commands.check(lambda ctx: ctx.author.id == OWNER_ID)
    async def automod_toggle_prefix(self, ctx, state: str):
        state = state.lower()
        if state == "off":
            self.enabled = False
            await ctx.send(wolf_wrap("AutoMod disabled."), delete_after=5)
            await self._announce_toggle(ctx.channel, False)
        elif state == "on":
            self.enabled = True
            await ctx.send(wolf_wrap("AutoMod enabled."), delete_after=5)
            await self._announce_toggle(ctx.channel, True)
        else:
            await ctx.send(wolf_wrap("Usage: `!automod on` or `!automod off`"))

    @app_commands.command(name="automod", description="Toggle AutoMod on or off (Owner only)", extras={"category": "owner"})
    @app_commands.check(lambda i: i.user.id == OWNER_ID)
    async def automod_toggle_slash(self, interaction: discord.Interaction, state: str, ephemeral: bool = False):
        state = state.lower()
        if state == "off":
            self.enabled = False
            await interaction.response.send_message(wolf_wrap("AutoMod disabled."), ephemeral=ephemeral)
            await self._announce_toggle(interaction.channel, False)
        elif state == "on":
            self.enabled = True
            await interaction.response.send_message(wolf_wrap("AutoMod enabled."), ephemeral=ephemeral)
            await self._announce_toggle(interaction.channel, True)
        else:
            await interaction.response.send_message(wolf_wrap("Usage: `on` or `off`"), ephemeral=ephemeral)

    # ── Test command ──────────────────────────────────────────────────────────

    @commands.command(name="automodtest", help="Test AutoMod is active (Owner only)")
    @commands.check(lambda ctx: ctx.author.id == OWNER_ID)
    async def automodtest_prefix(self, ctx):
        await ctx.send(embed=self._test_embed(), delete_after=15)

    @app_commands.command(name="automodtest", description="Test AutoMod is active (Owner only)", extras={"category": "owner"})
    @app_commands.check(lambda i: i.user.id == OWNER_ID)
    async def automodtest_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._test_embed(), ephemeral=ephemeral)

    def _test_embed(self) -> discord.Embed:
        status = "✅ Active" if self.enabled else "❌ Disabled"
        log_channel = self.bot.get_channel(config.AUTOMOD_LOG_CHANNEL_ID) if config.AUTOMOD_LOG_CHANNEL_ID else None
        embed = discord.Embed(title="🛡️ AutoMod Status", color=discord.Color.green() if self.enabled else discord.Color.red())
        embed.add_field(name="State", value=status, inline=True)
        embed.add_field(name="Log Channel", value=log_channel.mention if log_channel else "Not configured", inline=True)
        embed.add_field(
            name="Active Checks",
            value="Invite links, Mass mentions, Blocked words, Spam, Excessive caps, Repeated chars",
            inline=False
        )
        embed.add_field(name="Spam Threshold", value=f"{SPAM_THRESHOLD} messages / {SPAM_WINDOW}s", inline=True)
        embed.add_field(name="Blocked Words", value=str(len(BLOCKED_WORDS)), inline=True)
        embed.add_field(name="Exempt", value="Owner + Trusted users", inline=True)
        embed.set_footer(text="NightPaw AutoMod")
        return embed



async def setup(bot):
    await bot.add_cog(AutoMod(bot))
