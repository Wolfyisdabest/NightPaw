from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

BOT_COLOR = 0x8B0000  # Dark red
BOT_NAME = "NightPaw"


def _get_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}.") from exc


def _get_float(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a float, got {raw!r}.") from exc

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PREFIX = os.getenv("PREFIX", "!").strip() or "!"
BIRTHDAY_CHANNEL_ID = _get_int("BIRTHDAY_CHANNEL_ID")
AUTOMOD_LOG_CHANNEL_ID = _get_int("AUTOMOD_LOG_CHANNEL_ID")
OWNER_ID = _get_int("OWNER_ID")
MOD_LOG_CHANNEL_ID = _get_int("MOD_LOG_CHANNEL_ID")
BOT_LOG_CHANNEL_ID = _get_int("BOT_LOG_CHANNEL_ID")
BOT_LOG_WEBHOOK = os.getenv("BOT_LOG_WEBHOOK", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
BOT_LOG_WEBHOOK_LEVEL = os.getenv("BOT_LOG_WEBHOOK_LEVEL", "INFO").strip().upper() or "INFO"
BOT_LOG_FILE = os.getenv("BOT_LOG_FILE", "nightpaw.log").strip() or "nightpaw.log"
BOT_LOG_MAX_BYTES = _get_int("BOT_LOG_MAX_BYTES", 5_000_000)
BOT_LOG_BACKUP_COUNT = _get_int("BOT_LOG_BACKUP_COUNT", 5)

AI_OLLAMA_URL = os.getenv("AI_OLLAMA_URL", "http://127.0.0.1:11434").strip() or "http://127.0.0.1:11434"
AI_MODEL = os.getenv("AI_MODEL", "llama3.1:8b").strip() or "llama3.1:8b"

AI_VISION_MODEL = os.getenv("AI_VISION_MODEL", "gemma3:4b").strip()
AI_ATTACHMENT_MAX_BYTES = _get_int("AI_ATTACHMENT_MAX_BYTES", 3500000)
AI_MAX_INLINE_ATTACHMENT_CHARS = _get_int("AI_MAX_INLINE_ATTACHMENT_CHARS", 12000)
AI_MAX_ATTACHMENTS = _get_int("AI_MAX_ATTACHMENTS", 4)
AI_TEMPERATURE = _get_float("AI_TEMPERATURE", 0.35)


def validate_config() -> list[str]:
    errors: list[str] = []
    if not TOKEN:
        errors.append("DISCORD_TOKEN is missing.")
    if not OWNER_ID:
        errors.append("OWNER_ID is missing or invalid.")
    return errors


def wolf_wrap(msg: str) -> str:
    return f"🐺 *{msg}*"
