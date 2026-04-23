from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import discord

import config

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
TEXT_EXTENSIONS = {
    '.txt', '.md', '.py', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.csv', '.tsv',
    '.log', '.sql', '.xml', '.html', '.css', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.hpp', '.cs',
    '.go', '.rs', '.php', '.rb', '.sh', '.ps1', '.bat', '.env', '.properties', '.lua', '.kt', '.swift',
}

BINARY_TEXTLIKE_CONTENT_TYPES = {
    'application/json',
    'application/xml',
    'application/javascript',
    'application/x-javascript',
    'application/sql',
}


@dataclass(slots=True)
class ProcessedAttachment:
    filename: str
    content_type: str
    size: int
    source: str
    kind: str
    text_content: str = ''
    image_b64: str | None = None
    width: int | None = None
    height: int | None = None
    note: str = ''


@dataclass(slots=True)
class AttachmentBatch:
    attachments: list[ProcessedAttachment]
    warnings: list[str]

    @property
    def has_images(self) -> bool:
        return any(att.kind == 'image' and att.image_b64 for att in self.attachments)

    @property
    def has_text(self) -> bool:
        return any(att.kind == 'text' and att.text_content for att in self.attachments)

    @property
    def image_payloads(self) -> list[str]:
        return [att.image_b64 for att in self.attachments if att.kind == 'image' and att.image_b64]


def _ext(filename: str) -> str:
    return Path(filename).suffix.casefold()


def _is_image_attachment(att: discord.Attachment) -> bool:
    ctype = (att.content_type or '').casefold()
    return ctype.startswith('image/') or _ext(att.filename) in IMAGE_EXTENSIONS


def _is_text_attachment(att: discord.Attachment) -> bool:
    ctype = (att.content_type or '').casefold()
    if ctype.startswith('text/') or any(ctype.startswith(x) for x in BINARY_TEXTLIKE_CONTENT_TYPES):
        return True
    return _ext(att.filename) in TEXT_EXTENSIONS


def _decode_text(data: bytes) -> str:
    for encoding in ('utf-8', 'utf-8-sig', 'cp1252', 'latin-1'):
        try:
            text = data.decode(encoding, errors='replace').replace('\x00', '')
            return text.strip()
        except Exception:
            continue
    return data.decode('utf-8', errors='replace').replace('\x00', '').strip()

async def _read_attachment_bytes(att: discord.Attachment) -> bytes:
    try:
        return await att.read(use_cached=True)
    except Exception:
        return await att.read()


def _looks_textish_bytes(data: bytes) -> bool:
    if not data:
        return True
    sample = data[:2048]
    if b"\x00" in sample:
        return False
    odd = sum(1 for b in sample if b < 9 or (13 < b < 32))
    return odd / max(len(sample), 1) < 0.12


def prompt_targets_text_attachment(prompt: str = "") -> bool:
    prompt_n = " ".join((prompt or "").casefold().split())
    if not prompt_n:
        return True
    generic_text_words = ("attachment", "file", "text", "txt", "document", "readme", "log")
    direct_text_queries = (
        "what is said", "what does it say", "read this", "read the text", "what is in this text",
        "what did i write", "what did i send", "summarize", "summary", "overview", "quote",
        "first lines", "transcribe", "extract the text", "contents of", "what is in the file",
        "what is this attachment about", "what is the attachment about", "what is the following attachment about",
        "what is this file about", "what is the following file about", "what is this text about",
        "what do you see in this attachment", "what do you see inside this attachment", "what do you see in this file",
        "what do you see inside this file", "what do you see in this text", "what is written",
    )
    image_queries = (
        "what do you see", "describe this image", "in this image", "in the image", "screenshot",
        "photo", "picture", "visual", "look at this image",
    )
    if any(key in prompt_n for key in direct_text_queries):
        return True
    if any(word in prompt_n for word in generic_text_words):
        return True
    if any(key in prompt_n for key in image_queries):
        return False
    return False


def prompt_targets_image_attachment(prompt: str = "") -> bool:
    prompt_n = " ".join((prompt or "").casefold().split())
    if not prompt_n:
        return False
    image_queries = (
        "what do you see", "describe this image", "describe the image", "in this image", "in the image",
        "screenshot", "photo", "picture", "visual", "look at this image", "what is shown",
        "what's shown", "what is in the image", "what's in the image", "analyze this image",
    )
    return any(key in prompt_n for key in image_queries)


