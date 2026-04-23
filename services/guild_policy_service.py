from __future__ import annotations

from datetime import datetime, timezone

from services.db import connect


async def ensure_schema() -> None:
    async with connect() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS blocked_guilds (
                guild_id INTEGER PRIMARY KEY,
                guild_name TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                actor_user_id INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


async def block_guild(guild_id: int, guild_name: str, *, reason: str = "", actor_user_id: int = 0) -> None:
    await ensure_schema()
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO blocked_guilds (guild_id, guild_name, reason, actor_user_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                guild_name = excluded.guild_name,
                reason = excluded.reason,
                actor_user_id = excluded.actor_user_id,
                created_at = excluded.created_at
            """,
            (
                guild_id,
                guild_name[:200],
                reason[:500],
                actor_user_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def allow_guild(guild_id: int) -> bool:
    await ensure_schema()
    async with connect() as db:
        cursor = await db.execute("DELETE FROM blocked_guilds WHERE guild_id = ?", (guild_id,))
        await db.commit()
        return bool(cursor.rowcount)


async def get_blocked_guild(guild_id: int) -> dict[str, str | int] | None:
    await ensure_schema()
    async with connect() as db:
        async with db.execute(
            "SELECT guild_id, guild_name, reason, actor_user_id, created_at FROM blocked_guilds WHERE guild_id = ?",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "guild_id": int(row["guild_id"]),
        "guild_name": str(row["guild_name"]),
        "reason": str(row["reason"] or ""),
        "actor_user_id": int(row["actor_user_id"] or 0),
        "created_at": str(row["created_at"]),
    }


async def list_blocked_guilds() -> list[dict[str, str | int]]:
    await ensure_schema()
    async with connect() as db:
        async with db.execute(
            "SELECT guild_id, guild_name, reason, actor_user_id, created_at FROM blocked_guilds ORDER BY guild_name COLLATE NOCASE"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            "guild_id": int(row["guild_id"]),
            "guild_name": str(row["guild_name"]),
            "reason": str(row["reason"] or ""),
            "actor_user_id": int(row["actor_user_id"] or 0),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]
