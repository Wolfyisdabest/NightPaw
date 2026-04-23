from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import sqlite3
from collections.abc import Iterable

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "nightpaw.db"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


async def open_connection() -> aiosqlite.Connection:
    ensure_data_dir()
    db = await aiosqlite.connect(DB_PATH.as_posix(), timeout=30)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA busy_timeout = 30000")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute("PRAGMA foreign_keys = ON")
    except sqlite3.DatabaseError:
        pass
    return db


async def get_table_columns(db: aiosqlite.Connection, table_name: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        rows = await cursor.fetchall()
    return {str(row["name"]) for row in rows}


async def ensure_table_columns(
    db: aiosqlite.Connection,
    table_name: str,
    columns: Iterable[tuple[str, str]],
) -> None:
    existing = await get_table_columns(db, table_name)
    for column_name, column_sql in columns:
        if column_name in existing:
            continue
        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
        existing.add(column_name)


@asynccontextmanager
async def connect():
    db = await open_connection()
    try:
        yield db
    finally:
        await db.close()
