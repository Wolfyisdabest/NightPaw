from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from config import wolf_wrap
from services.trust_service import is_trusted_user


async def user_is_trusted(user_id: int) -> bool:
    return await is_trusted_user(user_id, config.OWNER_ID)


def is_owner(message: str | None = None):
    async def predicate(ctx: commands.Context) -> bool:
        allowed = ctx.author.id == config.OWNER_ID
        if not allowed and message:
            await ctx.send(wolf_wrap(message))
        return allowed
    return commands.check(predicate)


def is_owner_slash(message: str | None = None):
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != config.OWNER_ID:
            if message:
                await interaction.response.send_message(wolf_wrap(message), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def is_trusted(message: str | None = None):
    async def predicate(ctx: commands.Context) -> bool:
        allowed = await user_is_trusted(ctx.author.id)
        if not allowed and message:
            await ctx.send(wolf_wrap(message))
        return allowed
    return commands.check(predicate)


def is_trusted_slash(message: str | None = None):
    async def predicate(interaction: discord.Interaction) -> bool:
        trusted = await user_is_trusted(interaction.user.id)
        if not trusted and message:
            await interaction.response.send_message(wolf_wrap(message), ephemeral=True)
        return trusted
    return app_commands.check(predicate)


def is_owner_dm_only(message: str = "Sysadmin commands only work in my DMs."):
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id != config.OWNER_ID:
            return False
        if not isinstance(ctx.channel, discord.DMChannel):
            await ctx.send(wolf_wrap(message))
            return False
        return True
    return commands.check(predicate)


def is_owner_dm_slash(message: str = "Sysadmin commands only work in my DMs."):
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != config.OWNER_ID:
            return False
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(wolf_wrap(message), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def is_owner_or_trusted_dm(message: str = "Pack health commands only work in my DMs."):
    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.channel, discord.DMChannel):
            await ctx.send(wolf_wrap(message))
            return False
        if not await user_is_trusted(ctx.author.id):
            await ctx.send(wolf_wrap("Only pack members can use that command."))
            return False
        return True
    return commands.check(predicate)


def is_owner_or_trusted_dm_slash(message: str = "Pack health commands only work in my DMs."):
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(wolf_wrap(message), ephemeral=True)
            return False
        trusted = await user_is_trusted(interaction.user.id)
        if not trusted:
            await interaction.response.send_message(wolf_wrap("Only pack members can use that command."), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def is_owner_or_trusted_slash(message: str = "Only pack members can use that command."):
    async def predicate(interaction: discord.Interaction) -> bool:
        trusted = await user_is_trusted(interaction.user.id)
        if not trusted:
            await interaction.response.send_message(wolf_wrap(message), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)
