"""Helpers for turning a job's output into log lines."""

import asyncio
from collections.abc import AsyncIterator, Iterable

READ_CHUNK = 64 * 1024
# Shorter values would mask ordinary words in the output.
MIN_MASKED_LENGTH = 4


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
