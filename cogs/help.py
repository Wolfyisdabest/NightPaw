from __future__ import annotations

import contextlib
from dataclasses import dataclass
import math

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import config
from services.feature_intelligence import infer_command_category, infer_command_section


OWNER_ID = config.OWNER_ID
DB_PATH = "data/nightpaw.db"
PAGE_SIZE = 6

SECTION_META: dict[str, tuple[str, str, str]] = {
    "overview": ("📚", "Overview", "High-level bot info, visible command totals, and quick usage guidance."),
    "ranks": ("🏷️", "Ranks", "How NightPaw access levels work and what each rank can see."),
    "ai": ("🧠", "AI", "Chat, memory, routing, and NightPaw AI controls."),
    "utility": ("🧰", "Utility", "Daily-use tools, reminders, lookups, and practical helpers."),
    "lore": ("🌙", "Lore", "Character profiles, wolf lore, and worldbuilding commands."),
    "pack": ("🤝", "Pack", "Trusted pack visibility and pack-related commands."),
    "serveradmin": ("🧷", "ServerAdmin", "In-server controls and server-managed command settings."),
    "moderation": ("🛡️", "Moderation", "Moderation and safety tools, shown only when accessible."),
    "system": ("⚙️", "System", "Operational, maintenance, and diagnostic commands based on access."),
    "help": ("📖", "Help", "Navigation and command discovery tools."),
}

ACCESS_BADGES = {
    "general": "",
    "trusted": "Pack",
    "serveradmin": "ServerAdmin",
    "owner": "Alpha",
}


async def _is_trusted(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM trusted WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone() is not None
    except Exception:
        return False


@dataclass(slots=True)
class HelpEntry:
    name: str
    usage: str
    description: str
    access: str
    section: str
    aliases: list[str]


def _trim(text: str | None, limit: int = 180) -> str:
    if not text:
        return "No description provided."
    return " ".join(text.split())[:limit]


class HelpView(discord.ui.View):
    def __init__(
        self,
        *,
        author_id: int,
        data: dict[str, object],
    ):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.data = data
        self.section = "overview"
        self.page = 0
        self._refresh_controls()

    async def on_timeout(self) -> None:
        self._refresh_controls()
        for item in self.children:
            item.disabled = True
        message = getattr(self, "message", None)
        if message is None:
            return
        try:
            await message.edit(view=self)
        except Exception:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help view belongs to the person who opened it.", ephemeral=True)
            return False
        return True

    def _section_options(self) -> list[discord.SelectOption]:
        sections: dict[str, list[HelpEntry]] = self.data["sections"]  # type: ignore[assignment]
        options: list[discord.SelectOption] = []
        for key, (emoji, title, description) in SECTION_META.items():
            if key not in {"overview", "ranks"} and not sections.get(key):
                continue
            count = len(sections.get(key, []))
            label = title if key in {"overview", "ranks"} else f"{title} ({count})"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=key,
                    emoji=emoji,
                    description=description[:100],
                    default=key == self.section,
                )
            )
        return options[:25]

    def _max_page(self) -> int:
        sections: dict[str, list[HelpEntry]] = self.data["sections"]  # type: ignore[assignment]
        if self.section == "overview":
            return 0
        entries = sections.get(self.section, [])
        return max(0, math.ceil(len(entries) / PAGE_SIZE) - 1)

    def _refresh_controls(self) -> None:
        self.clear_items()

        select = discord.ui.Select(
            placeholder="Choose a help section...",
            options=self._section_options(),
            row=0,
        )

        async def select_callback(interaction: discord.Interaction) -> None:
            self.section = select.values[0]
            self.page = 0
            self._refresh_controls()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        select.callback = select_callback
        self.add_item(select)

        prev_button = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.secondary,
            disabled=self.page <= 0,
            row=1,
        )
        next_button = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= self._max_page(),
            row=1,
        )
        home_button = discord.ui.Button(
            label="Overview",
            style=discord.ButtonStyle.primary if self.section != "overview" else discord.ButtonStyle.secondary,
            disabled=self.section == "overview",
            row=1,
        )

        async def prev_callback(interaction: discord.Interaction) -> None:
            self.page = max(0, self.page - 1)
            self._refresh_controls()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        async def next_callback(interaction: discord.Interaction) -> None:
            self.page = min(self._max_page(), self.page + 1)
            self._refresh_controls()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        async def home_callback(interaction: discord.Interaction) -> None:
            self.section = "overview"
            self.page = 0
            self._refresh_controls()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        prev_button.callback = prev_callback
        next_button.callback = next_callback
        home_button.callback = home_callback
        self.add_item(prev_button)
        self.add_item(next_button)
        self.add_item(home_button)

    def build_embed(self) -> discord.Embed:
        if self.section == "overview":
            return self._build_overview_embed()
        if self.section == "ranks":
            return self._build_ranks_embed()
        return self._build_section_embed()

    def _build_overview_embed(self) -> discord.Embed:
        stats: dict[str, object] = self.data["stats"]  # type: ignore[assignment]
        sections: dict[str, list[HelpEntry]] = self.data["sections"]  # type: ignore[assignment]

        embed = discord.Embed(
            title="📚 NightPaw Command Center",
            description=(
                "One place to browse what NightPaw can do.\n"
                f"Use the select menu below to jump between sections. Prefix commands use `{config.PREFIX}` and many also have slash equivalents."
            ),
            color=config.BOT_COLOR,
        )
        embed.add_field(
            name="Bot Snapshot",
            value=(
                f"Visible commands: `{stats['visible_commands']}`\n"
                f"Loaded cogs: `{stats['visible_cogs']}`\n"
                f"Servers: `{stats['guilds']}`\n"
                f"Latency: `{stats['latency_ms']}ms`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Access Profile",
            value=(
                f"Level: `{stats['access_label']}`\n"
                f"Trusted: `{stats['trusted']}`\n"
                f"ServerAdmin: `{stats['serveradmin']}`\n"
                f"Alpha: `{stats['owner']}`"
            ),
            inline=True,
        )
        section_lines = []
        for key, entries in sections.items():
            if not entries:
                continue
            emoji, title, _ = SECTION_META[key]
            section_lines.append(f"{emoji} `{title}`: `{len(entries)}`")
        embed.add_field(
            name="Sections",
            value="\n".join(section_lines[:12]) or "No accessible sections.",
            inline=False,
        )
        embed.add_field(
            name="Quick Notes",
            value=(
                "NightPaw can answer questions, run selected safe commands through AI when enabled, and show command details by section.\n"
                "Restricted commands are hidden unless your access level allows them. Use the Ranks tab for the exact access model."
            ),
            inline=False,
        )
        embed.set_footer(text="Section overview • Select a category below")
        return embed

    def _build_ranks_embed(self) -> discord.Embed:
        stats: dict[str, object] = self.data["stats"]  # type: ignore[assignment]
        embed = discord.Embed(
            title="🏷️ NightPaw Rank Guide",
            description="NightPaw separates ownership, trusted-pack access, and in-server management access.",
            color=config.BOT_COLOR,
        )
        embed.add_field(
            name="General",
            value="Default access. Public utility, help, lore, and general AI features.",
            inline=False,
        )
        embed.add_field(
            name="Pack",
            value="Trusted users from the pack list. Grants pack-restricted visibility and trusted-only commands.",
            inline=False,
        )
        embed.add_field(
            name="ServerAdmin",
            value="In-server management access. Derived from guild permissions like Administrator, Manage Server, Manage Messages, Manage Roles, Kick, Ban, or Moderate Members.",
            inline=False,
        )
        embed.add_field(
            name="Alpha",
            value="Yes: Alpha = owner. This is the configured owner account and highest access level.",
            inline=False,
        )
        embed.add_field(
            name="Your Current Access",
            value=(
                f"Resolved level: `{stats['access_label']}`\n"
                f"Pack: `{stats['trusted']}`\n"
                f"ServerAdmin: `{stats['serveradmin']}`\n"
                f"Alpha: `{stats['owner']}`"
            ),
            inline=False,
        )
        embed.set_footer(text="Rank model • Select another section below")
        return embed

    def _build_section_embed(self) -> discord.Embed:
        sections: dict[str, list[HelpEntry]] = self.data["sections"]  # type: ignore[assignment]
        entries = sections.get(self.section, [])
        emoji, title, description = SECTION_META[self.section]
        start = self.page * PAGE_SIZE
        chunk = entries[start:start + PAGE_SIZE]
        max_page = self._max_page()

        embed = discord.Embed(
            title=f"{emoji} {title} Commands",
            description=description,
            color=config.BOT_COLOR,
        )
        if not chunk:
            embed.add_field(name="No Commands", value="Nothing is visible in this section for your current access level.", inline=False)
        else:
            for entry in chunk:
                alias_text = f"\nAliases: {', '.join(f'`{a}`' for a in entry.aliases[:4])}" if entry.aliases else ""
                access = ACCESS_BADGES.get(entry.access, "")
                access_text = f"\nAccess: `{access}`" if access else ""
                embed.add_field(
                    name=entry.usage,
                    value=f"{entry.description}{access_text}{alias_text}",
                    inline=False,
                )
        embed.set_footer(
            text=f"{title} • Page {self.page + 1}/{max_page + 1} • {len(entries)} visible command(s)"
        )
        return embed


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_admin(self, member: discord.abc.User, guild: discord.Guild | None) -> bool:
        if member.id == OWNER_ID:
            return True
        if guild is None:
            return False
        guild_member = guild.get_member(member.id)
        perms = getattr(guild_member, "guild_permissions", None)
        return bool(
            perms
            and (
                perms.administrator
                or perms.manage_guild
                or perms.manage_messages
                or perms.manage_roles
                or perms.kick_members
                or perms.ban_members
                or perms.moderate_members
            )
        )

    def _has_access(self, access: str, *, trusted: bool, is_admin: bool, is_owner: bool) -> bool:
        if access == "owner":
            return is_owner
        if access == "serveradmin":
            return is_admin
        if access == "trusted":
            return trusted
        return True

    def _collect_entries(
        self,
        *,
        trusted: bool,
        is_admin: bool,
        is_owner: bool,
    ) -> dict[str, list[HelpEntry]]:
        sections: dict[str, list[HelpEntry]] = {key: [] for key in SECTION_META if key not in {"overview", "ranks"}}

        for cog_name, cog in sorted(self.bot.cogs.items()):
            prefix_cmds = {cmd.name: cmd for cmd in cog.get_commands() if not cmd.hidden}
            slash_cmds = {
                cmd.name: cmd
                for cmd in getattr(cog, "__cog_app_commands__", [])
            }
            all_names = sorted(set(prefix_cmds) | set(slash_cmds))
            for name in all_names:
                prefix_cmd = prefix_cmds.get(name)
                slash_cmd = slash_cmds.get(name)
                access = infer_command_category(prefix_cmd=prefix_cmd, slash_cmd=slash_cmd)
                if not self._has_access(access, trusted=trusted, is_admin=is_admin, is_owner=is_owner):
                    continue
                section = infer_command_section(prefix_cmd=prefix_cmd, slash_cmd=slash_cmd)
                label_parts = []
                if prefix_cmd is not None:
                    label_parts.append(f"`{config.PREFIX}{name}`")
                if slash_cmd is not None:
                    label_parts.append(f"`/{name}`")
                usage = " | ".join(label_parts) if label_parts else f"`{name}`"
                description = _trim(
                    slash_cmd.description if slash_cmd is not None and getattr(slash_cmd, "description", None)
                    else prefix_cmd.help if prefix_cmd is not None
                    else ""
                )
                aliases = sorted(set(prefix_cmd.aliases)) if prefix_cmd is not None else []
                sections.setdefault(section, []).append(
                    HelpEntry(
                        name=name,
                        usage=usage,
                        description=description,
                        access=access,
                        section=section,
                        aliases=aliases,
                    )
                )

        for key in sections:
            sections[key].sort(key=lambda item: item.name)
        return sections

    async def _build_data(self, source) -> dict[str, object]:
        member = source.author if isinstance(source, commands.Context) else source.user
        guild = source.guild
        trusted = await _is_trusted(member.id)
        is_owner = member.id == OWNER_ID
        is_admin = self._is_admin(member, guild)
        sections = self._collect_entries(trusted=trusted, is_admin=is_admin, is_owner=is_owner)
        visible_commands = sum(len(items) for items in sections.values())
        visible_cogs = len(
            [
                cog_name
                for cog_name, cog in self.bot.cogs.items()
                if any(
                    self._has_access(
                        infer_command_category(prefix_cmd=cmd),
                        trusted=trusted,
                        is_admin=is_admin,
                        is_owner=is_owner,
                    )
                    for cmd in cog.get_commands()
                    if not cmd.hidden
                )
                or any(
                    self._has_access(
                        infer_command_category(slash_cmd=cmd),
                        trusted=trusted,
                        is_admin=is_admin,
                        is_owner=is_owner,
                    )
                    for cmd in getattr(cog, "__cog_app_commands__", [])
                )
            ]
        )
        stats = {
            "visible_commands": visible_commands,
            "visible_cogs": visible_cogs,
            "guilds": len(self.bot.guilds),
            "latency_ms": round(self.bot.latency * 1000),
            "trusted": trusted,
            "serveradmin": is_admin,
            "owner": is_owner,
            "access_label": "Alpha" if is_owner else "ServerAdmin" if is_admin else "Pack" if trusted else "General",
        }
        return {"sections": sections, "stats": stats}

    async def _send_help(self, source, sender):
        data = await self._build_data(source)
        author_id = source.author.id if isinstance(source, commands.Context) else source.user.id
        view = HelpView(author_id=author_id, data=data)
        message = await sender(embed=view.build_embed(), view=view)
        if isinstance(message, discord.Message):
            view.message = message

    @commands.command(name="help", help="Open the interactive NightPaw help center")
    async def help_prefix(self, ctx: commands.Context):
        await self._send_help(ctx, ctx.send)

    @app_commands.command(name="help", description="Open the interactive NightPaw help center", extras={"category": "general"})
    async def help_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(
            embed=discord.Embed(description="Loading help…", color=config.BOT_COLOR),
            ephemeral=ephemeral,
        )
        data = await self._build_data(interaction)
        view = HelpView(author_id=interaction.user.id, data=data)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        with contextlib.suppress(discord.NotFound):
            view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
