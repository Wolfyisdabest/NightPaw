from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import random
import config
from config import wolf_wrap

MATTHIJS_ID = 1085272077956829214

MATTHIJS_LORE = [
    "🌕 He texts in all caps sometimes. Not aggression — just enthusiasm with no volume control.",
    "🐺 Looks up to Wolfy. Doesn't always say it. Doesn't need to.",
    "⚡ Reactive first, thoughtful second. He's working on the order. Progress is being made.",
    "🎮 He'll ask to play without knowing what he wants to play. 'Everything' is a valid answer in his mind.",
    "🌿 Still figuring things out. That's not a flaw — that's just where he is.",
    "🤝 Loyal despite the chaos. The chaos is part of the package.",
    "👁️ He pinged once too many times. He was told. He learned. Mostly.",
    "🌑 Protective in his own way — not calculated, just instinctive.",
    "🎵 He shares music. Not all of it lands. He keeps sharing anyway.",
    "🔥 One Piece is cool. He will tell you this unprompted.",
    "🌕 The yellow wolf form fits — warm energy, instinctive, no supernatural edge needed.",
    "🐾 He's younger. Still working out what loyalty looks like in practice. Getting there.",
    "❄️ He asked how your day was and genuinely wanted to know.",
    "🎮 'CALL' — two hours of gaming followed. That's friendship without needing to explain it.",
    "🌿 He doesn't have a wolf form yet. But if the pack shaped him one, it would be yellow — warm and unfiltered.",
]

class Matthijs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _matthijs_main_embed(self, member: discord.Member | None = None) -> discord.Embed:
        embed = discord.Embed(
            title="🌕 Matthijs — Pack Adjacent | Still Figuring It Out",
            color=0xF5C518  # warm yellow
        )
        if member:
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Role",
            value="Trusted Friend · Younger Pack · Loyal Despite The Chaos",
            inline=False
        )
        embed.add_field(
            name="Bond",
            value="Looks up to Wolfy. Loyal in his own way. Still earning the full picture.",
            inline=False
        )
        embed.add_field(
            name="Personality",
            value=(
                "Reactive and enthusiastic first, thoughtful second.\n"
                "Younger energy — still working out how things fit together.\n"
                "Protective when it counts. Loud when he's excited. Quiet when he's curious."
            ),
            inline=False
        )
        embed.add_field(
            name="Wolf Form",
            value=(
                "No established wolf form. Doesn't need one yet.\n"
                "If the pack shaped one — yellow. Warm, instinctive, no supernatural edge.\n"
                "The colour of someone still figuring out their strength."
            ),
            inline=False
        )
        embed.add_field(
            name="Known For",
            value="All caps enthusiasm. One Piece opinions. Asking to play without knowing what. Showing up anyway.",
            inline=False
        )
        embed.set_footer(text=f"🌕 Discord: <@{MATTHIJS_ID}> • Still growing. Still here.")
        return embed

    def _matthijs_lore_embed(self) -> discord.Embed:
        embed = discord.Embed(
            description=wolf_wrap(random.choice(MATTHIJS_LORE)),
            color=0xF5C518
        )
        embed.set_footer(text="🌕 Matthijs — Pack Adjacent")
        return embed

    @commands.command(name="matthijs", help="Show info and lore about Matthijs")
    async def matthijs_prefix(self, ctx):
        member = ctx.guild.get_member(MATTHIJS_ID) if ctx.guild else None
        await ctx.send(embed=self._matthijs_main_embed(member))
        await ctx.send(embed=self._matthijs_lore_embed())

    @app_commands.command(name="matthijs", description="Show info and lore about Matthijs", extras={"category": "general"})
    async def matthijs_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        member = interaction.guild.get_member(MATTHIJS_ID) if interaction.guild else None
        await interaction.response.send_message(embed=self._matthijs_main_embed(member), ephemeral=ephemeral)
        await interaction.followup.send(embed=self._matthijs_lore_embed(), ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(Matthijs(bot))
