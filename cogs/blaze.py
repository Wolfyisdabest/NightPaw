from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import random
import config
from config import wolf_wrap

BLAZE_ID = 981526859223269376

BLAZE_LORE = [
    "🐺 Blaze doesn't panic. When something breaks, he just goes quiet and starts working the problem.",
    "🌿 The green wolf form would suit him — not flashy, not loud. Present and effective.",
    "🤝 He was in the Netherlands once. Brought a sign. Small thing. Meant something.",
    "🎮 He'll troubleshoot with you for two hours at midnight without complaint. That's just how he is.",
    "❄️ Blaze doesn't overthink loyalty. It's either there or it isn't. With him, it is.",
    "🔥 Sharp-minded. The kind of person who catches the thing everyone else missed.",
    "🌑 He's not loud about being a friend. He just shows up.",
    "👁️ The rivalry is real but it runs clean. Both of them know it.",
    "🐾 Distance doesn't change much. The bond holds across countries.",
    "🎵 He plays Fisch. He knows every market cycle and will tell you exactly when to buy.",
    "🤝 Trusted inner circle. Not because it was decided — because it was earned.",
    "🌿 When the server broke, he kept trying. That says enough.",
    "🔥 The green form would carry crimson's discipline with nature's steadiness. Balanced.",
    "🎮 Mythical Creatures RP. He rated the story 10 out of 10 and asked for more.",
    "❄️ Quiet the way steady people are quiet — not absent, just grounded.",
]

class Blaze(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _blaze_main_embed(self, member: discord.Member | None = None) -> discord.Embed:
        embed = discord.Embed(
            title="🌿 Blaze — Trusted Pack | Inner Circle",
            color=0x2D8C2D  # forest green
        )
        if member:
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Role",
            value="Trusted Friend · Inner Circle · Sharp-Minded Ally",
            inline=False
        )
        embed.add_field(
            name="Bond",
            value="Best friend. Known across distance, proven over time. Non-optional.",
            inline=False
        )
        embed.add_field(
            name="Personality",
            value="Sharp-minded and steady. Loyal without making a big deal of it. Competitive in the right way — rivalry that runs clean.",
            inline=False
        )
        embed.add_field(
            name="Wolf Form",
            value=(
                "If Blaze had a wolf form — similar to Shadow Crimson Wolf but green instead of crimson.\n"
                "Forest-green streaks, charcoal base. Same discipline. Different energy.\n"
                "Nature's steadiness over fire's intensity."
            ),
            inline=False
        )
        embed.add_field(
            name="Known For",
            value="Troubleshooting at midnight. Fisch market knowledge. Showing up when it matters.",
            inline=False
        )
        embed.set_footer(text=f"🌿 Discord: <@{BLAZE_ID}> • The bond holds across countries.")
        return embed

    def _blaze_lore_embed(self) -> discord.Embed:
        embed = discord.Embed(
            description=wolf_wrap(random.choice(BLAZE_LORE)),
            color=0x2D8C2D
        )
        embed.set_footer(text="🌿 Blaze — Inner Circle")
        return embed

    @commands.command(name="blaze", help="Show info and lore about Blaze")
    async def blaze_prefix(self, ctx):
        member = ctx.guild.get_member(BLAZE_ID) if ctx.guild else None
        await ctx.send(embed=self._blaze_main_embed(member))
        await ctx.send(embed=self._blaze_lore_embed())

    @app_commands.command(name="blaze", description="Show info and lore about Blaze", extras={"category": "general"})
    async def blaze_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        member = interaction.guild.get_member(BLAZE_ID) if interaction.guild else None
        await interaction.response.send_message(embed=self._blaze_main_embed(member), ephemeral=ephemeral)
        await interaction.followup.send(embed=self._blaze_lore_embed(), ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(Blaze(bot))
