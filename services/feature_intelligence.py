from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import inspect

import discord
from discord.ext import commands

from services.rust_bridge import normalize_message

ROOT = Path(__file__).resolve().parent.parent


def _safe_help(text: str | None, limit: int = 260) -> str:
    if not text:
        return "No description provided."
    return " ".join(text.split())[:limit]


def _source_hint(obj) -> str | None:
    try:
        file = inspect.getsourcefile(obj)
    except Exception:
        return None
    if not file:
        return None
    try:
        rel = Path(file).resolve().relative_to(ROOT)
        return rel.as_posix()
    except Exception:
        return Path(file).name


def _prefix_metadata(cmd: commands.Command) -> dict:
    aliases = sorted(set(cmd.aliases))
    return {
        "name": cmd.name,
        "qualified_name": cmd.qualified_name,
        "style": "prefix",
        "usage": f"!{cmd.qualified_name}",
        "description": _safe_help(cmd.help),
        "aliases": aliases,
        "hidden": bool(cmd.hidden),
        "checks": [getattr(check, "__name__", "custom-check") for check in getattr(cmd, "checks", [])],
        "category": infer_command_category(prefix_cmd=cmd),
    }


def _slash_metadata(cmd: app_commands.Command) -> dict:
    return {
        "name": cmd.name,
        "qualified_name": cmd.qualified_name,
        "style": "slash",
        "usage": f"/{cmd.qualified_name}",
        "description": _safe_help(getattr(cmd, "description", None)),
        "aliases": [],
        "hidden": False,
        "checks": [],
        "category": infer_command_category(slash_cmd=cmd),
    }


# Local import type hint compatibility for app_commands without runtime circulars.
from discord import app_commands  # noqa: E402


def infer_command_category(
    *,
    prefix_cmd: commands.Command | None = None,
    slash_cmd: app_commands.Command | None = None,
) -> str:
    if slash_cmd is not None:
        extras = getattr(slash_cmd, "extras", {}) or {}
        if extras.get("category"):
            value = str(extras["category"])
            return "serveradmin" if value == "admin" else value

    checks: list[str] = []
    help_text = ""
    command_name = ""

    if prefix_cmd is not None:
        checks.extend(getattr(check, "__name__", "custom-check") for check in getattr(prefix_cmd, "checks", []))
        help_text = str(prefix_cmd.help or "")
        command_name = prefix_cmd.name
    elif slash_cmd is not None:
        help_text = str(getattr(slash_cmd, "description", "") or "")
        command_name = slash_cmd.name

    lower_name = command_name.casefold()
    combined = normalize_message(f"{command_name} {help_text} {' '.join(checks)}")

    admin_names = {
        "aisetchannel", "aiclearchannel", "aienable", "aidisable", "aimentions",
        "aismart", "aismartreplies", "aiactions", "aiprompt", "aiclearhistory", "aisetnote",
        "aigetnote", "aiclearnote",
    }
    if lower_name in admin_names:
        return "aiconfig"

    if "admin/owner only" in combined:
        return "serveradmin"
    if any(token in combined for token in ("owner only", "alpha only", "owner dm only", "is_owner", "owner_dm")):
        return "owner"
    if any(token in combined for token in ("trusted", "pack member", "pack members", "owner_or_trusted")):
        return "trusted"
    if any(
        token in combined
        for token in (
            "manage server", "administrator", "manage messages", "manage roles",
            "kick a member", "ban a member", "timeout a member", "warn a member",
            "remove a timeout", "delete a number of messages", "set the server ai",
            "clear the server ai", "enable ai in this server", "disable ai in this server",
            "server-specific ai instruction", "persistent ai note",
        )
    ):
        return "serveradmin"
    return "general"


