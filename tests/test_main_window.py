"""Display-gated integration tests for MainWindow (scan table + preview pane).

These tests need a real Tk display and skip cleanly where none exists, so
headless CI stays green while Windows dev machines exercise the GUI wiring.
"""
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import tkinter as tk

from ghostvault.ui.main_window import MainWindow


def make_window(test):
    try:
        root = tk.Tk()
    except tk.TclError:
        test.skipTest("no display available")
    root.withdraw()
    test.addCleanup(root.destroy)
    return root, MainWindow(root)


def pump(root, window, predicate, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.02)
    root.update()
    return predicate()


class MainWindowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "note.txt").write_text("preview me", encoding="utf-8")
        (self.dir / "blob.bin").write_bytes(b"\x00\x01\x02")

    def tearDown(self):
        self._tmp.cleanup()

    def scan(self, root, window):
        window.folder.set(str(self.dir))
        window.start_scan()
        done = pump(root, window, lambda: (
            window._worker is not None
            and not window._worker.is_alive()
            and ("complete" in window.status.get().lower()
                 or "failed" in window.status.get().lower())))
        self.assertTrue(done, f"scan did not finish: {window.status.get()}")
        self.assertIn("complete", window.status.get().lower())

    def select_first_matching(self, root, window, name):
        for iid in window.tree.get_children():
            if window._row_entries[iid].name == name:
                window.tree.selection_set(iid)
                return iid
        self.fail(f"{name} not found in table")

    def test_select_text_file_shows_preview(self):
        root, window = make_window(self)
        self.scan(root, window)
        self.assertEqual(len(window.tree.get_children()), 2)
        self.select_first_matching(root, window, "note.txt")
        shown = pump(root, window, lambda: "preview me" in window.preview_text.get(
            "1.0", "end"))
        self.assertTrue(shown, window.preview_status.get())
        self.assertIn("note.txt", window.preview_status.get())

    def test_select_binary_file_shows_notice(self):
        root, window = make_window(self)
        self.scan(root, window)
        self.select_first_matching(root, window, "blob.bin")
        shown = pump(root, window, lambda: (
            "not previewed" in window.preview_text.get("1.0", "end")
            or "not previewed" in window.preview_status.get()))
        self.assertTrue(shown, window.preview_status.get())

    def test_preview_widget_is_read_only(self):
        root, window = make_window(self)
        self.assertEqual(str(window.preview_text.cget("state")), "disabled")


if __name__ == "__main__":
    unittest.main()
