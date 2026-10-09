import hashlib
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from ghostvault.scanner import (
    ScanError,
    filter_entries,
    format_mtime,
    format_size,
    scan_directory,
)


def snapshot(folder: Path) -> dict:
    return {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in folder.iterdir() if p.is_file()}


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_directory(self):
        r = scan_directory(self.dir)
        self.assertEqual((r.entries, r.total_size, r.skipped), ([], 0, 0))

    def test_extensions_sizes_and_no_extension(self):
        (self.dir / "a.TXT").write_bytes(b"12345")
        (self.dir / "b.py").write_bytes(b"x" * 10)
        (self.dir / "README").write_bytes(b"")
        r = scan_directory(self.dir)
        by_name = {e.name: e for e in r.entries}
        self.assertEqual(by_name["a.TXT"].extension, ".txt")
        self.assertEqual(by_name["README"].extension, "")
        self.assertEqual(r.total_size, 15)
        self.assertEqual(len(r.entries), 3)

    def test_not_recursive_and_dirs_excluded(self):
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("x")
        (self.dir / "top.txt").write_text("x")
        self.assertEqual([e.name for e in scan_directory(self.dir).entries], ["top.txt"])

    def test_nonexistent_and_not_a_dir_and_blank(self):
        with self.assertRaises(ScanError):
            scan_directory(self.dir / "nope")
        f = self.dir / "f.txt"
        f.write_text("x")
        with self.assertRaises(ScanError):
            scan_directory(f)
        with self.assertRaises(ScanError):
            scan_directory("  ")

    def test_scan_does_not_modify_files(self):
        for i in range(5):
            (self.dir / f"f{i}.bin").write_bytes(os.urandom(64))
        before = snapshot(self.dir)
        scan_directory(self.dir)
        self.assertEqual(before, snapshot(self.dir))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         sorted(before))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinks_skipped(self):
        target = self.dir / "real.txt"
        target.write_text("x")
        try:
            os.symlink(target, self.dir / "link.txt")
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlink here")
        self.assertEqual([e.name for e in scan_directory(self.dir).entries], ["real.txt"])

    def test_file_vanishes_during_scan(self):
        (self.dir / "ok.txt").write_text("x")
        (self.dir / "gone.txt").write_text("x")
        real_stat = os.DirEntry.stat if hasattr(os.DirEntry, "stat") else None
        real_scandir = os.scandir

        class Wrapper:
            def __init__(self, entry):
                self._e = entry
                self.name, self.path = entry.name, entry.path
            def is_symlink(self): return self._e.is_symlink()
            def is_file(self, **kw): return self._e.is_file(**kw)
            def is_dir(self, **kw): return self._e.is_dir(**kw)
            def stat(self, **kw):
                if self.name == "gone.txt":
                    raise FileNotFoundError("vanished")
                return self._e.stat(**kw)

        class Iter:
            def __init__(self, it): self._it = it
            def __enter__(self): return self
            def __exit__(self, *a): self._it.close()
            def __next__(self): return Wrapper(next(self._it))

        with mock.patch("ghostvault.scanner.os.scandir",
                        side_effect=lambda p: Iter(real_scandir(p))):
            r = scan_directory(self.dir)
        self.assertEqual([e.name for e in r.entries], ["ok.txt"])
        self.assertEqual(r.skipped, 1)

    def test_cancel(self):
        for i in range(3):
            (self.dir / f"{i}.txt").write_text("x")
        ev = threading.Event()
        ev.set()
        r = scan_directory(self.dir, ev)
        self.assertTrue(r.cancelled)
        self.assertEqual(r.entries, [])

    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1023), "1023 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(5 * 1024 ** 2), "5.0 MB")
        self.assertEqual(format_size(3 * 1024 ** 3), "3.0 GB")
        self.assertEqual(format_size(1024 ** 4), "1.0 TB")
        self.assertEqual(format_size(int(2.5 * 1024 ** 4)), "2.5 TB")

    def test_permission_denied_root(self):
        with mock.patch("ghostvault.scanner.os.scandir",
                        side_effect=PermissionError("denied")):
            with self.assertRaises(ScanError):
                scan_directory(self.dir)

    def test_unicode_and_spaced_names(self):
        names = ["spaced name.txt", "ünicode_ß.py", "名前.dat"]
        for n in names:
            (self.dir / n).write_bytes(b"x")
        r = scan_directory(self.dir)
        self.assertEqual(sorted(e.name for e in r.entries), sorted(names))

    def test_mtime_and_location_present(self):
        f = self.dir / "a.txt"
        f.write_bytes(b"xy")
        r = scan_directory(self.dir)
        self.assertEqual(len(r.entries), 1)
        e = r.entries[0]
        self.assertGreater(e.mtime, 0)
        self.assertEqual(e.location, str(self.dir))
        self.assertRegex(format_mtime(e.mtime), r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")

    def test_recursive_finds_nested(self):
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_bytes(b"123")
        (self.dir / "top.txt").write_bytes(b"x")
        flat = scan_directory(self.dir, recursive=False)
        self.assertEqual([e.name for e in flat.entries], ["top.txt"])
        rec = scan_directory(self.dir, recursive=True)
        by_name = {e.name: e for e in rec.entries}
        self.assertEqual(sorted(by_name), ["deep.txt", "top.txt"])
        self.assertEqual(by_name["deep.txt"].location, str(sub))
        self.assertEqual(rec.total_size, 4)

    def test_recursive_never_follows_symlinked_dir(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        outside = self.dir / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"x")
        link = self.dir / "linkdir"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlink here")
        r = scan_directory(self.dir, recursive=True)
        self.assertEqual(r.entries, [])

    def test_filter_entries(self):
        (self.dir / "a.TXT").write_bytes(b"1")
        (self.dir / "b.py").write_bytes(b"22")
        (self.dir / "README").write_bytes(b"")
        entries = scan_directory(self.dir).entries
        self.assertEqual(len(filter_entries(entries, "")), 3)
        self.assertEqual([e.name for e in filter_entries(entries, "a.")], ["a.TXT"])
        self.assertEqual(
            sorted(e.name for e in filter_entries(entries, ".py")), ["b.py"])
        self.assertEqual(
            sorted(e.name for e in filter_entries(entries, "TXT")), ["a.TXT"])


if __name__ == "__main__":
    unittest.main()
