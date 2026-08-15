"""Launcher for dutyshift's monthly duty-roster GUI.

dutyshift's GUI (script/gui.py::build_app) is built on ipywidgets, which needs a live Jupyter
kernel to render and to capture button clicks/output -- IPython's display() has nothing to draw
to inside a plain `python` process (see CLAUDE.md's Tech stack section). So this script does not
build or display the GUI itself: it writes the one-cell notebook that used to be main.ipynb to a
gitignored file in the repo root (so the kernel's working directory still resolves
`from script.gui import *`) and launches the classic Jupyter Notebook server against it, using
the same `notebook` package pinned in requirements.txt. The generated notebook is removed again
once the server exits.

Usage:
    python main.py [--port PORT] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
GENERATED_NOTEBOOK = REPO_ROOT / ".main.generated.ipynb"

NOTEBOOK_CELL_SOURCE = [
    "###############################################################################\n",
    "# dutyshift -- combined GUI\n",
    "###############################################################################\n",
    "\n",
    "from script.gui import *\n",
    "state = AppState()\n",
    "display(build_app(state))\n",
]


def build_notebook() -> dict:
    """Return the nbformat-4 notebook JSON that main.ipynb used to hold: one cell that builds
    and displays script/gui.py's combined GUI panel."""
    return {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": NOTEBOOK_CELL_SOURCE,
            }
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 2,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=None, help="Port to run the Jupyter Notebook server on.")
    parser.add_argument("--no-browser", action="store_true", help="Don't open a browser tab automatically.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    GENERATED_NOTEBOOK.write_text(json.dumps(build_notebook(), indent=1))
    cmd = [sys.executable, "-m", "notebook", str(GENERATED_NOTEBOOK)]
    if args.port is not None:
        cmd.append(f"--port={args.port}")
    if args.no_browser:
        cmd.append("--no-browser")

    proc = subprocess.Popen(cmd, cwd=REPO_ROOT)
    try:
        # Ctrl-C reaches the Jupyter child directly too (same foreground process group), and
        # its own shutdown may need a second Ctrl-C to confirm -- keep waiting through however
        # many arrive so we only clean up the generated notebook once the server has actually
        # exited, not out from under it mid-shutdown.
        while True:
            try:
                return proc.wait()
            except KeyboardInterrupt:
                continue
    finally:
        GENERATED_NOTEBOOK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
