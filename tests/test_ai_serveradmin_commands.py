from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from cogs.ai import AI
from cogs.help import Help
from cogs.packhealth import PackHealth
from cogs.sysadmin import Sysadmin
from services.feature_intelligence import infer_command_category, infer_command_section


class FakePermissions:
    def __init__(self, *, manage_guild: bool = False):
        self.manage_guild = manage_guild


class FakeAuthor:
    def __init__(self, user_id: int, *, manage_guild: bool = False):
        self.id = user_id
        self.guild_permissions = FakePermissions(manage_guild=manage_guild)


class FakeGuild:
    def __init__(self, guild_id: int):
        self.id = guild_id

    def get_member(self, user_id: int):
        return None


class FakeContext:
    def __init__(self, *, guild, author):
        self.guild = guild
        self.author = author
        self.sent_messages: list[str] = []
        self.channel = SimpleNamespace()

    async def send(self, message: str):
        self.sent_messages.append(message)


class FakeChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id


class FakeMessage:
    def __init__(self, *, content: str, author, guild, channel, mentions=None):
        self.id = 999
        self.content = content
        self.author = author
        self.guild = guild
        self.channel = channel
        self.mentions = mentions or []
        self.attachments = []
        self.created_at = None
        self.reference = None


def _make_ai_cog() -> AI:
    bot = SimpleNamespace(guilds=[], latency=0.0, cogs={}, user=SimpleNamespace(id=555, mention="<@555>"))
    return AI(bot)


def _make_basic_bot():
    return SimpleNamespace(guilds=[], latency=0.0, cogs={}, user=SimpleNamespace(id=555, mention="<@555>"))


@pytest.mark.parametrize(
    ("command_name", "args"),
    [
        ("aisetchannel_prefix", (SimpleNamespace(id=777, mention="#den"),)),
        ("aiclearchannel_prefix", ()),
        ("aienable_prefix", ()),
        ("aidisable_prefix", ()),
        ("aimentions_prefix", ("on",)),
        ("aismart_prefix", ("on",)),
        ("aiactions_prefix", ("on",)),
        ("aiprompt_prefix", ()),
        ("aiclearhistory_prefix", ()),
        ("aigetnote_prefix", (SimpleNamespace(id=321),)),
        ("aiclearnote_prefix", (SimpleNamespace(id=321),)),
    ],
)
def test_serveradmin_prefix_commands_use_guild_only_error_in_dms(monkeypatch, command_name, args):
    cog = _make_ai_cog()
    ctx = FakeContext(guild=None, author=FakeAuthor(user_id=123))
    admin_check = AsyncMock(return_value=False)
    monkeypatch.setattr(cog, "_is_admin_here", admin_check)

    command = getattr(AI, command_name)
    asyncio.run(command.callback(cog, ctx, *args))

    assert ctx.sent_messages == [config.wolf_wrap("This command can only be used inside a server.")]
    admin_check.assert_not_awaited()


def test_aisetnote_prefix_uses_guild_only_error_in_dms(monkeypatch):
    cog = _make_ai_cog()
    ctx = FakeContext(guild=None, author=FakeAuthor(user_id=123))
    admin_check = AsyncMock(return_value=False)
    monkeypatch.setattr(cog, "_is_admin_here", admin_check)

    asyncio.run(AI.aisetnote_prefix.callback(cog, ctx, SimpleNamespace(id=321), note="note"))

    assert ctx.sent_messages == [config.wolf_wrap("This command can only be used inside a server.")]
    admin_check.assert_not_awaited()


@pytest.mark.parametrize(
    "command_name",
    ["aiclearhistory_prefix", "aigetnote_prefix", "aiclearnote_prefix"],
)
def test_server_only_ai_config_commands_keep_permission_error_in_guild(monkeypatch, command_name):
    cog = _make_ai_cog()
    ctx = FakeContext(guild=FakeGuild(42), author=FakeAuthor(user_id=123))
    admin_check = AsyncMock(return_value=False)
    monkeypatch.setattr(cog, "_is_admin_here", admin_check)

    args = ()
    if command_name in {"aigetnote_prefix", "aiclearnote_prefix"}:
        args = (SimpleNamespace(id=321),)
        asyncio.run(getattr(AI, command_name).callback(cog, ctx, *args))
    else:
        asyncio.run(AI.aiclearhistory_prefix.callback(cog, ctx))

    assert ctx.sent_messages == [config.wolf_wrap("You need Manage Server permission for that here.")]
    admin_check.assert_awaited_once_with(ctx)


