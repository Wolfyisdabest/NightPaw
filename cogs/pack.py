from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config
from checks import is_owner, is_owner_slash, is_trusted, is_trusted_slash
from config import wolf_wrap
from services.trust_service import (
    add_trusted,
    clear_trusted,
    ensure_schema,
    list_trusted,
    remove_trusted,
)

BACKUP_PATH = Path("data/trust_backup.json")


class Pack(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_votes: dict = {}

    async def cog_load(self):
        await ensure_schema()

    async def _get_trusted(self):
        return await list_trusted()

    async def _add_trusted(self, user: discord.User | discord.Member, added_by: discord.User | discord.Member):
        inserted = await add_trusted(user, added_by)
        if not inserted:
            raise RuntimeError(f"User {user.id} is already trusted or could not be inserted.")

    async def _remove_trusted(self, user_id: int):
        await remove_trusted(user_id)

    async def _resolve_member(self, ctx, target: str) -> discord.Member | discord.User | None:
        import re as _re

        mention_match = _re.match(r"<@!?(\d+)>", target.strip())
        if mention_match:
            target = mention_match.group(1)

        if ctx.guild:
            try:
                converter = commands.MemberConverter()
                return await converter.convert(ctx, target)
            except commands.MemberNotFound:
                pass

            try:
                user_id = int(target.strip())
                return await ctx.guild.fetch_member(user_id)
            except (ValueError, discord.NotFound, discord.HTTPException):
                pass

        try:
            user_id = int(target.strip())
            return await ctx.bot.fetch_user(user_id)
        except (ValueError, discord.NotFound, discord.HTTPException):
            return None

    @commands.command(name="addtrust", aliases=["addpack"], help="Add a user to the trusted pack list (Owner only)")
    @is_owner()
    async def addtrust_prefix(self, ctx, *, target: str):
        member = await self._resolve_member(ctx, target)
        if member is None:
            await ctx.send(wolf_wrap("Couldn't find that pack member. Try a mention, username, or user ID."))
            return
        try:
            await self._add_trusted(member, ctx.author)
            await ctx.send(wolf_wrap(f"<@{member.id}> has been welcomed into the pack. The bond holds."))
        except RuntimeError:
            await ctx.send(wolf_wrap(f"<@{member.id}> is already part of the pack."))

    @app_commands.command(name="addtrust", description="Add a user to the trusted pack list (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def addtrust_slash(self, interaction: discord.Interaction, member: discord.Member, ephemeral: bool = False):
        try:
            await self._add_trusted(member, interaction.user)
            await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has been welcomed into the pack. The bond holds."), ephemeral=ephemeral)
        except RuntimeError:
            await interaction.response.send_message(wolf_wrap(f"<@{member.id}> is already part of the pack."), ephemeral=True)

    @commands.command(name="remtrust", aliases=["rempack"], help="Remove a user from the trusted pack list (Owner only)")
    @is_owner()
    async def remtrust_prefix(self, ctx, *, target: str):
        member = await self._resolve_member(ctx, target)
        if member is None:
            await ctx.send(wolf_wrap("Couldn't find that pack member. Try a mention, username, or user ID."))
            return
        await self._remove_trusted(member.id)
        await ctx.send(wolf_wrap(f"<@{member.id}> has been removed from the pack."))

    @app_commands.command(name="remtrust", description="Remove a user from the trusted pack list (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def remtrust_slash(self, interaction: discord.Interaction, member: discord.Member, ephemeral: bool = False):
        await self._remove_trusted(member.id)
        await interaction.response.send_message(wolf_wrap(f"<@{member.id}> has been removed from the pack."), ephemeral=ephemeral)

    @commands.command(name="trustlist", aliases=["pack"], help="Show list of trusted pack members")
    @is_trusted()
    async def trustlist_prefix(self, ctx):
        await ctx.send(embed=await self._trustlist_embed())

    @app_commands.command(name="trustlist", description="Show list of trusted pack members", extras={"category": "trusted"})
    @is_trusted_slash("Only pack members can use that command.")
    async def trustlist_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=await self._trustlist_embed(), ephemeral=ephemeral)

    async def _trustlist_embed(self) -> discord.Embed:
        trusted = await self._get_trusted()
        embed = discord.Embed(title="🐺 The Pack", color=config.BOT_COLOR)
        if not trusted:
            embed.description = "The pack list is empty. Trust is earned slowly."
        else:
            lines = "\n".join(
                f"<@{member.user_id}> — added by <@{member.added_by_id}>"
                for member in trusted
            )
            embed.description = lines
        embed.set_footer(text="Loyalty runs deep. Trust is non-optional.")
        return embed

    @commands.command(name="cleartrust", help="Clear all trusted users (Owner only)")
    @is_owner()
    async def cleartrust_prefix(self, ctx):
        await clear_trusted()
        await ctx.send(wolf_wrap("The pack list has been wiped. Trust rebuilds slowly."))

    @app_commands.command(name="cleartrust", description="Clear all trusted users (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def cleartrust_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await clear_trusted()
        await interaction.response.send_message(wolf_wrap("The pack list has been wiped. Trust rebuilds slowly."), ephemeral=ephemeral)

    @commands.command(name="backuptrust", help="Export the trusted user list (Owner only)")
    @is_owner()
    async def backuptrust_prefix(self, ctx):
        trusted = await self._get_trusted()
        BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        BACKUP_PATH.write_text(json.dumps([asdict(member) for member in trusted], indent=2), encoding="utf-8")
        await ctx.send(wolf_wrap("Pack list exported. Keep it safe."), file=discord.File(BACKUP_PATH))

    @app_commands.command(name="backuptrust", description="Export the trusted user list (Owner only)", extras={"category": "owner"})
    @is_owner_slash("Only the Alpha can use that command.")
    async def backuptrust_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        trusted = await self._get_trusted()
        BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        BACKUP_PATH.write_text(json.dumps([asdict(member) for member in trusted], indent=2), encoding="utf-8")
        await interaction.response.send_message(wolf_wrap("Pack list exported. Keep it safe."), file=discord.File(BACKUP_PATH), ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(Pack(bot))
