"""Scientific textbook/document chunking with section and page metadata.

Chunking is deterministic so that evidence citations are reproducible. Headings
are detected from Markdown ``#`` markers, numbered headings and short title-case
or upper-case lines. Page boundaries are preserved for PDFs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_CHARS = 1100
MIN_CHARS = 120
OVERLAP_CHARS = 120

_HEADING_MD = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HEADING_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+([A-Z][^\n]{2,90})$")
_HEADING_UPPER = re.compile(r"^([A-Z][A-Z0-9 \-_/&,]{3,90})$")


@dataclass
class TextBlock:
    text: str
    section: str | None = None
    page: int | None = None


@dataclass
class Chunk:
    index: int
    text: str
    section: str | None
    page: int | None
    char_start: int
    char_end: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        # Whitespace token approximation, recorded for retrieval diagnostics.
        return len(self.text.split())


def detect_sections(text: str, *, page: int | None = None) -> list[TextBlock]:
    """Split text into blocks following heading structure."""
    blocks: list[TextBlock] = []
    current_section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            blocks.append(TextBlock(text=body, section=current_section, page=page))
        buffer = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = None
        md = _HEADING_MD.match(line)
        if md:
            heading = md.group(2).strip()
        elif len(line) <= 100:
            num = _HEADING_NUMBERED.match(line)
            upper = _HEADING_UPPER.match(line)
            if num:
                heading = f"{num.group(1)} {num.group(2)}".strip()
            elif upper and len(line.split()) <= 12 and not line.endswith("."):
                heading = line.title()
        if heading:
            flush()
            current_section = heading
            continue
        buffer.append(raw_line)
    flush()
    return blocks


def chunk_blocks(blocks: list[TextBlock], *, max_chars: int = MAX_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    cursor = 0
    for block in blocks:
        text = " ".join(block.text.split())
        if not text:
            continue
        if len(text) <= max_chars:
            pieces = [text]
        else:
            pieces = _split_text(text, max_chars)
        for piece in pieces:
            if len(piece) < MIN_CHARS and chunks and chunks[-1].section == block.section:
                # Merge tiny trailing fragments into the previous chunk.
                prev = chunks[-1]
                prev.text = f"{prev.text} {piece}".strip()
                prev.char_end = cursor + len(piece)
                cursor += len(piece) + 1
                continue
            start = cursor
            end = cursor + len(piece)
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=piece,
                    section=block.section,
                    page=block.page,
                    char_start=start,
                    char_end=end,
                )
            )
            cursor = end + 1
    return chunks


def _split_text(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for sentence in sentences:
        if length + len(sentence) + 1 > max_chars and current:
            pieces.append(" ".join(current).strip())
            # Retain an overlap tail for context continuity.
            tail = " ".join(current)[-OVERLAP_CHARS:]
            current = [tail]
            length = len(tail)
        current.append(sentence)
        length += len(sentence) + 1
    if current:
        pieces.append(" ".join(current).strip())
    return [p for p in pieces if p]


def chunk_document(
    *,
    text: str,
    pages: list[str] | None = None,
    max_chars: int = MAX_CHARS,
) -> list[Chunk]:
    if pages:
        blocks: list[TextBlock] = []
        for page_number, page_text in enumerate(pages, start=1):
            blocks.extend(detect_sections(page_text, page=page_number))
    else:
        blocks = detect_sections(text)
    if not blocks and text.strip():
        blocks = [TextBlock(text=text.strip())]
    return chunk_blocks(blocks, max_chars=max_chars)