def infer_attachment_focus(prompt: str, batch: AttachmentBatch | None) -> str:
    if not batch or not batch.attachments:
        return "none"
    if batch.has_text and not batch.has_images:
        return "text"
    if batch.has_images and not batch.has_text:
        return "image"

    wants_text = prompt_targets_text_attachment(prompt)
    wants_image = prompt_targets_image_attachment(prompt)
    if wants_text and not wants_image:
        return "text"
    if wants_image and not wants_text:
        return "image"
    return "mixed"



async def collect_message_attachments(message: discord.Message) -> list[tuple[discord.Attachment, str]]:
    seen: set[int] = set()
    collected: list[tuple[discord.Attachment, str]] = []

    def add(items: Iterable[discord.Attachment], source: str):
        for att in items:
            if att.id in seen:
                continue
            seen.add(att.id)
            collected.append((att, source))

    add(message.attachments, 'message')
    ref = message.reference
    resolved = getattr(ref, 'resolved', None)
    if isinstance(resolved, discord.Message):
        add(resolved.attachments, 'reply')
    return collected


async def process_discord_attachments(
    entries: list[tuple[discord.Attachment, str]],
    *,
    max_attachments: int | None = None,
    max_bytes: int | None = None,
    max_text_chars: int | None = None,
    max_images: int = 2,
) -> AttachmentBatch:
    max_attachments = int(max_attachments or getattr(config, 'AI_MAX_ATTACHMENTS', 4))
    max_bytes = int(max_bytes or getattr(config, 'AI_ATTACHMENT_MAX_BYTES', 3_500_000))
    max_text_chars = int(max_text_chars or getattr(config, 'AI_MAX_INLINE_ATTACHMENT_CHARS', 12_000))

    attachments: list[ProcessedAttachment] = []
    warnings: list[str] = []
    image_count = 0

    for att, source in entries[:max_attachments]:
        ctype = att.content_type or 'unknown'
        if att.size > max_bytes:
            warnings.append(f"Skipped `{att.filename}` because it is larger than {max_bytes // 1_000_000} MB.")
            attachments.append(ProcessedAttachment(att.filename, ctype, att.size, source, 'other', note='too_large'))
            continue

        try:
            if _is_image_attachment(att):
                if image_count >= max_images:
                    warnings.append(f"Skipped extra image `{att.filename}` to keep the request light.")
                    attachments.append(ProcessedAttachment(att.filename, ctype, att.size, source, 'other', note='extra_image_skipped'))
                    continue
                raw = await _read_attachment_bytes(att)
                attachments.append(
                    ProcessedAttachment(
                        filename=att.filename,
                        content_type=ctype,
                        size=att.size,
                        source=source,
                        kind='image',
                        image_b64=base64.b64encode(raw).decode('ascii'),
                        width=att.width,
                        height=att.height,
                    )
                )
                image_count += 1
                continue

            if _is_text_attachment(att):
                raw = await _read_attachment_bytes(att)
                if _ext(att.filename) not in TEXT_EXTENSIONS and not _looks_textish_bytes(raw):
                    attachments.append(ProcessedAttachment(att.filename, ctype, att.size, source, 'other', note='binary_textlike_rejected'))
                    warnings.append(f"Skipped `{att.filename}` because it looked binary rather than readable text.")
                    continue
                text = _decode_text(raw)
                if len(text) > max_text_chars:
                    warnings.append(f"Trimmed `{att.filename}` to the first {max_text_chars} characters.")
                    text = text[:max_text_chars]
                attachments.append(
                    ProcessedAttachment(
                        filename=att.filename,
                        content_type=ctype,
                        size=att.size,
                        source=source,
                        kind='text',
                        text_content=text,
                    )
                )
                continue

            attachments.append(ProcessedAttachment(att.filename, ctype, att.size, source, 'other', note='unsupported_type'))
            warnings.append(f"Attached file `{att.filename}` was detected, but that file type is not parsed inline yet.")
        except Exception as exc:
            warnings.append(f"Failed to read `{att.filename}`: {exc}")
            attachments.append(ProcessedAttachment(att.filename, ctype, att.size, source, 'other', note='read_failed'))

    return AttachmentBatch(attachments=attachments, warnings=warnings)


