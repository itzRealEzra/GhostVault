"""Main window. UI only: scanning runs in a worker thread, results come back via queue."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..models import FileEntry, ScanResult
from ..preview import PREVIEW_MAX_BYTES, PreviewResult, preview_file
from ..scanner import ScanError, filter_entries, format_mtime, format_size, scan_directory

# Centralized theme.
BG = "#1e1e24"
PANEL = "#2a2a32"
FG = "#e6e6ea"
MUTED = "#9a9aa6"
ACCENT = "#8b5cf6"
ACCENT_HOVER = "#a78bfa"
POLL_MS = 50
PREVIEW_POLL_MS = 60


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.folder = tk.StringVar(value="")
        self.summary = tk.StringVar(value="Files: 0   Total size: 0 B")
        self.status = tk.StringVar(value="Choose a folder to begin.")
        self.filter_var = tk.StringVar(value="")
        self.recursive_var = tk.BooleanVar(value=False)
        self.preview_status = tk.StringVar(value="Select a file to preview.")
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._last_result: ScanResult | None = None
        self._row_entries: dict[str, FileEntry] = {}
        self._sort_col = "name"
        self._sort_desc = False
        self._preview_queue: queue.Queue = queue.Queue()
        self._preview_seq = 0
        self._preview_active = False
        self._preview_polling = False

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
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.request_preview())

        pv = ttk.Frame(self.root)
        pv.pack(fill="both", expand=False, **pad)
        ttk.Label(pv, text="Preview", style="Muted.TLabel").pack(anchor="w")
        pf = ttk.Frame(pv)
        pf.pack(fill="both", expand=True)
        self.preview_text = tk.Text(pf, height=8, wrap="none", state="disabled",
                                    bg=PANEL, fg=FG, insertbackground=FG,
                                    selectbackground=ACCENT, relief="flat",
                                    font=("Consolas", 10), padx=6, pady=6)
        pv_vsb = ttk.Scrollbar(pf, orient="vertical", command=self.preview_text.yview)
        pv_hsb = ttk.Scrollbar(pf, orient="horizontal", command=self.preview_text.xview)
        self.preview_text.configure(yscrollcommand=pv_vsb.set,
                                    xscrollcommand=pv_hsb.set)
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        pv_vsb.grid(row=0, column=1, sticky="ns")
        pv_hsb.grid(row=1, column=0, sticky="ew")
        pf.grid_rowconfigure(0, weight=1)
        pf.grid_columnconfigure(0, weight=1)
        ttk.Label(pv, textvariable=self.preview_status, style="Muted.TLabel",
                  anchor="w").pack(fill="x")

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
        self._clear_preview("Select a file to preview.")
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
        self._row_entries = {}
        for e in self._sorted_filtered():
            iid = self.tree.insert("", "end", values=(
                e.name, e.extension or "(none)",
                format_size(e.size), format_mtime(e.mtime), e.location))
            self._row_entries[iid] = e

    # ---- preview (worker never touches widgets) ----
    def request_preview(self) -> None:
        sel = self.tree.selection()
        entry = self._row_entries.get(sel[0]) if sel else None
        if entry is None:
            self._clear_preview("Select a file to preview.")
            return
        self._preview_seq += 1
        self._preview_active = True
        self._set_preview_text("", f"Loading preview of {entry.name}…")
        seq = self._preview_seq
        threading.Thread(target=self._preview_worker,
                         args=(str(entry.path), seq), daemon=True).start()
        if not self._preview_polling:
            self._preview_polling = True
            self.root.after(PREVIEW_POLL_MS, self._poll_preview)

    def _preview_worker(self, path: str, seq: int) -> None:
        try:
            result = preview_file(path, PREVIEW_MAX_BYTES)
        except Exception as exc:  # last-resort guard; details are logged
            import logging
            from pathlib import Path
            logging.getLogger(__name__).exception("Unexpected preview failure")
            result = PreviewResult(Path(path), "inaccessible",
                                   notice=f"Unexpected error: {exc}")
        self._preview_queue.put((seq, result))

    def _poll_preview(self) -> None:
        try:
            while True:
                seq, result = self._preview_queue.get_nowait()
                if seq == self._preview_seq and self._preview_active:
                    self._preview_active = False
                    self._render_preview(result)
                # else: stale result from an earlier selection, drop it
        except queue.Empty:
            pass
        except tk.TclError:
            self._preview_polling = False
            return
        try:
            if self._preview_active:
                self.root.after(PREVIEW_POLL_MS, self._poll_preview)
            else:
                self._preview_polling = False
        except tk.TclError:
            self._preview_polling = False

    def _render_preview(self, result: PreviewResult) -> None:
        try:
            if result.status in ("text", "empty"):
                header = result.path.name
                if result.size >= 0:
                    header += f" — {format_size(result.size)}"
                body = result.text if result.text else "(empty file)"
                self._set_preview_text(body, header)
            else:
                self._set_preview_text("", result.notice or "Preview unavailable.")
        except tk.TclError:
            pass

    def _set_preview_text(self, body: str, status: str) -> None:
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        if body:
            self.preview_text.insert("1.0", body)
        self.preview_text.configure(state="disabled")
        self.preview_status.set(status)

    def _clear_preview(self, message: str = "Select a file to preview.") -> None:
        self._preview_seq += 1  # invalidate any in-flight worker
        self._preview_active = False
        try:
            self._set_preview_text("", message)
        except tk.TclError:
            pass

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
        self._preview_seq += 1
        self._preview_active = False
        self.root.destroy()
