"""Application startup."""
from __future__ import annotations

import logging
import tkinter as tk

from .ui.main_window import MainWindow


def run() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()
