"""Read-only file preview. Never modifies the filesystem, never executes content.

Files are opened in binary read-only mode and only displayed as text; nothing
is ever evaluated or run. Symlinks are never followed.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .scanner import format_size

log = logging.getLogger(__name__)

#: Default preview cap: files (or reads) beyond this are reported, not loaded.
PREVIEW_MAX_BYTES = 64 * 1024

#: Extensions eligible for text preview (lowercase, leading dot).
#: Extensionless files (README, LICENSE, Makefile) are also eligible and are
#: judged by content sniffing instead.
TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".json", ".jsonl",
    ".xml", ".html", ".htm", ".css", ".scss",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".java", ".cs", ".go", ".rs",
    ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
    ".ps1", ".psm1", ".bat", ".cmd",
    ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml",
    ".csv", ".tsv", ".sql", ".r", ".pl", ".lua", ".diff", ".patch",
    ".tex", ".srt", ".vtt", ".env",
})


@dataclass(frozen=True)
class PreviewResult:
    """Outcome of a preview request. ``status`` is one of:
    ``text``, ``empty``, ``too_large``, ``binary``, ``unsupported``,
    ``missing``, ``not_a_file``, ``inaccessible``, ``symlink``.
    ``text`` is only populated for ``text``/``empty``; otherwise ``notice``
    carries the human-readable message for display.
    """
    path: Path
    status: str
    text: str = ""
    size: int = -1  # actual file size when known
    notice: str = ""


def preview_file(path: str | os.PathLike,
                 max_bytes: int = PREVIEW_MAX_BYTES) -> PreviewResult:
    """Return a capped, read-only text preview of *path*.

    Never writes, never follows symlinks, never executes content. Binary
    content is detected by NUL-byte sniffing; undecodable bytes become the
    Unicode replacement character instead of raising.
    """
    p = Path(path)
    limit = max(0, int(max_bytes))
    try:
        if p.is_symlink():
            return PreviewResult(path=p, status="symlink",
                                 notice="Symbolic links are not previewed.")
        if not p.exists():
            return PreviewResult(path=p, status="missing",
                                 notice="File no longer exists.")
        if not p.is_file():
            return PreviewResult(path=p, status="not_a_file",
                                 notice="Not a regular file.")
    except OSError as exc:
        log.warning("Cannot inspect %s: %s", p, exc)
        return PreviewResult(path=p, status="inaccessible",
                             notice=f"Cannot read file ({exc}).")

    ext = p.suffix.lower()
    if ext != "" and ext not in TEXT_EXTENSIONS:
        return PreviewResult(path=p, status="unsupported",
                             notice=f"Files of type '{ext}' are not previewed as text.")

    try:
        with open(p, "rb") as handle:
            data = handle.read(limit + 1)
    except FileNotFoundError:
        return PreviewResult(path=p, status="missing",
                             notice="File no longer exists.")
    except IsADirectoryError:
        return PreviewResult(path=p, status="not_a_file",
                             notice="Not a regular file.")
    except PermissionError as exc:
        log.warning("Permission denied previewing %s: %s", p, exc)
        return PreviewResult(path=p, status="inaccessible",
                             notice="Permission denied.")
    except OSError as exc:
        log.warning("Cannot read %s: %s", p, exc)
        return PreviewResult(path=p, status="inaccessible",
                             notice=f"Cannot read file ({exc}).")

    try:
        actual = p.stat().st_size
    except OSError:
        actual = len(data)

    if len(data) > limit:
        return PreviewResult(path=p, status="too_large", size=actual,
                             notice=(f"File is {format_size(actual)} — "
                                     f"preview limited to {format_size(limit)}."))
    if b"\x00" in data:
        return PreviewResult(path=p, status="binary", size=actual,
                             notice="Binary file — preview not available.")
    text = data.decode("utf-8", errors="replace")
    if not text:
        return PreviewResult(path=p, status="empty", size=0,
                             notice="(empty file)")
    return PreviewResult(path=p, status="text", text=text, size=actual)
