# GhostVault Tasks

## Current milestone
MILESTONE 1 — Application skeleton: COMPLETE (verified in Linux sandbox only; see below)

## Completed
- Project structure: main.py, ghostvault/{app,models,scanner}.py, ghostvault/ui/main_window.py
- Tkinter window titled GhostVault, dark theme centralized in main_window.py
- Folder selection via native dialog, path displayed
- Non-recursive scan in background thread (queue + after() polling), cancel button
- Table: Name, Extension, Size (human-readable); file count and total size
- Invalid / missing / inaccessible folder -> messagebox, no traceback
- Symlinks skipped, vanished/unreadable entries counted as skipped

## Files created
main.py, requirements.txt, README.md, TASKS.md, .gitignore,
ghostvault/__init__.py, app.py, models.py, scanner.py, ui/__init__.py, ui/main_window.py,
tests/__init__.py, tests/test_scanner.py

## Tests executed (observed)
- `python3 -m unittest discover -s tests -t . -v` on Python 3.12.3 (Linux): 9 tests, OK.
- Headless GUI smoke (Xvfb, Tk 8.6): window title "GhostVault"; scan of temp dir with 3 files
  showed 3 rows, "Files: 3  Total size: 2.0 KB", status "Scan complete."; file hashes unchanged.
- NOT run: native folder dialog (needs a human), Windows 10/11 launch.

## Known bugs / limits
- Not yet launched on Windows. Please run `python main.py` there and report issues.
- No sorting, categories, preview, history, settings, or logging config yet (later milestones).

## Next action
MILESTONE 2 — Scanning engine: add modified time + location columns, column sorting,
filename/extension filter, optional recursive scan (symlinks never followed).
