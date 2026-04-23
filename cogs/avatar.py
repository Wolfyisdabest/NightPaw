from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

import config


class Avatar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _asset_links(self, asset: discord.Asset | None) -> str | None:
        if asset is None:
            return None

        if asset.is_animated():
            formats = ["gif", "webp", "png"]
        else:
            formats = ["webp", "png", "jpg"]

        return " | ".join(
            f"[{fmt.upper()}]({asset.replace(format=fmt, size=1024).url})"
            for fmt in formats
        )

    def _avatar_embed(self, user: discord.User | discord.Member) -> discord.Embed:
        asset = user.display_avatar
        links = self._asset_links(asset)

        embed = discord.Embed(
            title=f"🐾 {user.display_name}'s Avatar",
            description=links,
            color=config.BOT_COLOR,
        )
        embed.set_image(url=asset.url)
        embed.set_footer(text=f"Requested from the den • {user.id}")
        return embed

    async def _fetch_full_user(self, user: discord.abc.User) -> discord.User | discord.Member:
        try:
            return await self.bot.fetch_user(user.id)
        except (discord.NotFound, discord.HTTPException):
            return user

    async def _profile_embed(self, user: discord.User | discord.Member) -> discord.Embed:
        full_user = await self._fetch_full_user(user)
        banner = getattr(full_user, "banner", None)

        # No banner? Fall straight back to the original avatar-only embed logic.
        if banner is None:
            return self._avatar_embed(user)

        avatar = user.display_avatar
        avatar_links = self._asset_links(avatar)
        banner_links = self._asset_links(banner)

        description_lines = []
        if avatar_links:
            description_lines.append(f"**Avatar:** {avatar_links}")
        if banner_links:
            description_lines.append(f"**Banner:** {banner_links}")

        embed = discord.Embed(
            title=f"🐾 {user.display_name}'s Avatar",
            description="\n".join(description_lines),
            color=config.BOT_COLOR,
        )
        embed.set_thumbnail(url=avatar.url)
        embed.set_image(url=banner.url)
        embed.set_footer(text=f"Requested from the den • {user.id}")
        return embed

    async def _resolve_user(self, ctx, target: str) -> discord.User | discord.Member | None:
        mention_match = re.match(r"<@!?(\d+)>", target.strip())
        if mention_match:
            target = mention_match.group(1)

        try:
            converter = commands.MemberConverter()
            return await converter.convert(ctx, target)
        except commands.MemberNotFound:
            pass

        try:
            user_id = int(target.strip())
            if ctx.guild:
                try:
                    return await ctx.guild.fetch_member(user_id)
                except discord.NotFound:
                    pass
            return await self.bot.fetch_user(user_id)
        except (ValueError, discord.NotFound, discord.HTTPException):
            pass

        return None

    @app_commands.command(
        name="avatar",
        description="Show the avatar and banner of a user or yourself",
        extras={"category": "general"},
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def avatar_slash(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
        ephemeral: bool = True,
    ):
        target = user or interaction.user
        await interaction.response.defer(ephemeral=ephemeral)
        embed = await self._profile_embed(target)
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    @commands.command(name="avatar", help="Show the avatar and banner of a user or yourself")
    async def avatar_prefix(self, ctx, *, target: str | None = None):
        if target is None:
            await ctx.send(embed=await self._profile_embed(ctx.author))
            return

        user = await self._resolve_user(ctx, target)
        if user is None:
            await ctx.send("🐺 *Couldn't find that pack member. Try a mention, username, or user ID.*")
            return

        await ctx.send(embed=await self._profile_embed(user))


async def setup(bot):
    await bot.add_cog(Avatar(bot))
