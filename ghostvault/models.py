"""Shared data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FileEntry:
    """One discovered file. Size is in bytes, mtime is epoch seconds."""
    name: str
    extension: str  # lowercase, includes leading dot, "" when absent
    size: int
    path: Path
    mtime: float = 0.0

    @property
    def location(self) -> str:
        return str(self.path.parent)


@dataclass
class ScanResult:
    """Outcome of a scan. Never raises for per-entry problems."""
    root: Path
    entries: list[FileEntry] = field(default_factory=list)
    skipped: int = 0          # entries that were inaccessible or vanished
    cancelled: bool = False

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries)
