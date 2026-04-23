from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from services.db import connect, ensure_table_columns


@dataclass(slots=True)
class BirthdayEntry:
    user_id: int
    day: int
    month: int
    last_notified_year: int | None


def _validate_day_month(day: int, month: int) -> None:
    try:
        date(2000, month, day)
    except ValueError as exc:
        raise ValueError(f"Invalid birthday date: {day:02d}-{month:02d}") from exc


async def ensure_schema() -> None:
    async with connect() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS birthdays (
                user_id INTEGER PRIMARY KEY,
                day INTEGER NOT NULL,
                month INTEGER NOT NULL,
                last_notified_year INTEGER
            )
            """
        )
        await ensure_table_columns(
            db,
            "birthdays",
            (
                ("day", "INTEGER"),
                ("month", "INTEGER"),
                ("last_notified_year", "INTEGER"),
            ),
        )
        await db.commit()


async def ensure_default_birthday(user_id: int, day: int, month: int) -> None:
    _validate_day_month(day, month)
    async with connect() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO birthdays (user_id, day, month, last_notified_year)
            VALUES (?, ?, ?, NULL)
            """,
            (user_id, day, month),
        )
        await db.commit()


async def upsert_birthday(user_id: int, day: int, month: int) -> None:
    _validate_day_month(day, month)
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO birthdays (user_id, day, month, last_notified_year)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                day = excluded.day,
                month = excluded.month,
                last_notified_year = NULL
            """,
            (user_id, day, month),
        )
        await db.commit()


async def get_birthday(user_id: int) -> BirthdayEntry | None:
    async with connect() as db:
        async with db.execute(
            "SELECT user_id, day, month, last_notified_year FROM birthdays WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        return None

    return BirthdayEntry(
        user_id=row["user_id"],
        day=row["day"],
        month=row["month"],
        last_notified_year=row["last_notified_year"],
    )


async def list_birthdays() -> list[BirthdayEntry]:
    async with connect() as db:
        async with db.execute(
            "SELECT user_id, day, month, last_notified_year FROM birthdays ORDER BY month ASC, day ASC, user_id ASC"
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        BirthdayEntry(
            user_id=row["user_id"],
            day=row["day"],
            month=row["month"],
            last_notified_year=row["last_notified_year"],
        )
        for row in rows
    ]


async def list_birthdays_for_date(day: int, month: int) -> list[BirthdayEntry]:
    async with connect() as db:
        async with db.execute(
            """
            SELECT user_id, day, month, last_notified_year
            FROM birthdays
            WHERE day = ? AND month = ?
            ORDER BY user_id ASC
            """,
            (day, month),
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        BirthdayEntry(
            user_id=row["user_id"],
            day=row["day"],
            month=row["month"],
            last_notified_year=row["last_notified_year"],
        )
        for row in rows
    ]


async def list_due_birthdays(day: int, month: int, year: int) -> list[BirthdayEntry]:
    async with connect() as db:
        async with db.execute(
            """
            SELECT user_id, day, month, last_notified_year
            FROM birthdays
            WHERE day = ?
              AND month = ?
              AND (last_notified_year IS NULL OR last_notified_year <> ?)
            ORDER BY user_id ASC
            """,
            (day, month, year),
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        BirthdayEntry(
            user_id=row["user_id"],
            day=row["day"],
            month=row["month"],
            last_notified_year=row["last_notified_year"],
        )
        for row in rows
    ]


async def mark_birthday_notified(user_id: int, year: int) -> None:
    async with connect() as db:
        await db.execute(
            "UPDATE birthdays SET last_notified_year = ? WHERE user_id = ?",
            (year, user_id),
        )
        await db.commit()


async def delete_birthday(user_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            "DELETE FROM birthdays WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
        return cursor.rowcount > 0
