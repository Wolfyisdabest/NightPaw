from __future__ import annotations

from dataclasses import dataclass
import discord

from services.db import connect, ensure_table_columns


@dataclass(slots=True)
class TrustedMember:
    user_id: int
    username: str
    added_by_id: int
    added_by_name: str


async def ensure_schema() -> None:
    async with connect() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS trusted (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_by_id INTEGER,
                added_by_name TEXT
            )
            """
        )
        await ensure_table_columns(
            db,
            "trusted",
            (
                ("username", "TEXT"),
                ("added_by_id", "INTEGER"),
                ("added_by_name", "TEXT"),
            ),
        )
        await db.commit()


async def is_trusted_user(user_id: int, owner_id: int) -> bool:
    if user_id == owner_id:
        return True
    async with connect() as db:
        async with db.execute("SELECT 1 FROM trusted WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None


async def list_trusted() -> list[TrustedMember]:
    async with connect() as db:
        async with db.execute(
            "SELECT user_id, username, added_by_id, added_by_name FROM trusted ORDER BY username COLLATE NOCASE ASC"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        TrustedMember(
            user_id=row["user_id"],
            username=row["username"],
            added_by_id=row["added_by_id"],
            added_by_name=row["added_by_name"],
        )
        for row in rows
    ]


async def add_trusted(
    user: discord.User | discord.Member,
    added_by: discord.User | discord.Member,
) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO trusted (user_id, username, added_by_id, added_by_name) VALUES (?, ?, ?, ?)",
            (user.id, str(user), added_by.id, str(added_by)),
        )
        await db.commit()
        return cursor.rowcount > 0


async def remove_trusted(user_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute("DELETE FROM trusted WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0


async def clear_trusted() -> int:
    async with connect() as db:
        cursor = await db.execute("DELETE FROM trusted")
        await db.commit()
        return cursor.rowcount
