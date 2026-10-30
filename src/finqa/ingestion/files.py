"""Crash-safe file writes shared by the ingestion steps."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path


def save_atomic(
    path: Path,
    data: str | bytes,
    attempts: int = 8,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Write to `<path>.tmp`, then rename onto `path`, so a crash never leaves a half-written
    file. On Windows the rename can be refused for a moment while antivirus or the search
    indexer scans the new file, so it is retried briefly before giving up."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if isinstance(data, bytes):
        tmp.write_bytes(data)
    else:
        tmp.write_text(data, encoding="utf-8")
    for attempt in range(attempts):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            sleep(0.25 * (attempt + 1))
