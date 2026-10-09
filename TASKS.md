# GhostVault Tasks

## Current milestone
MILESTONE 2 — Scanning engine: COMPLETE (verified on Windows; see below)
MILESTONE 0 — Audit and stabilize: COMPLETE (docs synced, Windows GUI smoke passed)

## Completed
- Project structure: main.py, ghostvault/{app,models,scanner}.py, ghostvault/ui/main_window.py
- Tkinter window titled GhostVault, dark theme centralized in main_window.py
- Folder selection via native dialog, path displayed
- Scan in background thread (queue + after() polling), cancel button
- Table: Name, Extension, Size (human-readable), Modified, Location; file count and total size
- Column sorting (typed keys), filename/extension filter, optional recursive scan
- Invalid / missing / inaccessible folder -> messagebox, no traceback
- Symlinks skipped, never followed; vanished/unreadable entries counted as skipped
- format_size TB branch fixed; FileEntry carries mtime + location

## Files created
main.py, requirements.txt, README.md, TASKS.md, .gitignore,
ghostvault/__init__.py, app.py, models.py, scanner.py, ui/__init__.py, ui/main_window.py,
tests/__init__.py, tests/test_scanner.py

## Tests executed (observed)
- `python -m unittest discover -s tests -t . -v` on Python 3.14.2 (Windows): 15 tests, OK
  (2 skipped: symlink creation needs privilege/Developer Mode on Windows).
- Scripted Windows GUI smoke (real Tk, hidden window, temp dirs only): window title
  "GhostVault"; recursive scan of temp dir (3 files, 16 B) showed 3 rows,
  "Files: 3  Total size: 16 B", status "Scan complete."; filter ".py" showed 1 row;
  sort by size kept 3 rows; no error popups; no hangs.
- Earlier: `python3 -m unittest discover -s tests -t . -v` on Python 3.12.3 (Linux):
  9 tests, OK (Milestone 1 scope).
- Headless GUI smoke (Xvfb, Tk 8.6, Milestone 1 scope): 3 rows, "Files: 3",
  status "Scan complete."; file hashes unchanged.
- NOT run: native folder dialog (needs a human), interactive `python main.py`
  mainloop session.

## Known bugs / limits
- Interactive `python main.py` mainloop session and native folder dialog still need a human
  on Windows (scripted GUI smoke passed; live session not run).
- Symlink tests skip on Windows without symlink privilege; covered on Linux.
- No categories, preview, history, settings, or logging config yet (later milestones).

## Next action (recommended)
MILESTONE 3 — Read-only preview: capped text preview pane for the selected file
(txt/code shown as text up to N KB, everything else size/type notice), still no
move/rename/delete. Acceptance: preview never writes, binary-safe, covered by
temp-dir tests.
