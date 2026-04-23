from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import config
from config import wolf_wrap


class Lore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Wolfy profile ─────────────────────────────────────────────────────────

    @commands.command(name="wolfy", help="Show Wolfy's Shadow Crimson Wolf profile")
    async def wolfy_prefix(self, ctx):
        await ctx.send(embed=self._wolfy_embed())

    @app_commands.command(name="wolfy", description="Show Wolfy's Shadow Crimson Wolf profile", extras={"category": "general"})
    async def wolfy_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._wolfy_embed(), ephemeral=ephemeral)

    def _wolfy_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🌑 Wolfy — Shadow Crimson Wolf",
            color=config.BOT_COLOR
        )
        embed.add_field(
            name="Form",
            value="Shadow Crimson Wolf — sole form. No transformations, no toggles.",
            inline=False
        )
        embed.add_field(
            name="Appearance",
            value=(
                "Large, lean, athletic wolf.\n"
                "Charcoal-black primary fur with silver-grey undertone.\n"
                "Near-crimson streaks along the body — visible in motion or low light.\n"
                "Eyes: deep near-crimson.\n"
                "Claws: constant near-crimson edge glow.\n"
                "Paw pads: faint continuous glow, intensifies under pressure.\n"
                "Sigil: dominant wolf-paw on right front shoulder — pulses slowly under intent or Pack Resonance."
            ),
            inline=False
        )
        embed.add_field(
            name="Role",
            value="Lone Wolf · Scout Alpha · Natural Mediator-Sentinel",
            inline=False
        )
        embed.add_field(
            name="Abilities",
            value=(
                "**Predatory Precision** — Enhanced focus and accuracy in combat or tracking.\n"
                "**Scan & Analyze** — Rapid situational assessment.\n"
                "**Silent Command** — Authority without vocalization.\n"
                "**Instinctive Stabilizer** — Natural ability to steady pack members or tense situations.\n"
                "**Pack Resonance** — Synchronizes intent and timing with Kael and the pack."
            ),
            inline=False
        )
        embed.add_field(
            name="Behavior",
            value="Constant low-pressure aura. Calm dominance. Economical movement. Comfortable alone, always alert.",
            inline=False
        )
        embed.add_field(
            name="Rule",
            value="Control is the primary resource. Overextension degrades performance rather than amplifying it.",
            inline=False
        )
        embed.set_footer(text="🔥 More wolf than most dare to see.")
        return embed

    # ── Pack bios ─────────────────────────────────────────────────────────────

    @commands.command(name="packbios", help="Show all pack member profiles")
    async def packbios_prefix(self, ctx):
        for embed in self._packbio_embeds():
            await ctx.send(embed=embed)

    @app_commands.command(name="packbios", description="Show all pack member profiles", extras={"category": "general"})
    async def packbios_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        embeds = self._packbio_embeds()
        await interaction.followup.send(embed=embeds[0], ephemeral=ephemeral)
        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    def _packbio_embeds(self) -> list[discord.Embed]:
        members = [
            {
                "name": "🤍 Sarah — White Sentinel",
                "role": "Sentinel · Moral Compass",
                "appearance": "Pure white fur with soft silver streaks. Pale silver eyes. Faint silver paw glow.",
                "function": "Vigilant guardian and moral anchor of the pack. First to flag what others haven't noticed yet.",
                "trait": "Stands her ground without being asked. The pack trusts her read on situations.",
            },
            {
                "name": "🌑 Shadow — Black Enforcer",
                "role": "Enforcer · External Threat Handler",
                "appearance": "Deep black fur with white and silver streaks. Ice-white eyes. Soft silver paw glow.",
                "function": "Handles external threats before they reach the pack. Operates with imposing aloofness.",
                "trait": "Doesn't explain his methods. Results speak. The pack doesn't ask.",
            },
            {
                "name": "🔥 Ember — Grey Combat Resonance",
                "role": "Offensive Combat Support · Resonance Amplifier",
                "appearance": "Medium grey fur with ember-red streaks. Golden-amber eyes. Amber paw glow.",
                "function": "Offensive combat support. Syncs tightly with Pack Resonance for coordinated strikes.",
                "trait": "Calls the strike before it's called. Usually right. Always ready.",
            },
            {
                "name": "❄️ Frost — Silver Tracker",
                "role": "Reconnaissance · Stealth Specialist",
                "appearance": "Pale silver-grey fur with darker streaks. Icy-blue eyes. Soft icy-blue paw glow.",
                "function": "Reconnaissance and stealth. Moves without leaving evidence. Always ahead of schedule.",
                "trait": "Doesn't need to be told twice. Doesn't need to be told once if he's already done it.",
            },
            {
                "name": "🌿 Ash — Dark Brown Stabilizer",
                "role": "Stabilizer · Healer · Pack Cohesion",
                "appearance": "Dark brown fur with ash-grey markings. Soft ash-grey eyes. Faint ash paw glow.",
                "function": "Holds pack cohesion. Moves through tension before it becomes a problem.",
                "trait": "Doesn't fight. Steadies. The pack is calmer when she's been through it.",
            },
            {
                "name": "🛡️ Thorn — Rust Rear Guard",
                "role": "Defensive Rear Guard",
                "appearance": "Rust-brown fur with darker bramble-pattern streaks. Copper/bronze eyes. Subtle copper paw glow.",
                "function": "Locks the rear position. Nothing passes without clearance.",
                "trait": "Says nothing. Holds the line. The rear has never been breached on his watch.",
            },
        ]

        embeds = []
        for i, m in enumerate(members, 1):
            embed = discord.Embed(
                title=m["name"],
                color=config.BOT_COLOR
            )
            embed.add_field(name="Role", value=m["role"], inline=False)
            embed.add_field(name="Appearance", value=m["appearance"], inline=False)
            embed.add_field(name="Function", value=m["function"], inline=False)
            embed.add_field(name="Trait", value=m["trait"], inline=False)
            embed.set_footer(text=f"Pack Member {i}/6 • The pack holds.")
            embeds.append(embed)

        return embeds

    # ── Pack Resonance ────────────────────────────────────────────────────────

    @commands.command(name="resonance", help="Show Pack Resonance lore and mechanics")
    async def resonance_prefix(self, ctx):
        await ctx.send(embed=self._resonance_embed())

    @app_commands.command(name="resonance", description="Show Pack Resonance lore and mechanics", extras={"category": "general"})
    async def resonance_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._resonance_embed(), ephemeral=ephemeral)

    def _resonance_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔗 Pack Resonance",
            color=config.BOT_COLOR
        )
        embed.add_field(
            name="What it is",
            value=(
                "A permanent bond-based synchronization state — not a form, not a power.\n"
                "Synchronizes intent, perception, and timing between Wolfy, Kael, and the pack.\n"
                "It does not add raw power. It aligns what's already there."
            ),
            inline=False
        )
        embed.add_field(
            name="Activation Requirements",
            value=(
                "• Emotional alignment between pack members\n"
                "• Kael's presence and stability\n"
                "• Pack cohesion — internal tension degrades it"
            ),
            inline=False
        )
        embed.add_field(
            name="Kael's Role",
            value=(
                "Kael is the anchor. Pack Resonance **collapses immediately if Kael destabilizes**.\n"
                "There is no workaround. There is no substitute. If Kael drops, it ends."
            ),
            inline=False
        )
        embed.add_field(
            name="Cost",
            value=(
                "Mental load and fatigue on Wolfy and the pack.\n"
                "Kael bears the heaviest strain as anchor.\n"
                "Prolonged use leaves residual fatigue even after disengagement.\n"
                "Cannot stack with high-drain forms or prolonged Unleashed output."
            ),
            inline=False
        )
        embed.add_field(
            name="Failure",
            value=(
                "Collapse is not clean. Disorientation, loss of control, lasting consequences.\n"
                "Ignoring strain leads to forced shutdown rather than clean exit."
            ),
            inline=False
        )
        embed.add_field(
            name="Moon Interactions",
            value=(
                "🩸 **Blood Moon** — Volatility threatens cohesion. High risk of instinct override.\n"
                "❄️ **Frost Moon** — Precision window. Resonance runs clean and controlled.\n"
                "🌿 **Emerald Moon** — Kael destabilizes. Resonance is at highest collapse risk.\n"
                "🌕 **Golden Moon** — Bond intensifies. Resonance runs strong but punishes solo action."
            ),
            inline=False
        )
        embed.set_footer(text="🔗 Powerful. Punishing. Non-optional when it's needed.")
        return embed

    # ── Moon lore ─────────────────────────────────────────────────────────────

    @commands.command(name="moonlore", help="Show the 4 moons and their effects")
    async def moonlore_prefix(self, ctx):
        await ctx.send(embed=self._moonlore_embed())

    @app_commands.command(name="moonlore", description="Show the 4 moons and their effects on the pack", extras={"category": "general"})
    async def moonlore_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._moonlore_embed(), ephemeral=ephemeral)

    def _moonlore_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🌙 The Moon System",
            description=(
                "The moons act as environmental modifiers — they influence Wolfy, Kael, and the pack naturally. "
                "Effects ripple subtly unless the moon directly impacts the scene."
            ),
            color=config.BOT_COLOR
        )
        embed.add_field(
            name="🩸 Blood Moon",
            value=(
                "Volatility, instinct-driven aggression, impulsive choices.\n"
                "Control costs more. Pack Resonance cohesion is at risk.\n"
                "The sigil responds more strongly. Harder to hold steady."
            ),
            inline=False
        )
        embed.add_field(
            name="❄️ Frost Moon",
            value=(
                "Calm, precision, emotional suppression, slower reaction to sudden changes.\n"
                "Best window for extended patrol, tracking, and analytical work.\n"
                "Pack Resonance runs cleaner under Frost Moon conditions."
            ),
            inline=False
        )
        embed.add_field(
            name="🌿 Emerald Moon",
            value=(
                "Loss of control, instinct misfires, consequences for misjudgment.\n"
                "Affects Kael hardest — Pack Resonance collapse risk is highest here.\n"
                "The pack stays tight. Solo action under the Emerald Moon is unwise."
            ),
            inline=False
        )
        embed.add_field(
            name="🌕 Golden Moon",
            value=(
                "Bond intensifies, teamwork synergy rises, autonomy is challenged.\n"
                "Leaving the pack feels genuinely difficult — the bond pulls hard.\n"
                "Pack Resonance runs strong. Solo action is punished."
            ),
            inline=False
        )
        embed.set_footer(text="🌙 The moons don't command. They influence. The pack decides the rest.")
        return embed


async def setup(bot):
    await bot.add_cog(Lore(bot))
