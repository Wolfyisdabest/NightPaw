from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from config import wolf_wrap
from services.warning_service import (
    add_warning,
    clear_warnings,
    count_warnings,
    ensure_schema,
    get_warnings,
)

logger = logging.getLogger(__name__)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_schema()

    async def _mod_log(
        self,
        action: str,
        mod: discord.Member | discord.User,
        target: discord.Member | discord.User,
        reason: str,
        guild: discord.Guild | None = None,
    ) -> None:
        channel_id = config.MOD_LOG_CHANNEL_ID
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        embed = discord.Embed(
            title=f"🛡️ {action}",
            color=config.BOT_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Target", value=f"<@{target.id}> (`{target}`)", inline=True)
        embed.add_field(name="Moderator", value=f"<@{mod.id}> (`{mod}`)", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        if guild:
            embed.set_footer(text=f"Server: {guild.name}")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.warning("Failed to send moderation log for action %s", action, exc_info=True)

    def _target_block_reason(
        self,
        moderator: discord.Member,
        target: discord.Member,
        *,
        action: str,
    ) -> str | None:
        if target.id == moderator.id:
            return f"You can't {action} yourself."
        if target.id == self.bot.user.id:
            return f"You can't {action} me."
        if target == target.guild.owner:
            return f"You can't {action} the server owner."
        if moderator != target.guild.owner and target.top_role >= moderator.top_role:
            return f"You can't {action} someone with an equal or higher role."
        me = target.guild.me
        if me and target.top_role >= me.top_role:
            return f"I can't {action} someone with an equal or higher role than mine."
        return None

    async def _maybe_send_prefix_denial(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        action: str,
    ) -> bool:
        reason = self._target_block_reason(ctx.author, member, action=action)
        if reason:
            await ctx.send(wolf_wrap(reason))
            return True
        return False

    async def _maybe_send_slash_denial(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        *,
        action: str,
    ) -> bool:
        reason = self._target_block_reason(interaction.user, member, action=action)
        if reason:
            await interaction.response.send_message(wolf_wrap(reason), ephemeral=True)
            return True
        return False

    @staticmethod
    def _match_ban(entry: discord.guild.BanEntry, username: str) -> bool:
        needle = username.casefold()
        return entry.user.name.casefold() == needle or str(entry.user).casefold() == needle

    def _userinfo_embed(self, member: discord.Member) -> discord.Embed:
        color = member.top_role.color if member.top_role.color.value else config.BOT_COLOR
        embed = discord.Embed(title=f"👤 {member.display_name}", color=color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Username", value=str(member), inline=True)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "Unknown", inline=True)
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:10]) + ("..." if len(roles) > 10 else "") if roles else "None", inline=False)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=True)
        embed.set_footer(text=f"Requested from the den • {member.id}")
        return embed

    @commands.command(name="kick", help="Kick a member from the server")
    @commands.has_permissions(kick_members=True)
    async def kick_prefix(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if await self._maybe_send_prefix_denial(ctx, member, action="kick"):
            return
        await member.kick(reason=reason)
        await self._mod_log("Kick", ctx.author, member, reason, ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}> has been driven from the pack. Reason: {reason}"))

    @app_commands.command(name="kick", description="Kick a member from the server", extras={"category": "admin"})
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", ephemeral: bool = False):
        if await self._maybe_send_slash_denial(interaction, member, action="kick"):
            return
        await member.kick(reason=reason)
        await self._mod_log("Kick", interaction.user, member, reason, interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has been driven from the pack. Reason: {reason}"), ephemeral=ephemeral)

    @commands.command(name="ban", help="Ban a member from the server")
    @commands.has_permissions(ban_members=True)
    async def ban_prefix(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if await self._maybe_send_prefix_denial(ctx, member, action="ban"):
            return
        await member.ban(reason=reason)
        await self._mod_log("Ban", ctx.author, member, reason, ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}> has been exiled from the pack permanently. Reason: {reason}"))

    @app_commands.command(name="ban", description="Ban a member from the server", extras={"category": "admin"})
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", ephemeral: bool = False):
        if await self._maybe_send_slash_denial(interaction, member, action="ban"):
            return
        await member.ban(reason=reason)
        await self._mod_log("Ban", interaction.user, member, reason, interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has been exiled from the pack permanently. Reason: {reason}"), ephemeral=ephemeral)

    @commands.command(name="unban", help="Unban a user by their username or full tag")
    @commands.has_permissions(ban_members=True)
    async def unban_prefix(self, ctx, *, username: str):
        bans = [entry async for entry in ctx.guild.bans()]
        for entry in bans:
            if self._match_ban(entry, username):
                await ctx.guild.unban(entry.user)
                await self._mod_log("Unban", ctx.author, entry.user, "Manual unban", ctx.guild)
                await ctx.send(wolf_wrap(f"<@{entry.user.id}> has been welcomed back to the pack."))
                return
        await ctx.send(wolf_wrap(f"Couldn't find `{username}` in the exile list."))

    @app_commands.command(name="unban", description="Unban a user by their username or full tag", extras={"category": "admin"})
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_slash(self, interaction: discord.Interaction, username: str, ephemeral: bool = False):
        bans = [entry async for entry in interaction.guild.bans()]
        for entry in bans:
            if self._match_ban(entry, username):
                await interaction.guild.unban(entry.user)
                await self._mod_log("Unban", interaction.user, entry.user, "Manual unban", interaction.guild)
                await interaction.response.send_message(wolf_wrap(f"<@{entry.user.id}> has been welcomed back to the pack."), ephemeral=ephemeral)
                return
        await interaction.response.send_message(wolf_wrap(f"Couldn't find `{username}` in the exile list."), ephemeral=ephemeral)

    @commands.command(name="timeout", help="Timeout a member for a set number of minutes")
    @commands.has_permissions(moderate_members=True)
    async def timeout_prefix(self, ctx, member: discord.Member, minutes: int, *, reason: str = "No reason provided"):
        if minutes <= 0:
            await ctx.send(wolf_wrap("Timeout duration must be more than 0 minutes."))
            return
        if await self._maybe_send_prefix_denial(ctx, member, action="timeout"):
            return
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await self._mod_log("Timeout", ctx.author, member, f"{minutes} minute(s) • {reason}", ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}> has been silenced for {minutes} minute(s). Reason: {reason}"))

    @app_commands.command(name="timeout", description="Timeout a member for a set number of minutes", extras={"category": "admin"})
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_slash(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided", ephemeral: bool = False):
        if minutes <= 0:
            await interaction.response.send_message(wolf_wrap("Timeout duration must be more than 0 minutes."), ephemeral=True)
            return
        if await self._maybe_send_slash_denial(interaction, member, action="timeout"):
            return
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await self._mod_log("Timeout", interaction.user, member, f"{minutes} minute(s) • {reason}", interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has been silenced for {minutes} minute(s). Reason: {reason}"), ephemeral=ephemeral)

    @commands.command(name="untimeout", help="Remove a timeout from a member")
    @commands.has_permissions(moderate_members=True)
    async def untimeout_prefix(self, ctx, member: discord.Member):
        if await self._maybe_send_prefix_denial(ctx, member, action="untimeout"):
            return
        await member.timeout(None)
        await self._mod_log("Untimeout", ctx.author, member, "Timeout removed", ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}>'s silence has been lifted."))

    @app_commands.command(name="untimeout", description="Remove a timeout from a member", extras={"category": "admin"})
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout_slash(self, interaction: discord.Interaction, member: discord.Member, ephemeral: bool = False):
        if await self._maybe_send_slash_denial(interaction, member, action="untimeout"):
            return
        await member.timeout(None)
        await self._mod_log("Untimeout", interaction.user, member, "Timeout removed", interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}>'s silence has been lifted."), ephemeral=ephemeral)

    @commands.command(name="warn", help="Warn a member")
    @commands.has_permissions(manage_messages=True)
    async def warn_prefix(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if await self._maybe_send_prefix_denial(ctx, member, action="warn"):
            return
        await add_warning(member.id, reason, ctx.author.id, str(ctx.author))
        count = await count_warnings(member.id)
        await self._mod_log("Warn", ctx.author, member, reason, ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}> has been warned. ({count} warning(s) total) Reason: {reason}"))

    @app_commands.command(name="warn", description="Warn a member", extras={"category": "admin"})
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", ephemeral: bool = False):
        if await self._maybe_send_slash_denial(interaction, member, action="warn"):
            return
        await add_warning(member.id, reason, interaction.user.id, str(interaction.user))
        count = await count_warnings(member.id)
        await self._mod_log("Warn", interaction.user, member, reason, interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has been warned. ({count} warning(s) total) Reason: {reason}"), ephemeral=ephemeral)

    @commands.command(name="warnings", help="View warnings for a member")
    @commands.has_permissions(manage_messages=True)
    async def warnings_prefix(self, ctx, member: discord.Member):
        warns = await get_warnings(member.id)
        if not warns:
            await ctx.send(wolf_wrap(f"<@{member.id}> has a clean record."))
            return
        embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", color=config.BOT_COLOR)
        for i, warning in enumerate(warns, 1):
            embed.add_field(
                name=f"Warning {i} — {warning.timestamp}",
                value=f"Reason: {warning.reason}\nIssued by: <@{warning.mod_id}> ({warning.mod_name})",
                inline=False,
            )
        await ctx.send(embed=embed)

    @app_commands.command(name="warnings", description="View warnings for a member", extras={"category": "admin"})
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warnings_slash(self, interaction: discord.Interaction, member: discord.Member, ephemeral: bool = False):
        warns = await get_warnings(member.id)
        if not warns:
            await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has a clean record."), ephemeral=ephemeral)
            return
        embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", color=config.BOT_COLOR)
        for i, warning in enumerate(warns, 1):
            embed.add_field(
                name=f"Warning {i} — {warning.timestamp}",
                value=f"Reason: {warning.reason}\nIssued by: <@{warning.mod_id}> ({warning.mod_name})",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    @commands.command(name="clearwarnings", help="Clear all warnings for a member")
    @commands.has_permissions(administrator=True)
    async def clearwarnings_prefix(self, ctx, member: discord.Member):
        removed = await clear_warnings(member.id)
        await self._mod_log("Clear Warnings", ctx.author, member, f"Removed {removed} warning(s)", ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}>'s record has been wiped clean."))

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member", extras={"category": "admin"})
    @app_commands.checks.has_permissions(administrator=True)
    async def clearwarnings_slash(self, interaction: discord.Interaction, member: discord.Member, ephemeral: bool = False):
        removed = await clear_warnings(member.id)
        await self._mod_log("Clear Warnings", interaction.user, member, f"Removed {removed} warning(s)", interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}>'s record has been wiped clean."), ephemeral=ephemeral)

    @commands.command(name="purge", help="Delete a number of messages from this channel")
    @commands.has_permissions(manage_messages=True)
    async def purge_prefix(self, ctx, amount: int):
        if amount <= 0:
            await ctx.send(wolf_wrap("Purge amount must be more than 0."))
            return
        deleted = await ctx.channel.purge(limit=amount + 1)
        deleted_count = len(deleted)
        if any(msg.id == ctx.message.id for msg in deleted):
            deleted_count = max(0, deleted_count - 1)
        await self._mod_log("Purge", ctx.author, ctx.author, f"Purged {deleted_count} message(s) in #{ctx.channel}", ctx.guild)
        msg = await ctx.send(wolf_wrap(f"Swept {deleted_count} message(s) from the den."))
        await asyncio.sleep(3)
        try:
            await msg.delete()
        except discord.NotFound:
            pass

    @app_commands.command(name="purge", description="Delete a number of messages from this channel", extras={"category": "admin"})
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_slash(self, interaction: discord.Interaction, amount: int, ephemeral: bool = False):
        if amount <= 0:
            await interaction.response.send_message(wolf_wrap("Purge amount must be more than 0."), ephemeral=True)
            return
        await interaction.response.send_message(wolf_wrap(f"Sweeping {amount} message(s)..."), ephemeral=ephemeral)
        deleted = await interaction.channel.purge(limit=amount)
        await self._mod_log("Purge", interaction.user, interaction.user, f"Purged {len(deleted)} message(s) in #{interaction.channel}", interaction.guild)

    @commands.command(name="addrole", help="Add a role to a member")
    @commands.has_permissions(manage_roles=True)
    async def addrole_prefix(self, ctx, member: discord.Member, role: discord.Role):
        if await self._maybe_send_prefix_denial(ctx, member, action="manage roles for"):
            return
        await member.add_roles(role)
        await self._mod_log("Add Role", ctx.author, member, f"Granted role: {role.name}", ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}> has been granted the **{role.name}** role."))

    @app_commands.command(name="addrole", description="Add a role to a member", extras={"category": "admin"})
    @app_commands.checks.has_permissions(manage_roles=True)
    async def addrole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role, ephemeral: bool = False):
        if await self._maybe_send_slash_denial(interaction, member, action="manage roles for"):
            return
        await member.add_roles(role)
        await self._mod_log("Add Role", interaction.user, member, f"Granted role: {role.name}", interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has been granted the **{role.name}** role."), ephemeral=ephemeral)

    @commands.command(name="removerole", help="Remove a role from a member")
    @commands.has_permissions(manage_roles=True)
    async def removerole_prefix(self, ctx, member: discord.Member, role: discord.Role):
        if await self._maybe_send_prefix_denial(ctx, member, action="manage roles for"):
            return
        await member.remove_roles(role)
        await self._mod_log("Remove Role", ctx.author, member, f"Removed role: {role.name}", ctx.guild)
        await ctx.send(wolf_wrap(f"<@{member.id}> has had the **{role.name}** role removed."))

    @app_commands.command(name="removerole", description="Remove a role from a member", extras={"category": "admin"})
    @app_commands.checks.has_permissions(manage_roles=True)
    async def removerole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role, ephemeral: bool = False):
        if await self._maybe_send_slash_denial(interaction, member, action="manage roles for"):
            return
        await member.remove_roles(role)
        await self._mod_log("Remove Role", interaction.user, member, f"Removed role: {role.name}", interaction.guild)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has had the **{role.name}** role removed."), ephemeral=ephemeral)

    @commands.command(name="userinfo", help="Show info about a user")
    @commands.has_permissions(manage_messages=True)
    async def userinfo_prefix(self, ctx, *, member: discord.Member | None = None):
        await ctx.send(embed=self._userinfo_embed(member or ctx.author))

    @app_commands.command(name="userinfo", description="Show info about a user", extras={"category": "admin"})
    @app_commands.checks.has_permissions(manage_messages=True)
    async def userinfo_slash(self, interaction: discord.Interaction, member: discord.Member | None = None, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._userinfo_embed(member or interaction.user), ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