def test_aisetnote_prefix_keeps_permission_error_in_guild(monkeypatch):
    cog = _make_ai_cog()
    ctx = FakeContext(guild=FakeGuild(42), author=FakeAuthor(user_id=123))
    admin_check = AsyncMock(return_value=False)
    monkeypatch.setattr(cog, "_is_admin_here", admin_check)

    asyncio.run(AI.aisetnote_prefix.callback(cog, ctx, SimpleNamespace(id=321), note="note"))

    assert ctx.sent_messages == [config.wolf_wrap("You need Manage Server permission for that here.")]
    admin_check.assert_awaited_once_with(ctx)


def test_serveradmin_prefix_command_keeps_permission_error_in_guild(monkeypatch):
    cog = _make_ai_cog()
    ctx = FakeContext(guild=FakeGuild(42), author=FakeAuthor(user_id=123))
    admin_check = AsyncMock(return_value=False)
    monkeypatch.setattr(cog, "_is_admin_here", admin_check)

    asyncio.run(AI.aienable_prefix.callback(cog, ctx))

    assert ctx.sent_messages == [config.wolf_wrap("You need Manage Server permission for that here.")]
    admin_check.assert_awaited_once_with(ctx)


def test_serveradmin_prefix_command_still_updates_guild_settings_for_admin(monkeypatch):
    cog = _make_ai_cog()
    ctx = FakeContext(guild=FakeGuild(42), author=FakeAuthor(user_id=123, manage_guild=True))
    monkeypatch.setattr(cog, "_is_admin_here", AsyncMock(return_value=True))
    upsert_mock = AsyncMock()
    monkeypatch.setattr("cogs.ai.upsert_guild_settings", upsert_mock)

    asyncio.run(AI.aienable_prefix.callback(cog, ctx))

    upsert_mock.assert_awaited_once_with(42, enabled=1)
    assert ctx.sent_messages == [config.wolf_wrap("AI has been enabled in this server.")]


def test_starts_with_real_command_only_checks_message_start(monkeypatch):
    cog = _make_ai_cog()
    message = FakeMessage(
        content="hello !help",
        author=SimpleNamespace(id=123, bot=False),
        guild=FakeGuild(42),
        channel=FakeChannel(100),
    )
    get_context = AsyncMock(return_value=SimpleNamespace(valid=True))
    monkeypatch.setattr(cog.bot, "get_context", get_context, raising=False)

    result = asyncio.run(cog._starts_with_real_command(message))

    assert result is False
    get_context.assert_not_awaited()


def test_starts_with_real_command_requires_a_real_registered_command(monkeypatch):
    cog = _make_ai_cog()
    message = FakeMessage(
        content="!notacommand hello there",
        author=SimpleNamespace(id=123, bot=False),
        guild=FakeGuild(42),
        channel=FakeChannel(100),
    )
    monkeypatch.setattr(cog.bot, "get_context", AsyncMock(return_value=SimpleNamespace(valid=False)), raising=False)

    result = asyncio.run(cog._starts_with_real_command(message))

    assert result is False


def test_ai_channel_message_is_ignored_when_smart_replies_are_disabled(monkeypatch):
    cog = _make_ai_cog()
    author = SimpleNamespace(id=123, bot=False, display_name="Tester", name="Tester")
    channel = FakeChannel(200)
    message = FakeMessage(content="hello there", author=author, guild=FakeGuild(42), channel=channel)
    chat_and_send = AsyncMock()

    @asynccontextmanager
    async def fake_processing_feedback(destination, *, enabled=True):
        yield

    monkeypatch.setattr("cogs.ai.get_guild_settings", AsyncMock(return_value={
        "enabled": 1,
        "channel_id": 200,
        "mention_enabled": 1,
        "channel_chat_enabled": 1,
        "commands_enabled": 1,
        "actions_enabled": 0,
        "smart_replies_enabled": 0,
        "custom_prompt": "",
        "reply_cooldown_seconds": 3,
    }))
    monkeypatch.setattr(cog, "_record_context", AsyncMock())
    monkeypatch.setattr(cog, "_starts_with_real_command", AsyncMock(return_value=False))
    monkeypatch.setattr(cog, "_maybe_handle_avatar_request", AsyncMock(return_value=False))
    monkeypatch.setattr(cog, "_collect_processed_attachments", AsyncMock(return_value=None))
    monkeypatch.setattr(cog, "_chat_and_send", chat_and_send)
    monkeypatch.setattr(cog, "_processing_feedback", fake_processing_feedback)

    asyncio.run(cog.on_message(message))

    chat_and_send.assert_not_awaited()


