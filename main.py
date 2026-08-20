"""Launcher for dutyshift's monthly duty-roster GUI.

Usage:
    python main.py
"""

import sys

from PyQt5.QtWidgets import QApplication

from script.gui import AppState, build_app


def main(argv=None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    state = AppState()
    window = build_app(state)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
