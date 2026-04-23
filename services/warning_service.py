from __future__ import annotations

from dataclasses import dataclass

from services.db import connect, ensure_table_columns


@dataclass(slots=True)
class WarningEntry:
    reason: str
    mod_id: int
    mod_name: str
    timestamp: str


async def ensure_schema() -> None:
    async with connect() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                mod_id INTEGER NOT NULL,
                mod_name TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now'))
            )
            """
        )
        await ensure_table_columns(
            db,
            "warnings",
            (
                ("user_id", "INTEGER"),
                ("reason", "TEXT"),
                ("mod_id", "INTEGER"),
                ("mod_name", "TEXT"),
                ("timestamp", "TEXT DEFAULT (datetime('now'))"),
            ),
        )
        await db.commit()


async def add_warning(user_id: int, reason: str, mod_id: int, mod_name: str) -> int:
    async with connect() as db:
        cursor = await db.execute(
            "INSERT INTO warnings (user_id, reason, mod_id, mod_name) VALUES (?, ?, ?, ?)",
            (user_id, reason, mod_id, mod_name),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_warnings(user_id: int) -> list[WarningEntry]:
    async with connect() as db:
        async with db.execute(
            "SELECT reason, mod_id, mod_name, timestamp FROM warnings WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        WarningEntry(
            reason=row["reason"],
            mod_id=row["mod_id"],
            mod_name=row["mod_name"],
            timestamp=row["timestamp"],
        )
        for row in rows
    ]


async def count_warnings(user_id: int) -> int:
    async with connect() as db:
        async with db.execute("SELECT COUNT(*) AS count FROM warnings WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    return int(row["count"]) if row else 0


async def clear_warnings(user_id: int) -> int:
    async with connect() as db:
        cursor = await db.execute("DELETE FROM warnings WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount
