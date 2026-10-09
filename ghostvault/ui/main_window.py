"""Main window. UI only: scanning runs in a worker thread, results come back via queue."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..models import FileEntry, ScanResult
from ..scanner import ScanError, filter_entries, format_mtime, format_size, scan_directory

# Centralized theme.
BG = "#1e1e24"
PANEL = "#2a2a32"
FG = "#e6e6ea"
MUTED = "#9a9aa6"
ACCENT = "#8b5cf6"
ACCENT_HOVER = "#a78bfa"
POLL_MS = 50


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.folder = tk.StringVar(value="")
        self.summary = tk.StringVar(value="Files: 0   Total size: 0 B")
        self.status = tk.StringVar(value="Choose a folder to begin.")
        self.filter_var = tk.StringVar(value="")
        self.recursive_var = tk.BooleanVar(value=False)
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._last_result: ScanResult | None = None
        self._sort_col = "name"
        self._sort_desc = False

        root.title("GhostVault")
        root.geometry("1020x560")
        root.minsize(640, 400)
        self._style()
        self._build()
        self.filter_var.trace_add("write", lambda *_: self._render_rows())
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- construction ----
    def _style(self) -> None:
        self.root.configure(bg=BG)
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        s.configure("TButton", background=PANEL, foreground=FG, padding=(12, 6), borderwidth=0)
        s.map("TButton", background=[("active", "#3a3a45"), ("disabled", BG)],
              foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        s.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", BG)])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                    foreground=FG, rowheight=24, borderwidth=0)
        s.configure("Treeview.Heading", background=BG, foreground=MUTED, relief="flat")
        s.map("Treeview", background=[("selected", ACCENT)])
        s.configure("TProgressbar", background=ACCENT, troughcolor=PANEL)

    def _build(self) -> None:
        pad = {"padx": 12}
        header = ttk.Frame(self.root)
        header.pack(fill="x", pady=(12, 6), **pad)
        ttk.Label(header, text="GhostVault", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Scan folders safely. Nothing is moved or changed.",
                  style="Muted.TLabel").pack(anchor="w")

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", pady=6, **pad)
        self.choose_btn = ttk.Button(bar, text="Choose Folder", command=self.choose_folder)
        self.choose_btn.pack(side="left")
        self.scan_btn = ttk.Button(bar, text="Scan Folder", style="Accent.TButton",
                                   command=self.start_scan, state="disabled")
        self.scan_btn.pack(side="left", padx=8)
        self.cancel_btn = ttk.Button(bar, text="Cancel", command=self.cancel_scan, state="disabled")
        self.cancel_btn.pack(side="left")

        ttk.Label(self.root, textvariable=self.folder, style="Muted.TLabel",
                  anchor="w").pack(fill="x", **pad)

        opts = ttk.Frame(self.root)
        opts.pack(fill="x", pady=(0, 4), **pad)
        ttk.Label(opts, text="Filter:", style="Muted.TLabel").pack(side="left")
        self.filter_entry = ttk.Entry(opts, textvariable=self.filter_var, width=30)
        self.filter_entry.pack(side="left", padx=(6, 12))
        ttk.Checkbutton(opts, text="Recursive", variable=self.recursive_var).pack(side="left")

        ttk.Label(self.root, textvariable=self.summary, anchor="w").pack(fill="x", pady=(6, 4), **pad)

        table = ttk.Frame(self.root)
        table.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(table, columns=("name", "ext", "size", "modified", "location"),
                                 show="headings", selectmode="browse")
        for col, text, width, anchor in (("name", "Name", 260, "w"),
                                         ("ext", "Extension", 90, "w"),
                                         ("size", "Size", 90, "e"),
                                         ("modified", "Modified", 130, "w"),
                                         ("location", "Location", 300, "w")):
            self.tree.heading(col, text=text, command=lambda c=col: self._on_sort(c))
            self.tree.column(col, width=width, anchor=anchor,
                             stretch=(col in ("name", "location")))
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        footer = ttk.Frame(self.root)
        footer.pack(fill="x", pady=8, **pad)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.pack(side="right")
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel",
                  anchor="w").pack(side="left", fill="x", expand=True)

    # ---- actions ----
    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose a folder to scan", mustexist=True)
        if chosen:
            self.folder.set(chosen)
            self.scan_btn.configure(state="normal")
            self.status.set("Folder selected. Press Scan Folder.")

    def start_scan(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        folder = self.folder.get()
        recursive = bool(self.recursive_var.get())
        self._cancel.clear()
        self._set_busy(True)
        self.status.set("Scanning...")
        self._worker = threading.Thread(target=self._scan_worker,
                                        args=(folder, recursive), daemon=True)
        self._worker.start()
        self.root.after(POLL_MS, self._poll)

    def cancel_scan(self) -> None:
        self._cancel.set()
        self.status.set("Cancelling...")

    # ---- worker plumbing (worker never touches widgets) ----
    def _scan_worker(self, folder: str, recursive: bool = False) -> None:
        try:
            self._queue.put(("done", scan_directory(folder, self._cancel, recursive)))
        except ScanError as exc:
            self._queue.put(("error", str(exc)))
        except Exception as exc:  # last-resort guard; details are logged
            import logging
            logging.getLogger(__name__).exception("Unexpected scan failure")
            self._queue.put(("error", f"Unexpected error: {exc}"))

    def _poll(self) -> None:
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            self.root.after(POLL_MS, self._poll)
            return
        self._set_busy(False)
        if kind == "done":
            self._show_result(payload)
        else:
            self.status.set("Scan failed.")
            messagebox.showerror("GhostVault", payload)

    def _show_result(self, result: ScanResult) -> None:
        self._last_result = result
        self._render_rows()
        self.summary.set(f"Files: {len(result.entries)}   "
                         f"Total size: {format_size(result.total_size)}")
        note = f" ({result.skipped} skipped)" if result.skipped else ""
        self.status.set(("Scan cancelled" if result.cancelled else "Scan complete") + note + ".")

    def _on_sort(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col, self._sort_desc = col, False
        self._render_rows()

    def _sorted_filtered(self) -> list[FileEntry]:
        if self._last_result is None:
            return []
        rows = filter_entries(self._last_result.entries, self.filter_var.get())
        key = {"name": lambda e: e.name.lower(),
               "ext": lambda e: e.extension,
               "size": lambda e: e.size,
               "modified": lambda e: e.mtime,
               "location": lambda e: e.location.lower()}.get(self._sort_col)
        if key is not None:
            rows = sorted(rows, key=key, reverse=self._sort_desc)
        return rows

    def _render_rows(self) -> None:
        if not hasattr(self, "tree"):
            return
        try:
            self.tree.delete(*self.tree.get_children())
        except Exception:
            return
        for e in self._sorted_filtered():
            self.tree.insert("", "end", values=(
                e.name, e.extension or "(none)",
                format_size(e.size), format_mtime(e.mtime), e.location))

    def _set_busy(self, busy: bool) -> None:
        self.choose_btn.configure(state="disabled" if busy else "normal")
        self.scan_btn.configure(state="disabled" if busy or not self.folder.get() else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _on_close(self) -> None:
        self._cancel.set()
        self.root.destroy()
