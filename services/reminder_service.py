from __future__ import annotations

from dataclasses import dataclass

from services.db import connect, ensure_table_columns


@dataclass(slots=True)
class ReminderEntry:
    id: int
    user_id: int
    channel_id: int | None
    message: str
    fire_at: str


async def ensure_schema() -> None:
    async with connect() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_id INTEGER,
                message TEXT NOT NULL,
                fire_at TEXT NOT NULL
            )
            """
        )
        await ensure_table_columns(
            db,
            "reminders",
            (
                ("user_id", "INTEGER"),
                ("channel_id", "INTEGER"),
                ("message", "TEXT"),
                ("fire_at", "TEXT"),
            ),
        )
        await db.commit()


async def create_reminder(user_id: int, channel_id: int | None, message: str, fire_at: str) -> int:
    async with connect() as db:
        cursor = await db.execute(
            "INSERT INTO reminders (user_id, channel_id, message, fire_at) VALUES (?, ?, ?, ?)",
            (user_id, channel_id, message, fire_at),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_reminders(user_id: int) -> list[ReminderEntry]:
    async with connect() as db:
        async with db.execute(
            "SELECT id, user_id, channel_id, message, fire_at FROM reminders WHERE user_id = ? ORDER BY fire_at ASC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        ReminderEntry(
            id=row["id"],
            user_id=row["user_id"],
            channel_id=row["channel_id"],
            message=row["message"],
            fire_at=row["fire_at"],
        )
        for row in rows
    ]


async def list_all_reminders() -> list[ReminderEntry]:
    async with connect() as db:
        async with db.execute(
            "SELECT id, user_id, channel_id, message, fire_at FROM reminders ORDER BY fire_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        ReminderEntry(
            id=row["id"],
            user_id=row["user_id"],
            channel_id=row["channel_id"],
            message=row["message"],
            fire_at=row["fire_at"],
        )
        for row in rows
    ]


async def delete_reminder(reminder_id: int, user_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_all_reminders(user_id: int) -> int:
    async with connect() as db:
        cursor = await db.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount


async def reminder_belongs_to_user(reminder_id: int, user_id: int) -> bool:
    async with connect() as db:
        async with db.execute(
            "SELECT 1 FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        ) as cursor:
            return await cursor.fetchone() is not None


async def delete_reminder_any(reminder_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await db.commit()
        return cursor.rowcount > 0
