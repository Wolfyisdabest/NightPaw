from __future__ import annotations

import contextlib
import os
import platform
from pathlib import Path
import math
from typing import Literal

import discord
import aiohttp
import psutil
from discord import app_commands
from discord.ext import commands

import config
from checks import is_owner_dm_only, is_owner_dm_slash, is_owner_slash
from config import wolf_wrap
from services.db import DB_PATH
from services.guild_policy_service import allow_guild, block_guild, ensure_schema as ensure_guild_policy_schema, list_blocked_guilds
from services.startup_update_service import SNAPSHOT_PATH


INVITE_PERMISSION_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Core",
        (
            ("view_channel", "View Channels"),
            ("send_messages", "Send Messages"),
            ("embed_links", "Embed Links"),
            ("attach_files", "Attach Files"),
            ("read_message_history", "Read Message History"),
            ("add_reactions", "Add Reactions"),
            ("use_external_emojis", "Use External Emojis"),
            ("send_messages_in_threads", "Send Messages in Threads"),
            ("create_public_threads", "Create Public Threads"),
            ("create_private_threads", "Create Private Threads"),
            ("manage_threads", "Manage Threads"),
        ),
    ),
    (
        "Moderation",
        (
            ("manage_messages", "Manage Messages"),
            ("moderate_members", "Timeout Members"),
            ("kick_members", "Kick Members"),
            ("ban_members", "Ban Members"),
            ("manage_roles", "Manage Roles"),
            ("manage_nicknames", "Manage Nicknames"),
            ("change_nickname", "Change Own Nickname"),
            ("move_members", "Move Members"),
            ("mute_members", "Mute Members"),
            ("deafen_members", "Deafen Members"),
        ),
    ),
    (
        "Server",
        (
            ("manage_channels", "Manage Channels"),
            ("manage_guild", "Manage Server"),
            ("view_audit_log", "View Audit Log"),
            ("manage_webhooks", "Manage Webhooks"),
            ("manage_expressions", "Manage Emojis/Stickers"),
            ("mention_everyone", "Mention Everyone"),
        ),
    ),
)


class InvitePermissionSelect(discord.ui.Select):
    def __init__(
        self,
        *,
        group_name: str,
        options: list[discord.SelectOption],
        selected_names: set[str],
    ):
        for option in options:
            option.default = option.value in selected_names
        super().__init__(
            placeholder=f"{group_name} permissions",
            min_values=0,
            max_values=len(options),
            options=options,
            row=0 if group_name == "Core" else 1 if group_name == "Moderation" else 2,
        )
        self.group_name = group_name

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, InvitePermissionView):
            return
        group_values = {option.value for option in self.options}
        view.selected_names.difference_update(group_values)
        view.selected_names.update(self.values)
        await interaction.response.defer()


class InvitePermissionView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "Sysadmin",
        owner_id: int,
        initial_selected: list[str] | None = None,
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id
        self.selected_names: set[str] = set(initial_selected or [])
        self.message: discord.InteractionMessage | None = None
        self._rebuild_selects()

    def _rebuild_selects(self) -> None:
        self.clear_items()
        for group_name, options in self.cog._permission_select_groups():
            self.add_item(
                InvitePermissionSelect(
                    group_name=group_name,
                    options=options,
                    selected_names=self.selected_names,
                )
            )
        self.add_item(InviteConfirmButton())
        self.add_item(InviteCancelButton())
        self.add_item(InviteResetButton())

    def _disable_all(self) -> None:
        for item in self.children:
            item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                wolf_wrap("Only the command invoker can use this invite builder."),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self._disable_all()
        if self.message is not None:
            with contextlib.suppress(Exception):
                await self.message.edit(view=self)


class InviteConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Confirm", style=discord.ButtonStyle.green, row=3)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, InvitePermissionView):
            return
        perms = view.cog._permissions_from_names(sorted(view.selected_names))
        embed = view.cog._invite_embed(
            mode_label="custom",
            perms=perms,
            custom_enabled=sorted(view.selected_names),
        )
        view._disable_all()
        await interaction.response.edit_message(embed=embed, view=view)


class InviteCancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.red, row=3)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, InvitePermissionView):
            return
        embed = discord.Embed(
            title="NightPaw Server Invite",
            description="Custom invite builder canceled.",
            color=config.BOT_COLOR,
        )
        view._disable_all()
        await interaction.response.edit_message(embed=embed, view=view)


class InviteResetButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Reset", style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, InvitePermissionView):
            return
        view.selected_names.clear()
        view._rebuild_selects()
        await interaction.response.edit_message(embed=view.cog._custom_invite_prompt_embed(), view=view)


class Sysadmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_guild_policy_schema()

    def _invite_permissions_for_mode(self, mode: str) -> discord.Permissions:
        if mode == "minimal":
            perms = discord.Permissions.none()
            perms.view_channel = True
            perms.send_messages = True
            return perms
        if mode == "required":
            perms = discord.Permissions.none()
            perms.view_channel = True
            perms.send_messages = True
            perms.embed_links = True
            perms.attach_files = True
            perms.read_message_history = True
            perms.add_reactions = True
            perms.manage_messages = True
            perms.moderate_members = True
            perms.kick_members = True
            perms.ban_members = True
            perms.manage_roles = True
            return perms
        if mode == "full":
            perms = discord.Permissions.none()
            perms.view_channel = True
            perms.send_messages = True
            perms.embed_links = True
            perms.attach_files = True
            perms.read_message_history = True
            perms.add_reactions = True
            perms.use_external_emojis = True
            perms.manage_messages = True
            perms.manage_threads = True
            perms.create_public_threads = True
            perms.create_private_threads = True
            perms.send_messages_in_threads = True
            perms.moderate_members = True
            perms.kick_members = True
            perms.ban_members = True
            perms.manage_roles = True
            perms.read_message_history = True
            return perms
        raise ValueError(f"Unknown invite mode: {mode}")

    def _permission_name_map(self) -> dict[str, str]:
        names = discord.Permissions.VALID_FLAGS
        return {name.casefold(): name for name in names}

    def _permissions_from_names(self, names: list[str]) -> discord.Permissions:
        resolved_names = self._permission_name_map()
        perms = discord.Permissions.none()
        for item in names:
            key = resolved_names.get(item.casefold())
            if key is None:
                continue
            setattr(perms, key, True)
        return perms

    def _permission_select_groups(self) -> list[tuple[str, list[discord.SelectOption]]]:
        resolved_names = self._permission_name_map()
        groups: list[tuple[str, list[discord.SelectOption]]] = []
        for group_name, entries in INVITE_PERMISSION_GROUPS:
            options: list[discord.SelectOption] = []
            for perm_name, label in entries:
                actual_name = resolved_names.get(perm_name.casefold())
                if actual_name is None:
                    continue
                options.append(discord.SelectOption(label=label, value=actual_name, description=actual_name))
            if options:
                groups.append((group_name, options))
        return groups

    def _parse_custom_permissions(self, raw: str) -> tuple[discord.Permissions | None, list[str], list[str]]:
        normalized = [token.strip().casefold() for token in (raw or "").replace("|", ",").split(",")]
        requested = [token.replace(" ", "_") for token in normalized if token]
        if not requested:
            return None, [], []

        resolved_names = self._permission_name_map()
        perms = discord.Permissions.none()
        enabled: list[str] = []
        invalid: list[str] = []
        for item in requested:
            key = resolved_names.get(item)
            if key is None:
                invalid.append(item)
                continue
            setattr(perms, key, True)
            enabled.append(key)
        return perms, enabled, invalid

    def _custom_invite_prompt_embed(self) -> discord.Embed:
        embed = discord.Embed(title="NightPaw Server Invite", color=config.BOT_COLOR)
        embed.description = "Pick the custom permissions to include, then confirm to generate the OAuth invite URL."
        embed.add_field(name="Mode", value="custom", inline=False)
        embed.add_field(name="Scopes", value="`bot`, `applications.commands`", inline=False)
        embed.add_field(
            name="Permission Groups",
            value="Core, Moderation, Server",
            inline=False,
        )
        embed.set_footer(text="Owner-only interactive invite builder.")
        return embed

    def _invite_embed(
        self,
        *,
        mode_label: str,
        perms: discord.Permissions,
        target_user: discord.abc.User | None = None,
        custom_enabled: list[str] | None = None,
        invalid_permissions: list[str] | None = None,
    ) -> discord.Embed:
        app_id = getattr(self.bot, "application_id", None)
        invite_url = None
        if app_id:
            invite_url = discord.utils.oauth_url(
                app_id,
                permissions=perms,
                scopes=("bot", "applications.commands"),
            )

        target_label = None
        if target_user is not None:
            target_label = f"{getattr(target_user, 'display_name', target_user.name)} ({target_user.id})"

        embed = discord.Embed(title="NightPaw Server Invite", color=config.BOT_COLOR)
        embed.description = (
            "Owner-only OAuth invite generator."
            + (f"\nPrepared for: `{target_label}`" if target_label else "")
        )
        embed.add_field(
            name="Mode",
            value=mode_label,
            inline=False,
        )
        embed.add_field(
            name="Scopes",
            value="`bot`, `applications.commands`",
            inline=False,
        )
        selected_names = custom_enabled if custom_enabled is not None else [name for name, enabled in perms if enabled]
        selected_text = ", ".join(f"`{name}`" for name in selected_names[:20]) if selected_names else "`none`"
        if len(selected_names) > 20:
            selected_text += f", and {len(selected_names) - 20} more"
        embed.add_field(name="Selected Permissions", value=selected_text, inline=False)
        embed.add_field(name="Permission Integer", value=f"`{perms.value}`", inline=False)
        if invite_url:
            embed.add_field(name="Invite Link", value=invite_url, inline=False)
        else:
            embed.add_field(
                name="Invite Link",
                value="Application ID unavailable right now, so I couldn't build the OAuth link.",
                inline=False,
            )
        if invalid_permissions:
            embed.add_field(
                name="Ignored Permission Names",
                value=", ".join(f"`{name}`" for name in invalid_permissions[:15]),
                inline=False,
            )
        embed.set_footer(text="Generated only. This command does not add the bot automatically.")
        return embed

    def _latency_text(self) -> str:
        latency = getattr(self.bot, "latency", float("nan"))
        if isinstance(latency, float) and math.isnan(latency):
            return "unavailable"
        return f"{round(latency * 1000)}ms"

    def _sysinfo_embed(self) -> discord.Embed:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        embed = discord.Embed(title="🖥️ System Info", color=config.BOT_COLOR)
        embed.add_field(name="OS", value=platform.system() + " " + platform.release(), inline=False)
        embed.add_field(name="CPU Usage", value=f"{cpu}%", inline=True)
        embed.add_field(name="RAM", value=f"{ram.used / 1e9:.1f}GB / {ram.total / 1e9:.1f}GB ({ram.percent}%)", inline=True)
        embed.add_field(name="Disk (C:)", value=f"{disk.used / 1e9:.1f}GB / {disk.total / 1e9:.1f}GB ({disk.percent}%)", inline=True)
        embed.set_footer(text="NightPaw Sysadmin")
        return embed

    @commands.command(name="sysinfo", help="Show system info (Owner DM only)")
    @is_owner_dm_only()
    async def sysinfo_prefix(self, ctx):
        await ctx.send(embed=self._sysinfo_embed())

    @app_commands.command(name="sysinfo", description="Show system info (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def sysinfo_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._sysinfo_embed(), ephemeral=ephemeral)

    def _ls_embed(self, path: str) -> discord.Embed:
        try:
            entries = os.listdir(path)
            dirs = [f"📁 {e}" for e in entries if os.path.isdir(os.path.join(path, e))]
            files = [f"📄 {e}" for e in entries if os.path.isfile(os.path.join(path, e))]
            all_entries = dirs + files
            display = "\n".join(all_entries[:30]) or "Empty directory."
            if len(all_entries) > 30:
                display += f"\n... and {len(all_entries) - 30} more"
            embed = discord.Embed(
                title=f"📂 {os.path.abspath(path)}",
                description=f"```\n{display}\n```",
                color=config.BOT_COLOR,
            )
        except PermissionError:
            embed = discord.Embed(description=wolf_wrap("Permission denied."), color=config.BOT_COLOR)
        except FileNotFoundError:
            embed = discord.Embed(description=wolf_wrap(f"Path not found: `{path}`"), color=config.BOT_COLOR)
        return embed

    @commands.command(name="ls", help="List directory contents (Owner DM only)")
    @is_owner_dm_only()
    async def ls_prefix(self, ctx, *, path: str = "."):
        await ctx.send(embed=self._ls_embed(path))

    @app_commands.command(name="ls", description="List directory contents (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def ls_slash(self, interaction: discord.Interaction, path: str = ".", ephemeral: bool = False):
        await interaction.response.send_message(embed=self._ls_embed(path), ephemeral=ephemeral)

    def _readfile_embed(self, path: str) -> discord.Embed:
        blocked = [".env", "token", "password", "secret", "nightpaw.db"]
        if any(b in path.lower() for b in blocked):
            return discord.Embed(description=wolf_wrap("That file is off limits."), color=config.BOT_COLOR)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(1800)
                truncated = bool(f.read(1))
            embed = discord.Embed(
                title=f"📄 {os.path.basename(path)}",
                description=f"```\n{content}\n```" + ("\n_Truncated to first 1800 characters._" if truncated else ""),
                color=config.BOT_COLOR,
            )
        except PermissionError:
            embed = discord.Embed(description=wolf_wrap("Permission denied."), color=config.BOT_COLOR)
        except FileNotFoundError:
            embed = discord.Embed(description=wolf_wrap(f"File not found: `{path}`"), color=config.BOT_COLOR)
        except UnicodeDecodeError:
            embed = discord.Embed(description=wolf_wrap("Can't read binary file as text."), color=config.BOT_COLOR)
        return embed

    @commands.command(name="readfile", help="Read a text file (Owner DM only)")
    @is_owner_dm_only()
    async def readfile_prefix(self, ctx, *, path: str):
        await ctx.send(embed=self._readfile_embed(path))

    @app_commands.command(name="readfile", description="Read a text file (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def readfile_slash(self, interaction: discord.Interaction, path: str, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._readfile_embed(path), ephemeral=ephemeral)

    @commands.command(name="botping", help="Check bot latency (Owner DM only)")
    @is_owner_dm_only()
    async def botping_prefix(self, ctx):
        await ctx.send(wolf_wrap(f"Pong! `{round(self.bot.latency * 1000)}ms`"))

    @app_commands.command(name="botping", description="Check bot latency (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def botping_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(f"Pong! `{round(self.bot.latency * 1000)}ms`"), ephemeral=ephemeral)

    async def _ollama_status(self) -> str:
        url = getattr(config, "AI_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{url}/api/tags", timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status >= 400:
                        return f"HTTP {resp.status}"
                    data = await resp.json()
        except Exception as exc:
            return f"offline ({type(exc).__name__})"
        names = [item.get("name") for item in (data.get("models") or []) if item.get("name")]
        return f"online ({len(names)} models)"

    async def _debugreport_embed(self) -> discord.Embed:
        proc = psutil.Process(os.getpid())
        ai_cog = self.bot.cogs.get("AI")
        ai_diag = ai_cog.service.get_last_run_info() if ai_cog and hasattr(ai_cog, "service") else {}
        log_path = Path(getattr(config, "BOT_LOG_FILE", "nightpaw.log"))
        log_exists = log_path.exists()
        log_size = f"{(log_path.stat().st_size / 1024 / 1024):.2f} MB" if log_exists else "missing"
        snapshot_exists = SNAPSHOT_PATH.exists()
        embed = discord.Embed(title="NightPaw Debug Report", color=config.BOT_COLOR)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="Latency", value=self._latency_text(), inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Cogs", value=str(len(self.bot.cogs)), inline=True)
        embed.add_field(name="Process RAM", value=f"{proc.memory_info().rss / 1024 / 1024:.1f} MB", inline=True)
        embed.add_field(name="Ollama", value=await self._ollama_status(), inline=True)
        embed.add_field(name="Main Model", value=getattr(config, "AI_MODEL", "unknown"), inline=True)
        embed.add_field(name="Vision Model", value=getattr(config, "AI_VISION_MODEL", "none") or "none", inline=True)
        embed.add_field(name="DB Path", value=DB_PATH.as_posix(), inline=False)
        embed.add_field(name="Log File", value=f"{log_path.as_posix()} ({log_size})", inline=False)
        embed.add_field(name="Startup Snapshot", value=SNAPSHOT_PATH.as_posix() if snapshot_exists else "missing", inline=False)
        embed.add_field(
            name="Last AI Route",
            value=(
                f"scope={ai_diag.get('scope_type') or 'none'}:{ai_diag.get('scope_id') or 'none'}\n"
                f"attachments={ai_diag.get('attachment_count', 0)} focus={ai_diag.get('attachment_focus') or 'none'}\n"
                f"vision_prepass={bool(ai_diag.get('vision_prepass_used'))} fallback={ai_diag.get('fallback_used') or 'none'}\n"
                f"chat_model={ai_diag.get('chat_model_used') or 'none'}"
            ),
            inline=False,
        )
        embed.set_footer(text="Owner DM diagnostics")
        return embed

    @commands.command(name="debugreport", help="Show an extended debug report (Owner DM only)")
    @is_owner_dm_only()
    async def debugreport_prefix(self, ctx):
        await ctx.send(embed=await self._debugreport_embed())

    @app_commands.command(name="debugreport", description="Show an extended debug report (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def debugreport_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=await self._debugreport_embed(), ephemeral=ephemeral)

    def _resolve_guild_query(self, query: str) -> discord.Guild | None:
        raw = (query or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            return self.bot.get_guild(int(raw))

        lowered = raw.casefold()
        exact = [guild for guild in self.bot.guilds if guild.name.casefold() == lowered]
        if exact:
            return sorted(exact, key=lambda guild: guild.id)[0]

        partial = [guild for guild in self.bot.guilds if lowered in guild.name.casefold()]
        if len(partial) == 1:
            return partial[0]
        return None

    def _server_inventory_embed(self) -> discord.Embed:
        embed = discord.Embed(title="NightPaw Server Inventory", color=config.BOT_COLOR)
        guilds = sorted(self.bot.guilds, key=lambda guild: (guild.name.casefold(), guild.id))
        if not guilds:
            embed.description = "Not connected to any guilds."
            return embed

        lines = []
        for guild in guilds[:25]:
            owner_id = getattr(guild, "owner_id", None)
            members = getattr(guild, "member_count", None)
            lines.append(
                f"`{guild.id}` • {guild.name} • owner `{owner_id or 'unknown'}` • members `{members if members is not None else 'unknown'}`"
            )
        embed.description = "\n".join(lines)
        if len(guilds) > 25:
            embed.add_field(name="More", value=f"...and {len(guilds) - 25} more guilds.", inline=False)
        embed.set_footer(text=f"{len(guilds)} guild(s) connected.")
        return embed

    async def _leave_guild(self, guild: discord.Guild, *, block_after: bool, actor_user_id: int) -> str:
        if block_after:
            await block_guild(
                guild.id,
                guild.name,
                reason="Owner-directed self-ban / forced leave",
                actor_user_id=actor_user_id,
            )
        name = guild.name
        guild_id = guild.id
        await guild.leave()
        if block_after:
            return f"Left `{name}` (`{guild_id}`) and marked it as blocked for future joins."
        return f"Left `{name}` (`{guild_id}`)."

    @commands.command(name="serverlist", help="List the exact guilds NightPaw is currently in (Owner DM only)")
    @is_owner_dm_only()
    async def serverlist_prefix(self, ctx):
        await ctx.send(embed=self._server_inventory_embed())

    @app_commands.command(name="serverlist", description="List the exact guilds NightPaw is currently in (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def serverlist_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._server_inventory_embed(), ephemeral=ephemeral)

    @commands.command(name="serverleave", help="Leave one guild by ID or exact name (Owner DM only)")
    @is_owner_dm_only()
    async def serverleave_prefix(self, ctx, *, query: str):
        guild = self._resolve_guild_query(query)
        if guild is None:
            await ctx.send(wolf_wrap("Couldn't resolve that guild. Use `!serverlist` and pass the guild ID for an exact match."))
            return
        await ctx.send(wolf_wrap(await self._leave_guild(guild, block_after=False, actor_user_id=ctx.author.id)))

    @app_commands.command(name="serverleave", description="Leave one guild by ID or exact name (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def serverleave_slash(self, interaction: discord.Interaction, query: str, ephemeral: bool = False):
        guild = self._resolve_guild_query(query)
        if guild is None:
            await interaction.response.send_message(
                wolf_wrap("Couldn't resolve that guild. Use `/serverlist` and pass the guild ID for an exact match."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(wolf_wrap(await self._leave_guild(guild, block_after=False, actor_user_id=interaction.user.id)), ephemeral=ephemeral)

    @commands.command(name="serverban", help="Leave one guild and block future joins to it (Owner DM only)")
    @is_owner_dm_only()
    async def serverban_prefix(self, ctx, *, query: str):
        guild = self._resolve_guild_query(query)
        if guild is None:
            await ctx.send(wolf_wrap("Couldn't resolve that guild. Use `!serverlist` and pass the guild ID for an exact match."))
            return
        await ctx.send(wolf_wrap(await self._leave_guild(guild, block_after=True, actor_user_id=ctx.author.id)))

    @app_commands.command(name="serverban", description="Leave one guild and block future joins to it (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def serverban_slash(self, interaction: discord.Interaction, query: str, ephemeral: bool = False):
        guild = self._resolve_guild_query(query)
        if guild is None:
            await interaction.response.send_message(
                wolf_wrap("Couldn't resolve that guild. Use `/serverlist` and pass the guild ID for an exact match."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(wolf_wrap(await self._leave_guild(guild, block_after=True, actor_user_id=interaction.user.id)), ephemeral=ephemeral)

    @commands.command(name="serverallow", help="Remove a blocked guild from the self-ban list (Owner DM only)")
    @is_owner_dm_only()
    async def serverallow_prefix(self, ctx, guild_id: int):
        removed = await allow_guild(guild_id)
        await ctx.send(wolf_wrap("Blocked guild entry removed." if removed else "That guild was not on the blocked list."))

    @app_commands.command(name="serverallow", description="Remove a blocked guild from the self-ban list (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def serverallow_slash(self, interaction: discord.Interaction, guild_id: str, ephemeral: bool = False):
        try:
            resolved = int(guild_id)
        except ValueError:
            await interaction.response.send_message(wolf_wrap("Guild ID must be numeric."), ephemeral=True)
            return
        removed = await allow_guild(resolved)
        await interaction.response.send_message(wolf_wrap("Blocked guild entry removed." if removed else "That guild was not on the blocked list."), ephemeral=ephemeral)

    @commands.command(name="serverleaveall", help="Leave every current guild NightPaw is in (Owner DM only)")
    @is_owner_dm_only()
    async def serverleaveall_prefix(self, ctx):
        guilds = list(self.bot.guilds)
        if not guilds:
            await ctx.send(wolf_wrap("Not connected to any guilds right now."))
            return
        left: list[str] = []
        for guild in guilds:
            left.append(f"{guild.name} ({guild.id})")
            await guild.leave()
        preview = ", ".join(left[:6])
        if len(left) > 6:
            preview += f", and {len(left) - 6} more"
        await ctx.send(wolf_wrap(f"Left {len(left)} guild(s): {preview}"))

    @app_commands.command(name="serverleaveall", description="Leave every current guild NightPaw is in (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def serverleaveall_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        guilds = list(self.bot.guilds)
        if not guilds:
            await interaction.response.send_message(wolf_wrap("Not connected to any guilds right now."), ephemeral=ephemeral)
            return
        left: list[str] = []
        for guild in guilds:
            left.append(f"{guild.name} ({guild.id})")
            await guild.leave()
        preview = ", ".join(left[:6])
        if len(left) > 6:
            preview += f", and {len(left) - 6} more"
        await interaction.response.send_message(wolf_wrap(f"Left {len(left)} guild(s): {preview}"), ephemeral=ephemeral)

    @commands.command(name="serverblocked", help="Show the blocked/self-banned guild list (Owner DM only)")
    @is_owner_dm_only()
    async def serverblocked_prefix(self, ctx):
        blocked = await list_blocked_guilds()
        embed = discord.Embed(title="Blocked Guilds", color=config.BOT_COLOR)
        if not blocked:
            embed.description = "No blocked guilds stored."
        else:
            embed.description = "\n".join(
                f"`{item['guild_id']}` • {item['guild_name']}" + (f" • {item['reason']}" if item["reason"] else "")
                for item in blocked[:20]
            )
            if len(blocked) > 20:
                embed.add_field(name="More", value=f"...and {len(blocked) - 20} more blocked guilds.", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="serverblocked", description="Show the blocked/self-banned guild list (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    async def serverblocked_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        blocked = await list_blocked_guilds()
        embed = discord.Embed(title="Blocked Guilds", color=config.BOT_COLOR)
        if not blocked:
            embed.description = "No blocked guilds stored."
        else:
            embed.description = "\n".join(
                f"`{item['guild_id']}` • {item['guild_name']}" + (f" • {item['reason']}" if item["reason"] else "")
                for item in blocked[:20]
            )
            if len(blocked) > 20:
                embed.add_field(name="More", value=f"...and {len(blocked) - 20} more blocked guilds.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    @commands.command(name="serverinvite", help="Generate a bot OAuth invite link with preset or custom permissions (Owner DM only)")
    @is_owner_dm_only()
    async def serverinvite_prefix(
        self,
        ctx,
        mode: str = "required",
        *,
        custom_permissions: str = "",
    ):
        mode_name = mode.casefold().strip()
        if mode_name == "custom":
            perms, enabled, invalid = self._parse_custom_permissions(custom_permissions)
            if perms is None:
                await ctx.send(wolf_wrap("For `custom` mode, provide permission names like `view_channel, send_messages, embed_links`."))
                return
            await ctx.send(
                embed=self._invite_embed(
                    mode_label="custom",
                    perms=perms,
                    custom_enabled=enabled,
                    invalid_permissions=invalid,
                )
            )
            return

        if mode_name not in {"minimal", "required", "full"}:
            await ctx.send(wolf_wrap("Use `minimal`, `required`, `full`, or `custom`."))
            return
        await ctx.send(embed=self._invite_embed(mode_label=mode_name, perms=self._invite_permissions_for_mode(mode_name)))

    @app_commands.command(name="serverinvite", description="Generate a bot OAuth invite link with preset or custom permissions", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can use that command.")
    @app_commands.describe(
        mode="Permission preset to use",
        custom_permissions="Comma-separated permission names when mode is custom",
    )
    async def serverinvite_slash(
        self,
        interaction: discord.Interaction,
        mode: Literal["minimal", "required", "full", "custom"] = "required",
        custom_permissions: str = "",
        ephemeral: bool = False,
    ):
        if mode == "custom":
            initial_enabled: list[str] = []
            invalid: list[str] = []
            if custom_permissions.strip():
                _, initial_enabled, invalid = self._parse_custom_permissions(custom_permissions)
            view = InvitePermissionView(
                cog=self,
                owner_id=interaction.user.id,
                initial_selected=initial_enabled,
            )
            embed = self._custom_invite_prompt_embed()
            if invalid:
                embed.add_field(
                    name="Ignored Permission Names",
                    value=", ".join(f"`{name}`" for name in invalid[:15]),
                    inline=False,
                )
            await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
            view.message = await interaction.original_response()
            return

        await interaction.response.send_message(
            embed=self._invite_embed(
                mode_label=mode,
                perms=self._invite_permissions_for_mode(mode),
            )
            ,
            ephemeral=ephemeral,
        )


async def setup(bot):
    await bot.add_cog(Sysadmin(bot))
