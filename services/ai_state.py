from __future__ import annotations

from collections.abc import Iterable
import asyncio
import logging

from services.db import connect, ensure_table_columns

logger = logging.getLogger(__name__)


_SCHEMA_READY = False
_SCHEMA_LOCK = asyncio.Lock()




def _retryable_db_error(exc: Exception) -> bool:
    lowered = str(exc).casefold()
    return any(token in lowered for token in (
        "no such table",
        "disk i/o error",
        "database is locked",
        "database disk image is malformed",
        "readonly database",
    ))


async def _run_db(operation, default=None):
    global _SCHEMA_READY
    last_exc = None
    for attempt in range(2):
        try:
            return await operation()
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _retryable_db_error(exc):
                _SCHEMA_READY = False
                try:
                    await ensure_schema(force=True)
                except Exception:
                    pass
                await asyncio.sleep(0.05)
                continue
            logger.warning("AI state DB operation failed: %s", exc, exc_info=True)
            return default
    logger.warning("AI state DB operation failed after retry: %s", last_exc, exc_info=True)
    return default

DEFAULT_GUILD_SETTINGS: dict[str, int | str | None] = {
    "enabled": 1,
    "channel_id": None,
    "mention_enabled": 1,
    "channel_chat_enabled": 1,
    "commands_enabled": 1,
    "actions_enabled": 0,
    "smart_replies_enabled": 1,
    "custom_prompt": "",
    "reply_cooldown_seconds": 3,
}


async def ensure_schema(force: bool = False) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY and not force:
        return

    async with _SCHEMA_LOCK:
        if _SCHEMA_READY and not force:
            return
        async with connect() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    channel_id INTEGER,
                    mention_enabled INTEGER NOT NULL DEFAULT 1,
                    channel_chat_enabled INTEGER NOT NULL DEFAULT 1,
                    commands_enabled INTEGER NOT NULL DEFAULT 1,
                    actions_enabled INTEGER NOT NULL DEFAULT 0,
                    smart_replies_enabled INTEGER NOT NULL DEFAULT 1,
                    custom_prompt TEXT NOT NULL DEFAULT '',
                    reply_cooldown_seconds INTEGER NOT NULL DEFAULT 3
                )
                """
            )
            await ensure_table_columns(
                db,
                "ai_guild_settings",
                (
                    ("enabled", "INTEGER NOT NULL DEFAULT 1"),
                    ("channel_id", "INTEGER"),
                    ("mention_enabled", "INTEGER NOT NULL DEFAULT 1"),
                    ("channel_chat_enabled", "INTEGER NOT NULL DEFAULT 1"),
                    ("commands_enabled", "INTEGER NOT NULL DEFAULT 1"),
                    ("actions_enabled", "INTEGER NOT NULL DEFAULT 0"),
                    ("smart_replies_enabled", "INTEGER NOT NULL DEFAULT 1"),
                    ("custom_prompt", "TEXT NOT NULL DEFAULT ''"),
                    ("reply_cooldown_seconds", "INTEGER NOT NULL DEFAULT 3"),
                ),
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_type TEXT NOT NULL,
                    scope_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await ensure_table_columns(
                db,
                "ai_history",
                (
                    ("scope_type", "TEXT"),
                    ("scope_id", "INTEGER"),
                    ("user_id", "INTEGER"),
                    ("author_name", "TEXT"),
                    ("role", "TEXT"),
                    ("content", "TEXT"),
                    ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
                ),
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_channel_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await ensure_table_columns(
                db,
                "ai_channel_messages",
                (
                    ("guild_id", "INTEGER"),
                    ("channel_id", "INTEGER"),
                    ("user_id", "INTEGER"),
                    ("author_name", "TEXT"),
                    ("content", "TEXT"),
                    ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
                ),
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_user_notes (
                    user_id INTEGER PRIMARY KEY,
                    note TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await ensure_table_columns(
                db,
                "ai_user_notes",
                (
                    ("note", "TEXT"),
                    ("updated_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
                ),
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_type TEXT NOT NULL,
                    scope_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'misc',
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await ensure_table_columns(
                db,
                "ai_memories",
                (
                    ("scope_type", "TEXT"),
                    ("scope_id", "INTEGER"),
                    ("user_id", "INTEGER"),
                    ("memory_type", "TEXT NOT NULL DEFAULT 'misc'"),
                    ("content", "TEXT"),
                    ("created_at", "TEXT NOT NULL DEFAULT (datetime('now'))"),
                ),
            )
            await db.commit()
        _SCHEMA_READY = True


async def get_guild_settings(guild_id: int) -> dict[str, int | str | None]:
    async def op():
        await ensure_schema()
        async with connect() as db:
            async with db.execute(
                "SELECT * FROM ai_guild_settings WHERE guild_id = ?",
                (guild_id,),
            ) as cursor:
                row = await cursor.fetchone()

        result = {"guild_id": guild_id, **DEFAULT_GUILD_SETTINGS}
        if row is None:
            return result
        result.update(dict(row))
        return result

    return await _run_db(op, {"guild_id": guild_id, **DEFAULT_GUILD_SETTINGS})


async def upsert_guild_settings(guild_id: int, **fields) -> None:
    async def op():
        await ensure_schema()
        current = await get_guild_settings(guild_id)
        current.update(fields)
        async with connect() as db:
            await db.execute(
                """
                INSERT INTO ai_guild_settings (
                    guild_id, enabled, channel_id, mention_enabled, channel_chat_enabled,
                    commands_enabled, actions_enabled, smart_replies_enabled, custom_prompt,
                    reply_cooldown_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    channel_id = excluded.channel_id,
                    mention_enabled = excluded.mention_enabled,
                    channel_chat_enabled = excluded.channel_chat_enabled,
                    commands_enabled = excluded.commands_enabled,
                    actions_enabled = excluded.actions_enabled,
                    smart_replies_enabled = excluded.smart_replies_enabled,
                    custom_prompt = excluded.custom_prompt,
                    reply_cooldown_seconds = excluded.reply_cooldown_seconds
                """,
                (
                    guild_id,
                    int(current["enabled"]),
                    current["channel_id"],
                    int(current["mention_enabled"]),
                    int(current["channel_chat_enabled"]),
                    int(current["commands_enabled"]),
                    int(current["actions_enabled"]),
                    int(current["smart_replies_enabled"]),
                    str(current["custom_prompt"]),
                    int(current["reply_cooldown_seconds"]),
                ),
            )
            await db.commit()

    await _run_db(op, None)


async def add_history(
    scope_type: str,
    scope_id: int,
    user_id: int,
    author_name: str,
    role: str,
    content: str,
) -> None:
    cleaned = " ".join(content.split())[:4000]
    if not cleaned:
        return

    async def op():
        await ensure_schema()
        async with connect() as db:
            await db.execute(
                "INSERT INTO ai_history (scope_type, scope_id, user_id, author_name, role, content) VALUES (?, ?, ?, ?, ?, ?)",
                (scope_type, scope_id, user_id, author_name[:120], role, cleaned),
            )
            await db.execute(
                """
                DELETE FROM ai_history
                WHERE id NOT IN (
                    SELECT id FROM ai_history
                    WHERE scope_type = ? AND scope_id = ?
                    ORDER BY id DESC
                    LIMIT 40
                ) AND scope_type = ? AND scope_id = ?
                """,
                (scope_type, scope_id, scope_type, scope_id),
            )
            await db.commit()

    await _run_db(op, None)


async def get_history(scope_type: str, scope_id: int, limit: int = 12) -> list[dict]:
    async def op():
        await ensure_schema()
        async with connect() as db:
            async with db.execute(
                """
                SELECT user_id, author_name, role, content, created_at
                FROM ai_history
                WHERE scope_type = ? AND scope_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (scope_type, scope_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    return await _run_db(op, [])


async def clear_history(scope_type: str, scope_id: int) -> int:
    async def op():
        await ensure_schema()
        async with connect() as db:
            cursor = await db.execute(
                "DELETE FROM ai_history WHERE scope_type = ? AND scope_id = ?",
                (scope_type, scope_id),
            )
            await db.execute(
                "DELETE FROM ai_memories WHERE scope_type = ? AND scope_id = ?",
                (scope_type, scope_id),
            )
            await db.commit()
            return cursor.rowcount

    return await _run_db(op, 0)


async def record_channel_message(
    guild_id: int,
    channel_id: int,
    user_id: int,
    author_name: str,
    content: str,
) -> None:
    cleaned = " ".join(content.split())[:4000]
    if not cleaned:
        return

    async def op():
        await ensure_schema()
        async with connect() as db:
            await db.execute(
                "INSERT INTO ai_channel_messages (guild_id, channel_id, user_id, author_name, content) VALUES (?, ?, ?, ?, ?)",
                (guild_id, channel_id, user_id, author_name[:120], cleaned),
            )
            await db.execute(
                """
                DELETE FROM ai_channel_messages
                WHERE id NOT IN (
                    SELECT id FROM ai_channel_messages
                    WHERE guild_id = ? AND channel_id = ?
                    ORDER BY id DESC
                    LIMIT 60
                ) AND guild_id = ? AND channel_id = ?
                """,
                (guild_id, channel_id, guild_id, channel_id),
            )
            await db.commit()

    await _run_db(op, None)


async def get_recent_channel_messages(guild_id: int, channel_id: int, limit: int = 12) -> list[dict]:
    async def op():
        await ensure_schema()
        async with connect() as db:
            async with db.execute(
                """
                SELECT user_id, author_name, content, created_at
                FROM ai_channel_messages
                WHERE guild_id = ? AND channel_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (guild_id, channel_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    return await _run_db(op, [])


async def set_user_note(user_id: int, note: str) -> None:
    cleaned = note.strip()[:2000]

    async def op():
        await ensure_schema()
        async with connect() as db:
            await db.execute(
                """
                INSERT INTO ai_user_notes (user_id, note, updated_at) VALUES (?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (user_id, cleaned),
            )
            await db.commit()

    await _run_db(op, None)


async def get_user_note(user_id: int) -> str:
    async def op():
        await ensure_schema()
        async with connect() as db:
            async with db.execute(
                "SELECT note FROM ai_user_notes WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return row["note"] if row else ""

    return await _run_db(op, "")


async def clear_user_note(user_id: int) -> bool:
    async def op():
        await ensure_schema()
        async with connect() as db:
            cursor = await db.execute("DELETE FROM ai_user_notes WHERE user_id = ?", (user_id,))
            await db.commit()
            return cursor.rowcount > 0

    return await _run_db(op, False)


async def remember_fact(
    scope_type: str,
    scope_id: int,
    user_id: int,
    content: str,
) -> bool:
    cleaned = " ".join(content.split())[:500]
    if not cleaned:
        return False

    async def op():
        await ensure_schema()
        memory_type = classify_memory(cleaned)
        async with connect() as db:
            async with db.execute(
                """
                SELECT 1
                FROM ai_memories
                WHERE scope_type = ? AND scope_id = ? AND user_id = ? AND lower(content) = lower(?)
                LIMIT 1
                """,
                (scope_type, scope_id, user_id, cleaned),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is not None:
                return False
            await db.execute(
                """
                INSERT INTO ai_memories (scope_type, scope_id, user_id, memory_type, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope_type, scope_id, user_id, memory_type, cleaned),
            )
            await db.execute(
                """
                DELETE FROM ai_memories
                WHERE id NOT IN (
                    SELECT id FROM ai_memories
                    WHERE scope_type = ? AND scope_id = ? AND user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) AND scope_type = ? AND scope_id = ? AND user_id = ?
                """,
                (
                    scope_type,
                    scope_id,
                    user_id,
                    32,
                    scope_type,
                    scope_id,
                    user_id,
                ),
            )
            await db.commit()
            return True

    return await _run_db(op, False)


async def get_memories(scope_type: str, scope_id: int, user_id: int, limit: int = 8) -> list[str]:
    async def op():
        await ensure_schema()
        async with connect() as db:
            async with db.execute(
                """
                SELECT content
                FROM ai_memories
                WHERE scope_type = ? AND scope_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (scope_type, scope_id, user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row["content"]) for row in reversed(rows)]

    return await _run_db(op, [])


async def get_memory_rows(scope_type: str, scope_id: int, user_id: int, limit: int = 8) -> list[dict]:
    async def op():
        await ensure_schema()
        async with connect() as db:
            async with db.execute(
                """
                SELECT content, memory_type, created_at
                FROM ai_memories
                WHERE scope_type = ? AND scope_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (scope_type, scope_id, user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    return await _run_db(op, [])


def classify_memory(content: str) -> str:
    lowered = (content or "").casefold()
    if any(token in lowered for token in ("favorite", "favourite", "prefer", "like ", "love ", "hate ", "dislike ")):
        return "preference"
    if any(token in lowered for token in ("i am ", "my name is", "i'm ", "my birthday", "my age", "my pronouns")):
        return "identity"
    if any(token in lowered for token in ("project", "nightpaw", "bot", "repo", "codebase", "feature", "command")):
        return "project"
    if any(token in lowered for token in ("owner", "friend", "partner", "trusted", "pack", "developer", "creator")):
        return "relationship"
    return "misc"


async def bulk_store_channel_messages(
    guild_id: int,
    channel_id: int,
    messages: Iterable[tuple[int, str, str]],
) -> None:
    rows = [(guild_id, channel_id, uid, name[:120], " ".join(content.split())[:4000]) for uid, name, content in messages if content.strip()]
    if not rows:
        return

    async def op():
        await ensure_schema()
        async with connect() as db:
            await db.executemany(
                "INSERT INTO ai_channel_messages (guild_id, channel_id, user_id, author_name, content) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            await db.commit()

    await _run_db(op, None)