def test_mentions_still_reply_outside_the_ai_channel(monkeypatch):
    cog = _make_ai_cog()
    author = SimpleNamespace(id=123, bot=False, display_name="Tester", name="Tester")
    outside_channel = FakeChannel(201)
    message = FakeMessage(
        content="<@555> hey can you help?",
        author=author,
        guild=FakeGuild(42),
        channel=outside_channel,
        mentions=[cog.bot.user],
    )
    chat_and_send = AsyncMock()

    @asynccontextmanager
    async def fake_processing_feedback(destination, *, enabled=True):
        yield

    monkeypatch.setattr("cogs.ai.get_guild_settings", AsyncMock(return_value={
        "enabled": 1,
        "channel_id": 200,
        "mention_enabled": 1,
        "channel_chat_enabled": 1,
        "commands_enabled": 1,
        "actions_enabled": 0,
        "smart_replies_enabled": 0,
        "custom_prompt": "server prompt",
        "reply_cooldown_seconds": 3,
    }))
    monkeypatch.setattr(cog, "_record_context", AsyncMock())
    monkeypatch.setattr(cog, "_starts_with_real_command", AsyncMock(return_value=False))
    monkeypatch.setattr(cog, "_maybe_handle_avatar_request", AsyncMock(return_value=False))
    monkeypatch.setattr(cog, "_collect_processed_attachments", AsyncMock(return_value=None))
    monkeypatch.setattr(cog, "_chat_and_send", chat_and_send)
    monkeypatch.setattr(cog, "_processing_feedback", fake_processing_feedback)
    monkeypatch.setattr(cog, "_cooldown_ok", lambda *args, **kwargs: True)

    asyncio.run(cog.on_message(message))

    chat_and_send.assert_awaited_once()
    assert chat_and_send.await_args.kwargs["custom_prompt"] == "server prompt"


def test_ai_config_commands_are_classified_separately():
    cog = _make_ai_cog()
    prefix_map = {cmd.name: cmd for cmd in cog.get_commands()}
    slash_map = {cmd.name: cmd for cmd in getattr(cog, "__cog_app_commands__", [])}

    for command_name in ("aisetchannel", "aiclearchannel", "aienable", "aidisable", "aimentions", "aismart", "aiactions", "aiprompt", "aiclearhistory", "aisetnote", "aigetnote", "aiclearnote"):
        assert infer_command_category(prefix_cmd=prefix_map[command_name], slash_cmd=slash_map.get(command_name)) == "aiconfig"
        assert infer_command_section(prefix_cmd=prefix_map[command_name], slash_cmd=slash_map.get(command_name)) == "aiconfig"


def test_help_hides_ai_config_in_dms_and_leaves_serveradmin_empty():
    bot = _make_basic_bot()
    ai_cog = AI(bot)
    bot.cogs = {"AI": ai_cog}
    help_cog = Help(bot)

    dm_sections = help_cog._collect_entries(trusted=False, is_admin=False, is_owner=False)
    assert dm_sections["aiconfig"] == []

    guild_sections = help_cog._collect_entries(trusted=False, is_admin=True, is_owner=False)
    assert guild_sections["aiconfig"]
    assert guild_sections["serveradmin"] == []


def test_botping_is_public_and_sysinfo_is_removed():
    bot = _make_basic_bot()
    sysadmin = Sysadmin(bot)
    prefix_map = {cmd.name: cmd for cmd in sysadmin.get_commands()}
    slash_map = {cmd.name: cmd for cmd in getattr(sysadmin, "__cog_app_commands__", [])}

    assert "sysinfo" not in prefix_map
    assert "sysinfo" not in slash_map
    assert "sysinfo" not in AI.ACTION_ALLOWLIST

    assert prefix_map["botping"].checks == []
    assert infer_command_category(prefix_cmd=prefix_map["botping"], slash_cmd=slash_map["botping"]) == "general"


def test_packhealth_embeds_stay_within_discord_field_limit():
    bot = _make_basic_bot()
    bot.cogs = {}
    packhealth = PackHealth(bot)

    embeds = asyncio.run(packhealth._build_health_embeds())

    assert len(embeds) >= 2
    assert all(len(embed.fields) <= 25 for embed in embeds)
