"""Сборка Rich Message HTML для Bot API 10.1 (``sendRichMessage``).

Централизует теги, которых нет в legacy ``parse_mode=HTML``: ``<h*>``,
``<details>``, ``<table>``, ``<time>``, якоря. Legacy HTML для
``sendMessage``-fallback живёт рядом в ``presentation/html.py``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from html import escape

# Bot API 10.1 — лимит rich message (с запасом под safety-cap в рендерах).
RICH_MESSAGE_CHAR_LIMIT = 32768
RICH_MESSAGE_SAFETY_CAP = 30000

_HEADING_TAG = {1: "h1", 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6"}
_HTML_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?>")
_HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")


def escape_rich(text: str) -> str:
    """Экранирует пользовательский текст для вставки в Rich HTML."""
    return escape(text, quote=False)


def input_rich_message(
    html: str,
    *,
    skip_entity_detection: bool = True,
) -> dict[str, object]:
    """``InputRichMessage`` для ``sendRichMessage`` / draft."""
    payload: dict[str, object] = {"html": html}
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    return payload


def paragraph(text: str) -> str:
    return f"<p>{text}</p>"


def section_heading(text: str, *, level: int = 3) -> str:
    tag = _HEADING_TAG.get(level, "h3")
    return f"<{tag}>{text}</{tag}>"


def divider() -> str:
    return "<hr>"


def details_block(summary: str, body: str, *, open: bool = True) -> str:
    """Сворачиваемый блок; ``open=True`` — развёрнут по умолчанию."""
    open_attr = " open" if open else ""
    return f"<details{open_attr}><summary>{summary}</summary>{body}</details>"


def unordered_list(items: Sequence[str]) -> str:
    if not items:
        return ""
    lines = "".join(f"<li>{item}</li>" for item in items)
    return f"<ul>{lines}</ul>"


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Таблица rich message; ячейки — уже размеченный HTML."""
    head = "".join(f"<th>{cell}</th>" for cell in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><tr>{head}</tr>{''.join(body_rows)}</table>"


def datetime_link(label: str, unix_ts: int) -> str:
    """Тапабельное время (``RichTextDateTime`` через ``<time>``)."""
    return f'<time datetime="{int(unix_ts)}">{label}</time>'


def anchor(name: str) -> str:
    return f'<a name="{escape_rich(name)}"></a>'


def anchor_link(text: str, name: str) -> str:
    return f'<a href="#{escape_rich(name)}">{text}</a>'


def external_link(label: str, url: str) -> str:
    """Внешняя ссылка для rich message."""
    return f'<a href="{escape(url, quote=True)}">{label}</a>'


def bold(text: str) -> str:
    return f"<b>{text}</b>"


def italic(text: str) -> str:
    return f"<i>{text}</i>"


def mark(text: str) -> str:
    return f"<mark>{text}</mark>"


def blockquote(text: str, *, cite: str | None = None) -> str:
    """Блочная цитата (``<blockquote>``). ``cite`` — автор в ``<cite>``."""
    body = text
    if cite:
        body += f"<cite>{cite}</cite>"
    return f"<blockquote>{body}</blockquote>"


def pull_quote(text: str, *, author: str | None = None) -> str:
    """Выделенная цитата (``<tg-pullquote>``). ``author`` — подпись в ``<cite>``."""
    body = text
    if author:
        body += f"<cite>{escape_rich(author)}</cite>"
    return f"<tg-pullquote>{body}</tg-pullquote>"


def ordered_list(items: Sequence[str]) -> str:
    if not items:
        return ""
    lines = "".join(f"<li>{item}</li>" for item in items)
    return f"<ol>{lines}</ol>"


def footnote_ref(ref_id: str) -> str:
    """Ссылка на сноску ``[^id]`` в rich Markdown-стиле — через якорь."""
    return f'<a href="#{escape_rich(ref_id)}">[{escape_rich(ref_id)}]</a>'


def footnote_def(ref_id: str, body: str) -> str:
    """Определение сноски (``<tg-reference>`` + якорь)."""
    return (
        f'<a name="{escape_rich(ref_id)}"></a>'
        f'<tg-reference name="{escape_rich(ref_id)}">{body}</tg-reference>'
    )


def thinking_block(text: str) -> str:
    """Draft-only placeholder (``<tg-thinking>``) — только ``sendRichMessageDraft``."""
    return f"<tg-thinking>{text}</tg-thinking>"


def join_blocks(blocks: Sequence[str]) -> str:
    """Склеивает блоки rich message без лишних переводов строк."""
    return "".join(block for block in blocks if block)


def _close_open_tags(html_text: str) -> str:
    stack: list[str] = []
    for match in _HTML_TAG_RE.finditer(html_text):
        closing, tag = match.group(1), match.group(2).lower()
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] == tag:
                    del stack[i]
                    break
        else:
            stack.append(tag)
    if not stack:
        return html_text
    return html_text + "".join(f"</{tag}>" for tag in reversed(stack))


def _safe_html_prefix(text: str, length: int) -> str:
    """Префикс длиной ≤ ``length`` без разрыва HTML-тегов и сущностей."""
    if length >= len(text):
        return text
    cut = length

    last_lt = text.rfind("<", 0, cut)
    last_gt = text.rfind(">", 0, cut)
    if last_lt > last_gt:
        cut = last_lt

    last_amp = text.rfind("&", 0, cut)
    last_semi = text.rfind(";", 0, cut)
    if last_amp > last_semi and cut - last_amp <= 10:
        cut = last_amp

    if cut <= 0:
        return ""
    return _close_open_tags(text[:cut])


def truncate_rich_html(html: str, *, max_len: int = RICH_MESSAGE_SAFETY_CAP) -> str:
    """Усекает rich HTML до лимита, добавляя notice."""
    if len(html) <= max_len:
        return html
    notice = paragraph(f"<i>… Сообщение укорочено (лимит {max_len} символов).</i>")
    budget = max_len - len(notice)
    if budget <= 0:
        return notice[:max_len]
    return _safe_html_prefix(html, budget) + notice


_STREAM_CONTAINER_TAGS = frozenset({"details", "table", "ul", "ol", "blockquote", "tg-pullquote"})
_STREAM_BOUNDARY_TAGS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "details",
        "table",
        "ul",
        "ol",
        "blockquote",
        "tg-pullquote",
        "tg-reference",
    }
)


def rich_blocks_for_streaming(html: str) -> list[str]:
    """Разбивает rich HTML на завершённые блоки верхнего уровня.

    Режет по границам ``</p>``, ``</h1>``–``</h6>``, ``<hr>``, ``</details>``,
    ``</table>``, ``</ul>``, ``</ol>`` — но только вне контейнеров: вложенные
    ``</ul>`` / ``</p>`` внутри ``<details>`` не должны разрывать
    сворачиваемый блок пополам (полуоткрытый блок промаргивает в draft).
    """
    if not html:
        return []
    blocks: list[str] = []
    start = 0
    depth = 0
    for match in _HTML_TAG_RE.finditer(html):
        closing, tag = bool(match.group(1)), match.group(2).lower()
        if tag in _STREAM_CONTAINER_TAGS:
            depth = max(0, depth - 1) if closing else depth + 1
        if depth > 0:
            continue
        is_boundary = (closing and tag in _STREAM_BOUNDARY_TAGS) or (not closing and tag == "hr")
        if is_boundary:
            blocks.append(html[start : match.end()])
            start = match.end()
    if start < len(html):
        blocks.append(html[start:])
    return [b for b in blocks if b]
