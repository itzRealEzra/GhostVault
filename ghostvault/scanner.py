"""Read-only directory scanner. Never modifies the filesystem."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from .models import FileEntry, ScanResult

log = logging.getLogger(__name__)


class ScanError(Exception):
    """Raised when the selected folder itself cannot be scanned."""


def format_size(num_bytes: int) -> str:
    """Human-readable size. Internal math stays in bytes."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # unreachable, keeps type checkers happy


def format_mtime(epoch_seconds: float) -> str:
    """Format epoch seconds as 'YYYY-MM-DD HH:MM' for display."""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "—"


def matches_filter(entry: FileEntry, query: str) -> bool:
    """Case-insensitive substring match against name or extension."""
    q = query.strip().lower()
    if not q:
        return True
    if q.startswith("."):
        return q in entry.extension
    return q in entry.name.lower() or q in entry.extension


def filter_entries(entries: list[FileEntry], query: str) -> list[FileEntry]:
    """Pure helper so filtering is testable without Tkinter."""
    return [e for e in entries if matches_filter(e, query)]


def scan_directory(folder: str | os.PathLike,
                   cancel_event: threading.Event | None = None,
                   recursive: bool = False) -> ScanResult:
    """List files of *folder*.

    Non-recursive by default. With ``recursive=True`` subdirectories are
    walked iteratively. Symlinks are always skipped, never followed.
    Entries that are unreadable or disappear mid-scan are counted in
    ``skipped``. Raises ScanError if the folder itself is invalid.
    """
    if not str(folder).strip():
        raise ScanError("No folder selected.")
    root = Path(folder)
    if not root.exists():
        raise ScanError(f"Folder does not exist:\n{root}")
    if not root.is_dir():
        raise ScanError(f"Not a folder:\n{root}")

    result = ScanResult(root=root)
    stack: list[Path] = [root]
    while stack:
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            break
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except PermissionError as exc:
            if current == root:
                raise ScanError(f"Permission denied:\n{root}") from None
            log.warning("Skipped unreadable folder %s: %s", current, exc)
            result.skipped += 1
            continue
        except OSError as exc:
            if current == root:
                raise ScanError(
                    f"Cannot read folder:\n{root}\n({exc.strerror or exc})") from None
            log.warning("Skipped unreadable folder %s: %s", current, exc)
            result.skipped += 1
            continue

        with iterator:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    result.cancelled = True
                    break
                try:
                    entry = next(iterator)
                except StopIteration:
                    break
                except OSError as exc:
                    log.warning("Scan interrupted while listing %s: %s", current, exc)
                    result.skipped += 1
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if recursive:
                            stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:  # vanished or inaccessible
                    log.warning("Skipped %s: %s", entry.name, exc)
                    result.skipped += 1
                    continue
                result.entries.append(FileEntry(
                    name=entry.name,
                    extension=Path(entry.name).suffix.lower(),
                    size=st.st_size,
                    path=Path(entry.path),
                    mtime=st.st_mtime,
                ))
        if result.cancelled:
            break
    log.info("Scanned %s: %d files, %d skipped, cancelled=%s recursive=%s",
             root, len(result.entries), result.skipped, result.cancelled, recursive)
    return result
