#!/usr/bin/env python3
"""Qt SSH_ASKPASS helper used by Gipler.

OpenSSH invokes this executable with the prompt as its first argument and reads
the response from stdout.  The passphrase is never written to disk or logged.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
)


def _application() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
    app.setApplicationName("Gipler")
    return app


def _confirmation(prompt: str) -> bool:
    box = QMessageBox()
    box.setWindowTitle("Gipler · Autenticación SSH")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(prompt)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return box.exec() == QMessageBox.StandardButton.Yes


def _passphrase(prompt: str) -> tuple[str, bool]:
    dialog = QInputDialog()
    dialog.setWindowTitle("Gipler · Autenticación SSH")
    dialog.setLabelText(prompt or "Passphrase de la clave SSH:")
    dialog.setInputMode(QInputDialog.InputMode.TextInput)
    dialog.setTextEchoMode(QLineEdit.EchoMode.Password)
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.textValue(), accepted


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    prompt = args[1] if len(args) > 1 else "Passphrase de la clave SSH:"
    _application()
    lowered = prompt.casefold()
    if "yes/no" in lowered or os.environ.get("SSH_ASKPASS_PROMPT") == "confirm":
        answer = "yes" if _confirmation(prompt) else "no"
        sys.stdout.write(answer + "\n")
        sys.stdout.flush()
        return 0 if answer == "yes" else 1
    secret, accepted = _passphrase(prompt)
    if not accepted:
        return 1
    sys.stdout.write(secret + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
