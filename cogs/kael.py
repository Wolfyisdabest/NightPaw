from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import random
import config
from config import wolf_wrap

KAEL_LORE = [
    "🐺 Kael moves without announcing himself. You notice him when he's already beside you.",
    "🔥 The ember glow is rare. When it appears, something important is happening.",
    "❄️ Kael doesn't react to small threats. He waits. When he moves, it means something.",
    "🌑 He's been called the pack's anchor more than once — not because he holds things down, but because without him things drift.",
    "👁️ Kael's eyes shift to ember only when the pack needs it most. Most of the time they're just quiet, watching.",
    "🐾 He's been with Wolfy long enough that words aren't always needed. Presence is enough.",
    "⚡ Playful until he's not. That line is very clear to anyone who knows him.",
    "🌿 The Resonance doesn't stabilize on its own. Kael is why it holds.",
    "🔥 When the glow activates, it's not a warning to the pack. It's a warning to whatever's threatening it.",
    "🤝 Co-Alpha isn't a title Kael carries loudly. He carries it in how he moves, how he watches, how he stays.",
    "💀 The claws stay natural at rest. Everything about Kael at rest says: not a threat. Everything about Kael in motion says: don't test that.",
    "🌕 Kael has never needed to prove himself. The pack already knows.",
    "❄️ His grey-black coat blends into dusk and dawn both. He was built for the in-between.",
    "🐺 Bonded Guardian isn't a role he was assigned. It's just what he is.",
    "🔥 There's a version of Kael that's chasing leaves in the den clearing. There's another that holds the line when everything shakes. Both are equally real.",
]

class Kael(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _kael_main_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🐺 Kael — Co-Alpha & Bonded Guardian",
            color=config.BOT_COLOR
        )
        embed.add_field(
            name="Role",
            value="Co-Alpha · Bonded Guardian · Pack Resonance Anchor",
            inline=False
        )
        embed.add_field(
            name="Bond",
            value="Wolfy's lifelong companion. Foundational and non-optional.",
            inline=False
        )
        embed.add_field(
            name="Appearance",
            value="Czechoslovakian Wolfdog — grey-black coat, deep ember/amber eyes at rest.",
            inline=False
        )
        embed.add_field(
            name="Glow System",
            value=(
                "Ember glow activates on eyes and claws only when:\n"
                "• Pack Resonance stabilizes\n"
                "• Wolfy sharpens intent\n"
                "• Direct threat is detected toward Wolfy or the pack\n"
                "Returns fully natural once tension drops."
            ),
            inline=False
        )
        embed.add_field(
            name="Function",
            value="Stabilizes Pack Resonance. If Kael falters, Resonance collapses.",
            inline=False
        )
        embed.add_field(
            name="Personality",
            value="Playful until he's not. That line is unmistakable.",
            inline=False
        )
        embed.set_footer(text="🔥 Curiosity leads, loyalty follows, strength protects.")
        return embed

    def _kael_lore_embed(self) -> discord.Embed:
        embed = discord.Embed(
            description=wolf_wrap(random.choice(KAEL_LORE)),
            color=config.BOT_COLOR
        )
        embed.set_footer(text="🐺 Kael — Co-Alpha")
        return embed

    @commands.command(name="kael", help="Show info and lore about Kael")
    async def kael_prefix(self, ctx):
        await ctx.send(embed=self._kael_main_embed())
        await ctx.send(embed=self._kael_lore_embed())

    @app_commands.command(name="kael", description="Show info and lore about Kael", extras={"category": "general"})
    async def kael_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._kael_main_embed(), ephemeral=ephemeral)
        await interaction.followup.send(embed=self._kael_lore_embed(), ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(Kael(bot))
