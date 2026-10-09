import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ghostvault.preview import PREVIEW_MAX_BYTES, preview_file


def snapshot(path: Path):
    st = path.stat()
    return (st.st_mtime_ns, st.st_size, hashlib.sha256(path.read_bytes()).hexdigest())


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_limit_is_64k(self):
        self.assertEqual(PREVIEW_MAX_BYTES, 64 * 1024)

    def test_text_file(self):
        f = self.dir / "note.txt"
        f.write_bytes(b"hello\nworld\n")
        r = preview_file(f)
        self.assertEqual(r.status, "text")
        self.assertEqual(r.text, "hello\nworld\n")
        self.assertEqual(r.size, 12)

    def test_source_file(self):
        f = self.dir / "app.py"
        f.write_bytes(b"print('hi')\n")
        r = preview_file(f)
        self.assertEqual((r.status, r.text), ("text", "print('hi')\n"))

    def test_extensionless_text_file(self):
        f = self.dir / "README"
        f.write_text("readme body", encoding="utf-8")
        r = preview_file(f)
        self.assertEqual((r.status, r.text), ("text", "readme body"))

    def test_empty_file(self):
        f = self.dir / "empty.txt"
        f.write_bytes(b"")
        r = preview_file(f)
        self.assertEqual(r.status, "empty")
        self.assertEqual(r.text, "")

    def test_binary_file(self):
        f = self.dir / "blob.bin"
        f.write_bytes(b"\x00\x01\x02binary")
        r = preview_file(f)
        # .bin is not an eligible extension
        self.assertEqual(r.status, "unsupported")

    def test_text_extension_with_nul_is_binary(self):
        f = self.dir / "odd.txt"
        f.write_bytes(b"ab\x00cd")
        r = preview_file(f)
        self.assertEqual(r.status, "binary")
        self.assertEqual(r.text, "")
        self.assertIn("Binary", r.notice)

    def test_unsupported_extension(self):
        f = self.dir / "prog.xyz"
        f.write_text("plain ascii, but unknown type", encoding="utf-8")
        r = preview_file(f)
        self.assertEqual(r.status, "unsupported")
        self.assertEqual(r.text, "")
        self.assertIn(".xyz", r.notice)

    def test_too_large_uses_default_limit(self):
        f = self.dir / "big.txt"
        f.write_bytes(b"a" * (PREVIEW_MAX_BYTES + 1))
        r = preview_file(f)
        self.assertEqual(r.status, "too_large")
        self.assertEqual(r.text, "")
        self.assertIn("64.0 KB", r.notice)

    def test_exactly_at_limit_is_text(self):
        f = self.dir / "edge.txt"
        f.write_bytes(b"b" * PREVIEW_MAX_BYTES)
        r = preview_file(f)
        self.assertEqual(r.status, "text")
        self.assertEqual(len(r.text), PREVIEW_MAX_BYTES)

    def test_custom_limit(self):
        f = self.dir / "small.txt"
        f.write_bytes(b"x" * 20)
        r = preview_file(f, max_bytes=10)
        self.assertEqual(r.status, "too_large")
        ok = preview_file(f, max_bytes=20)
        self.assertEqual(ok.status, "text")

    def test_invalid_encoding_never_raises(self):
        f = self.dir / "latin.txt"
        f.write_bytes("caf\xe9\n".encode("latin-1"))
        r = preview_file(f)
        self.assertEqual(r.status, "text")
        self.assertIn("\ufffd", r.text)  # replacement character, no crash

    def test_missing_file(self):
        r = preview_file(self.dir / "gone.txt")
        self.assertEqual(r.status, "missing")
        self.assertIn("exists", r.notice)

    def test_directory_is_not_a_file(self):
        r = preview_file(self.dir)
        self.assertEqual(r.status, "not_a_file")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_never_followed(self):
        target = self.dir / "real.txt"
        target.write_text("secret", encoding="utf-8")
        link = self.dir / "link.txt"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlink here")
        r = preview_file(link)
        self.assertEqual(r.status, "symlink")
        self.assertEqual(r.text, "")

    def test_permission_error(self):
        f = self.dir / "locked.txt"
        f.write_text("x", encoding="utf-8")
        with mock.patch("builtins.open", side_effect=PermissionError("denied")):
            r = preview_file(f)
        self.assertEqual(r.status, "inaccessible")

    def test_preview_is_read_only(self):
        files = []
        (self.dir / "t.txt").write_text("text", encoding="utf-8")
        (self.dir / "b.bin").write_bytes(b"\x00\x01")
        (self.dir / "big.txt").write_bytes(b"z" * (PREVIEW_MAX_BYTES + 100))
        for p in sorted(self.dir.iterdir()):
            files.append((p, snapshot(p)))
        for p, _ in files:
            preview_file(p)
        for p, before in files:
            self.assertEqual(before, snapshot(p))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         [p.name for p, _ in files])


if __name__ == "__main__":
    unittest.main()
