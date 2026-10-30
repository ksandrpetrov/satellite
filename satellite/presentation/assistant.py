"""Safe, compact Telegram layout for assistant text and server-generated reports."""

from __future__ import annotations

import re
from html import escape

from .rich import bold, join_blocks, paragraph, section_heading, unordered_list


def assistant_message_chunks(text: str, *, limit: int = 2800) -> list[str]:
    """Keep a meeting or suggestion together, within Telegram's UTF-16 limit."""

    def size(value: str) -> int:
        return len(value.encode("utf-16-le")) // 2

    blocks: list[str] = []
    heading = ""
    for block in text.split("\n\n"):
        if block.startswith("## ") and "\n" not in block:
            heading += block + "\n\n"
            continue
        blocks.append(heading + block)
        heading = ""
    if heading:
        blocks.append(heading.rstrip())
    chunks: list[str] = []
    current = ""
    for block in blocks:
        while size(block) > limit:
            count = 0
            end = 0
            for char in block:
                units = 2 if ord(char) > 0xFFFF else 1
                if count + units > limit:
                    break
                count += units
                end += 1
            split = max(block.rfind("\n", 0, end), block.rfind(" ", 0, end))
            end = split if split > end // 2 else end
            if current:
                chunks.append(current)
                current = ""
            chunks.append(block[:end].rstrip())
            block = block[end:].lstrip()
        joined = current + "\n\n" + block if current else block
        if size(joined) > limit:
            chunks.append(current)
            current = block
        else:
            current = joined
    if current:
        chunks.append(current)
    return chunks


def assistant_message_html(text: str) -> tuple[str, str]:
    rich: list[str] = []
    legacy: list[str] = []
    for block in text.split("\n\n"):
        lines = block.splitlines()
        if not lines:
            continue
        if lines[0].startswith("## "):
            title = escape(lines.pop(0)[3:])
            rich.append(section_heading(title))
            legacy.append(bold(title))
        if not lines:
            continue
        escaped = [escape(line) for line in lines]
        if all(line.startswith("• ") for line in lines):
            rich.append(unordered_list([line[2:] for line in escaped]))
        else:
            if re.match(r"^\d+\. ", lines[0]):
                escaped[0] = bold(escaped[0])
            rich.append(paragraph("<br>".join(escaped)))
        legacy.append("\n".join(escaped))
    return join_blocks(rich), "\n\n".join(legacy)