def infer_command_section(
    *,
    prefix_cmd: commands.Command | None = None,
    slash_cmd: app_commands.Command | None = None,
) -> str:
    command_name = ""
    module_name = ""
    cog_name = ""

    if prefix_cmd is not None:
        command_name = prefix_cmd.name.casefold()
        module_name = str(getattr(prefix_cmd.callback, "__module__", "")).casefold()
        cog_name = str(getattr(prefix_cmd, "cog_name", "")).casefold()
    elif slash_cmd is not None:
        command_name = slash_cmd.name.casefold()
        module_name = str(getattr(slash_cmd.callback, "__module__", "")).casefold()
        parent = getattr(slash_cmd, "binding", None)
        cog_name = str(parent.__class__.__name__ if parent is not None else "").casefold()

    combined = normalize_message(f"{command_name} {module_name} {cog_name}")
    if any(token in combined for token in ("cogs.ai", " ai ", "ai.")) or command_name.startswith("ai"):
        if infer_command_category(prefix_cmd=prefix_cmd, slash_cmd=slash_cmd) == "aiconfig":
            return "aiconfig"
        return "ai"
    if any(token in combined for token in ("moderation", "automod")):
        return "moderation"
    if any(token in combined for token in ("packhealth", "sysadmin", "cogmanager")):
        return "system"
    if any(token in combined for token in ("pack", "trusted")):
        return "pack"
    if any(token in combined for token in ("help",)):
        return "help"
    if any(token in combined for token in ("lore", "wolf_lore", "wolfy", "kael", "matthijs", "blaze")):
        return "lore"
    if any(token in combined for token in ("utility", "avatar", "birthday")):
        return "utility"
    return "utility"


def build_feature_snapshot(bot: commands.Bot) -> dict:
    cogs_out: list[dict] = []
    category_counts: dict[str, int] = defaultdict(int)

    for cog_name, cog in sorted(bot.cogs.items()):
        if cog_name == "AI":
            continue

        prefix_cmds = sorted(cog.get_commands(), key=lambda c: c.name)
        slash_cmds = sorted(getattr(cog, "__cog_app_commands__", []), key=lambda c: c.name)

        commands_out: list[dict] = []
        seen: set[str] = set()

        for cmd in prefix_cmds:
            if cmd.hidden:
                continue
            matching_slash = next((item for item in slash_cmds if item.name == cmd.name), None)
            meta = _prefix_metadata(cmd)
            meta["category"] = infer_command_category(prefix_cmd=cmd, slash_cmd=matching_slash)
            commands_out.append(meta)
            seen.add(cmd.name)

        for cmd in slash_cmds:
            if cmd.name in seen:
                continue
            meta = _slash_metadata(cmd)
            commands_out.append(meta)

        for item in commands_out:
            category_counts[item.get("category", "general")] += 1

        cogs_out.append(
            {
                "name": cog_name,
                "source": _source_hint(cog.__class__),
                "description": _safe_help(getattr(cog, "description", None) or cog.__class__.__doc__),
                "commands": sorted(commands_out, key=lambda x: (x["style"], x["name"])),
            }
        )

    return {
        "bot_name": getattr(getattr(bot, "user", None), "name", "NightPaw"),
        "cogs": cogs_out,
        "cog_count": len(cogs_out),
        "command_count": sum(len(c["commands"]) for c in cogs_out),
        "categories": dict(sorted(category_counts.items())),
    }


def render_feature_summary(snapshot: dict, max_commands_per_cog: int = 8) -> str:
    lines: list[str] = []
    lines.append(
        f"Live command snapshot: {snapshot['cog_count']} cogs, {snapshot['command_count']} public commands."
    )
    categories = snapshot.get("categories") or {}
    if categories:
        rendered_categories = ", ".join(f"{name}={count}" for name, count in categories.items())
        lines.append(f"Command categories: {rendered_categories}.")
    lines.append(
        "When someone asks what you can do, answer from this snapshot first. Do not invent commands, permissions, or features."
    )

    for cog in snapshot["cogs"]:
        lines.append(f"Cog: {cog['name']} — {cog['description']}")
        commands_list = cog["commands"][:max_commands_per_cog]
        if not commands_list:
            continue
        rendered = "; ".join(
            f"{item['usage']} = {item['description']}" for item in commands_list
        )
        lines.append(f"Commands: {rendered}")

    return "\n".join(lines)


def render_feature_embed(snapshot: dict) -> discord.Embed:
    categories = snapshot.get("categories") or {}
    category_text = " • ".join(f"{k}: {v}" for k, v in categories.items()) or "No categories"
    embed = discord.Embed(
        title="🐺 NightPaw AI Status",
        description=(
            f"Live feature snapshot: **{snapshot['cog_count']}** cogs • **{snapshot['command_count']}** commands\n"
            f"Categories: {category_text}"
        ),
        color=0x8B0000,
    )
    for cog in snapshot["cogs"][:12]:
        cmds = cog["commands"][:5]
        value = "\n".join(f"• `{c['usage']}`" for c in cmds) or "No public commands."
        embed.add_field(name=cog["name"], value=value[:1024], inline=False)
    embed.set_footer(text="Built from loaded cogs and commands at runtime.")
    return embed
