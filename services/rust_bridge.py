from __future__ import annotations

import importlib
import unicodedata


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv",
    ".log", ".sql", ".xml", ".html", ".css", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".go", ".rs", ".php", ".rb", ".sh", ".ps1", ".bat", ".env", ".properties", ".lua", ".kt", ".swift",
}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz"}


def _normalize_message_py(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    return " ".join(normalized.casefold().split())


def _chunk_text_py(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than 0")

    trimmed = (text or "").strip()
    if not trimmed:
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(trimmed)

    while start < text_len:
        while start < text_len and trimmed[start].isspace():
            start += 1
        if start >= text_len:
            break

        if text_len - start <= max_chars:
            tail = trimmed[start:].strip()
            if tail:
                chunks.append(tail)
            break

        limit = start + max_chars
        split_at = limit
        if limit < text_len and trimmed[limit].isspace():
            split_at = limit
        else:
            for idx in range(limit - 1, start, -1):
                if trimmed[idx].isspace():
                    split_at = idx
                    break

        if split_at == limit:
            chunks.append(trimmed[start:limit])
            start = limit
            continue

        chunk = trimmed[start:split_at].strip()
        if chunk:
            chunks.append(chunk)
        start = split_at

    return chunks


def _classify_attachment_py(filename: str) -> str:
    normalized = (filename or "").strip().replace("\\", "/").rsplit("/", maxsplit=1)[-1].casefold()
    if any(normalized.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return "image"
    if any(normalized.endswith(ext) for ext in VIDEO_EXTENSIONS):
        return "video"
    if any(normalized.endswith(ext) for ext in AUDIO_EXTENSIONS):
        return "audio"
    if any(normalized.endswith(ext) for ext in TEXT_EXTENSIONS):
        return "text"
    if any(normalized.endswith(ext) for ext in ARCHIVE_EXTENSIONS):
        return "archive"
    return "unknown"


try:
    candidate = importlib.import_module("nightpaw_rs")
except ImportError:
    candidate = None

if candidate is not None and all(
    hasattr(candidate, attr) for attr in ("normalize_message", "chunk_text", "classify_attachment")
):
    _RUST = candidate
else:
    _RUST = None


HAS_RUST = _RUST is not None
RUST_BACKEND = "rust" if HAS_RUST else "python"


def normalize_message(text: str) -> str:
    if _RUST is not None:
        return _RUST.normalize_message(text)
    return _normalize_message_py(text)


def chunk_text(text: str, max_chars: int) -> list[str]:
    if _RUST is not None:
        return list(_RUST.chunk_text(text, max_chars))
    return _chunk_text_py(text, max_chars)


def classify_attachment(filename: str) -> str:
    if _RUST is not None:
        return str(_RUST.classify_attachment(filename))
    return _classify_attachment_py(filename)
