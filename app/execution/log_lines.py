"""Helpers for turning a job's output into log lines."""

import asyncio
import re
from collections.abc import AsyncIterator, Iterable

from markupsafe import Markup, escape

READ_CHUNK = 64 * 1024
# Shorter values would mask ordinary words in the output.
MIN_MASKED_LENGTH = 4
# The log panel's "только ошибки" filter. app.js has the same pattern for
# live lines (ERROR_PATTERN there) — keep them in sync.
ERROR_PATTERN = re.compile(
    # The leading \b keeps "\w+(error|exception)" linear: it starts only at
    # word starts, not at every offset of a long word (quadratic, ReDoS).
    # No lookbehind: app.js shares this pattern and old Safari can't parse it.
    r"\b(error|fail|failed|failure|fatal|critical|traceback)\b|\b\w+(error|exception)\b", re.IGNORECASE
)


async def read_lines(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    """Lines of `stream` without the newline, however long they are.

    StreamReader's own line iteration fails on lines over 64 KiB, which
    would kill a job printing one big JSON blob.
    """
    pending = bytearray()
    while chunk := await stream.read(READ_CHUNK):
        pending += chunk
        if b"\n" not in chunk:
            continue
        *complete, rest = pending.split(b"\n")
        pending = bytearray(rest)
        for raw in complete:
            yield raw.decode(errors="replace")
    if pending:
        yield pending.decode(errors="replace")


def mask(line: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if len(secret) >= MIN_MASKED_LENGTH:
            line = line.replace(secret, "***")
    return line


def for_display(line: str, max_chars: int) -> str:
    """What the browser shows: an over-long line's end, with a note."""
    if len(line) <= max_chars:
        return line
    note = f"[начало обрезано, всего {len(line)} символов — полностью в скачанном логе] …"
    return note + line[-max_chars:]


def matches(line: str, query: str, errors_only: bool) -> bool:
    """The log panel's search: a case-insensitive substring, and/or an
    error-looking line."""
    if query and query.lower() not in line.lower():
        return False
    return not errors_only or ERROR_PATTERN.search(line) is not None


def highlight(line: str, query: str, errors_only: bool = False) -> Markup:
    """`line` escaped, with the searched text (or, filtering by errors alone,
    the error words) wrapped in <mark>."""
    if query:
        spans = [m.span() for m in re.finditer(re.escape(query), line, re.IGNORECASE)]
    elif errors_only:
        spans = [m.span() for m in ERROR_PATTERN.finditer(line)]
    else:
        return escape(line)
    out, pos = Markup(), 0
    for start, end in spans:
        out += escape(line[pos:start]) + Markup("<mark>") + escape(line[start:end]) + Markup("</mark>")
        pos = end
    return out + escape(line[pos:])
