# GhostVault

Windows desktop utility to scan folders and (in later milestones) safely organize files.
Status: Milestone 2 — read-only scanning (recursive optional, filter, sorting).
Nothing is moved, renamed, or deleted.

## Run
Requires Python 3.10+ with Tkinter (included in the standard Windows installer).

    python main.py

## Test
    python -m unittest discover -s tests -t . -v

Tests use temporary directories only.