def render_attachment_context(batch: AttachmentBatch) -> str:
    if not batch.attachments:
        return ''

    lines: list[str] = ['Attachment context available for this turn:']
    for att in batch.attachments:
        prefix = f"- {att.filename} ({att.source}, {att.kind}, {att.size} bytes"
        if att.kind == 'image' and (att.width or att.height):
            prefix += f", {att.width or '?'}x{att.height or '?'}"
        prefix += ')'
        lines.append(prefix)
        if att.kind == 'text' and att.text_content:
            lines.append(f"  Content from {att.filename}:\n```\n{att.text_content}\n```")
    if batch.warnings:
        lines.append('Attachment handling notes:')
        for warning in batch.warnings:
            lines.append(f'- {warning}')
    return '\n'.join(lines)



def should_prefer_text_attachment_fallback(batch: AttachmentBatch, prompt: str = "") -> bool:
    if not batch or not batch.has_text:
        return False

    prompt_n = " ".join((prompt or "").casefold().split())
    if not prompt_n:
        return True

    direct_text_queries = (
        "what is said", "what does it say", "read this", "read the text", "what is in this text",
        "what did i write", "what did i send", "summarize", "summary", "overview", "quote",
        "first lines", "transcribe", "extract the text", "contents of", "what is in the file",
        "what is this attachment about", "what is the attachment about", "what is the following attachment about",
        "what is this file about", "what is the following file about", "what is this text about",
    )
    image_queries = (
        "what do you see", "describe this image", "in this image", "in the image", "screenshot",
        "photo", "picture", "visual", "look at this image",
    )

    if any(key in prompt_n for key in image_queries) and batch.has_images and not batch.has_text:
        return False

    if any(key in prompt_n for key in direct_text_queries):
        return True

    return batch.has_text and not batch.has_images

def describe_attachment_capability() -> str:
    vision_model = getattr(config, 'AI_VISION_MODEL', '').strip()
    if vision_model:
        return (
            f"I can read common text/code attachments directly, and I can analyze image attachments when the local vision model `{vision_model}` is installed in Ollama."
        )
    return 'I can read common text/code attachments directly. Image understanding needs a vision-capable Ollama model to be configured.'


def build_text_attachment_fallback(batch: AttachmentBatch, prompt: str = "") -> str:
    text_attachments = [att for att in batch.attachments if att.kind == "text" and att.text_content]
    if not text_attachments:
        return "I did not get any readable text attachment content in this turn."

    primary = text_attachments[0]
    body = primary.text_content.strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    title = lines[0] if lines else primary.filename
    excerpt = body[:900].strip()
    if len(body) > 900:
        excerpt += "…"

    prompt_n = " ".join(prompt.casefold().split())
    if any(key in prompt_n for key in (
        "summary", "summarize", "sum up", "overview", "what is this about",
        "what is this attachment about", "what is the attachment about", "what is the following attachment about",
        "what is this file about", "what is the following file about", "what is this text about",
    )):
        next_bits: list[str] = []
        for line in lines[1:8]:
            if (len(line) < 80 and line.isalpha()) or line.endswith(":"):
                next_bits.append(line.rstrip(":"))
        sections = f" Visible section headings: {', '.join(next_bits[:5])}." if next_bits else ""
        return f"`{primary.filename}` looks like a text write-up titled **{title}**.{sections}"

    if any(key in prompt_n for key in (
        "what is said", "what does it say", "read this", "read the text", "what is in this text", "quote", "first lines"
    )):
        return f"I read `{primary.filename}`. It starts like this:\n\n{excerpt}"

    return f"I read `{primary.filename}`. The attachment starts with **{title}** and contains readable text. Here's the opening portion:\n\n{excerpt}"


def build_unreadable_attachment_reply(batch: AttachmentBatch, prompt: str = "") -> str:
    if not batch.attachments:
        return "I did not receive any attachment content on this turn."

    names = ", ".join(f"`{att.filename}`" for att in batch.attachments[:3])
    prompt_n = " ".join((prompt or "").casefold().split())
    if any(word in prompt_n for word in ("summary", "summarize", "about", "what is this", "what do you see", "read")):
        return (
            f"I received {names}, but I couldn't extract readable text from that file on this turn. "
            "If it's meant to be plain text, try resending it as a standard UTF-8 `.txt` file or paste the text directly into chat."
        )
    return (
        f"I received {names}, but I couldn't pull readable text out of it on this turn. "
        "Try sending it again as a plain text file or paste the contents directly."
    )
