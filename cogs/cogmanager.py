from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import os
import config
from config import wolf_wrap
from checks import is_owner_slash

COGS_DIR = "./cogs"
# This cog cannot be unloaded
PROTECTED_COGS = {"cogs.cogmanager"}

def is_owner_dm_only():
    async def predicate(ctx):
        if ctx.author.id != config.OWNER_ID:
            return False
        if not isinstance(ctx.channel, discord.DMChannel):
            await ctx.send(wolf_wrap("Cog management only works in my DMs."))
            return False
        return True
    return commands.check(predicate)

class CogManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _cog_path(self, name: str) -> str:
        """Normalize cog name to dotted path."""
        name = name.replace("/", ".").replace("\\", ".")
        if not name.startswith("cogs."):
            name = f"cogs.{name}"
        return name.rstrip(".py").replace(".py", "")

    def _available_cogs(self) -> list[str]:
        """Scan cogs/ directory for all .py files."""
        try:
            return sorted([
                f"cogs.{f[:-3]}"
                for f in os.listdir(COGS_DIR)
                if f.endswith(".py") and not f.startswith("_")
            ])
        except Exception:
            return []

    def _loaded_cogs(self) -> list[str]:
        return sorted(self.bot.extensions.keys())

    def _status_embed(self) -> discord.Embed:
        available = set(self._available_cogs())
        loaded = set(self._loaded_cogs())
        unloaded = available - loaded

        embed = discord.Embed(title="🧩 Cog Manager", color=config.BOT_COLOR)

        loaded_str = "\n".join(f"✅ `{c.replace('cogs.', '')}`" for c in sorted(loaded)) or "None"
        embed.add_field(name=f"Loaded ({len(loaded)})", value=loaded_str, inline=False)

        if unloaded:
            unloaded_str = "\n".join(f"⭕ `{c.replace('cogs.', '')}`" for c in sorted(unloaded))
            embed.add_field(name=f"Available but not loaded ({len(unloaded)})", value=unloaded_str, inline=False)

        embed.set_footer(text=f"{len(loaded)}/{len(available)} cogs loaded • Protected: cogmanager")
        return embed

    # ── Load ──────────────────────────────────────────────────────────────────

    async def _load(self, send, cog: str):
        path = self._cog_path(cog)
        try:
            await self.bot.load_extension(path)
            await self.bot.tree.sync()
            await send(wolf_wrap(f"✅ Loaded `{path}` and synced slash commands."))
        except commands.ExtensionAlreadyLoaded:
            await send(wolf_wrap(f"`{path}` is already loaded."))
        except commands.ExtensionNotFound:
            await send(wolf_wrap(f"Couldn't find `{path}`. Make sure the file exists in `cogs/`."))
        except Exception as e:
            await send(wolf_wrap(f"Failed to load `{path}`: `{e}`"))

    @commands.command(name="cogload", help="Load a cog by name (Owner DM only)")
    @is_owner_dm_only()
    async def cogload_prefix(self, ctx, cog: str):
        await self._load(ctx.send, cog)

    @app_commands.command(name="cogload", description="Load a new or unloaded cog (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can manage cogs.")
    async def cogload_slash(self, interaction: discord.Interaction, cog: str, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await self._load(lambda *args, **kwargs: interaction.followup.send(*args, ephemeral=ephemeral, **kwargs), cog)

    # ── Unload ────────────────────────────────────────────────────────────────

    async def _unload(self, send, cog: str):
        path = self._cog_path(cog)
        if path in PROTECTED_COGS:
            await send(wolf_wrap(f"`{path}` is protected and cannot be unloaded."))
            return
        try:
            await self.bot.unload_extension(path)
            await self.bot.tree.sync()
            await send(wolf_wrap(f"⭕ Unloaded `{path}` and synced slash commands."))
        except commands.ExtensionNotLoaded:
            await send(wolf_wrap(f"`{path}` isn't loaded."))
        except Exception as e:
            await send(wolf_wrap(f"Failed to unload `{path}`: `{e}`"))

    @commands.command(name="cogunload", help="Unload a cog by name (Owner DM only)")
    @is_owner_dm_only()
    async def cogunload_prefix(self, ctx, cog: str):
        await self._unload(ctx.send, cog)

    @app_commands.command(name="cogunload", description="Unload a cog (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can manage cogs.")
    async def cogunload_slash(self, interaction: discord.Interaction, cog: str, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await self._unload(lambda *args, **kwargs: interaction.followup.send(*args, ephemeral=ephemeral, **kwargs), cog)

    # ── Reload ────────────────────────────────────────────────────────────────

    async def _reload(self, send, cog: str):
        path = self._cog_path(cog)
        try:
            await self.bot.reload_extension(path)
            await self.bot.tree.sync()
            await send(wolf_wrap(f"🔄 Reloaded `{path}` and synced slash commands."))
        except commands.ExtensionNotLoaded:
            # Try loading it instead
            try:
                await self.bot.load_extension(path)
                await self.bot.tree.sync()
                await send(wolf_wrap(f"✅ `{path}` wasn't loaded — loaded it fresh and synced."))
            except Exception as e:
                await send(wolf_wrap(f"Failed to load `{path}`: `{e}`"))
        except commands.ExtensionNotFound:
            await send(wolf_wrap(f"Couldn't find `{path}`."))
        except Exception as e:
            await send(wolf_wrap(f"Failed to reload `{path}`: `{e}`"))

    @commands.command(name="cogreload", help="Reload a cog by name (Owner DM only)")
    @is_owner_dm_only()
    async def cogreload_prefix(self, ctx, cog: str):
        await self._reload(ctx.send, cog)

    @app_commands.command(name="cogreload", description="Reload a cog (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can manage cogs.")
    async def cogreload_slash(self, interaction: discord.Interaction, cog: str, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await self._reload(lambda *args, **kwargs: interaction.followup.send(*args, ephemeral=ephemeral, **kwargs), cog)

    # ── Reload all ────────────────────────────────────────────────────────────

    async def _reload_all(self, send):
        loaded = [c for c in self._loaded_cogs() if c not in PROTECTED_COGS]
        results = []
        failed = 0
        for path in loaded:
            try:
                await self.bot.reload_extension(path)
                results.append(f"✅ `{path.replace('cogs.', '')}`")
            except Exception as e:
                results.append(f"❌ `{path.replace('cogs.', '')}` — {e}")
                failed += 1
        await self.bot.tree.sync()
        summary = "\n".join(results) or "Nothing to reload."
        status = f"{'⚠️' if failed else '✅'} Reloaded {len(loaded) - failed}/{len(loaded)} cogs."
        embed = discord.Embed(title="🔄 Reload All", description=summary, color=config.BOT_COLOR)
        embed.set_footer(text=status)
        await send(embed=embed)

    @commands.command(name="cogreloadall", help="Reload all loaded cogs (Owner DM only)")
    @is_owner_dm_only()
    async def cogreloadall_prefix(self, ctx):
        await self._reload_all(ctx.send)

    @app_commands.command(name="cogreloadall", description="Reload all loaded cogs (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can manage cogs.")
    async def cogreloadall_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await self._reload_all(lambda *args, **kwargs: interaction.followup.send(*args, ephemeral=ephemeral, **kwargs))

    # ── Load all unloaded ─────────────────────────────────────────────────────

    async def _loadnew(self, send):
        available = set(self._available_cogs())
        loaded = set(self._loaded_cogs())
        new = available - loaded
        if not new:
            await send(wolf_wrap("No unloaded cogs found. Everything is already running."))
            return
        results = []
        for path in sorted(new):
            try:
                await self.bot.load_extension(path)
                results.append(f"✅ `{path.replace('cogs.', '')}`")
            except Exception as e:
                results.append(f"❌ `{path.replace('cogs.', '')}` — {e}")
        await self.bot.tree.sync()
        embed = discord.Embed(
            title="✅ Load New Cogs",
            description="\n".join(results),
            color=config.BOT_COLOR
        )
        embed.set_footer(text="Slash commands synced.")
        await send(embed=embed)

    @commands.command(name="cogloadnew", help="Load any unloaded cogs found in cogs/ (Owner DM only)")
    @is_owner_dm_only()
    async def cogloadnew_prefix(self, ctx):
        await self._loadnew(ctx.send)

    @app_commands.command(name="cogloadnew", description="Load any new unloaded cogs in cogs/ (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can manage cogs.")
    async def cogloadnew_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.defer(ephemeral=ephemeral)
        await self._loadnew(lambda *args, **kwargs: interaction.followup.send(*args, ephemeral=ephemeral, **kwargs))

    # ── Status ────────────────────────────────────────────────────────────────

    @commands.command(name="cogstatus", help="Show loaded and available cogs (Owner DM only)")
    @is_owner_dm_only()
    async def cogstatus_prefix(self, ctx):
        await ctx.send(embed=self._status_embed())

    @app_commands.command(name="cogstatus", description="Show loaded and available cogs (Owner only)", extras={"category": "owner"})
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @is_owner_slash("Only the Alpha can manage cogs.")
    async def cogstatus_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._status_embed(), ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(CogManager(bot))
