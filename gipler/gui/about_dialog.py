"""Ventana informativa «Acerca de Gipler»."""

from __future__ import annotations

import os
import tomllib
from importlib import metadata
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from gipler.gui.identity import apply_window_icon
from gipler.resources import master_icon


def _put(info: dict[str, str], key: str, value: object) -> None:
    if key in info or not isinstance(value, str):
        return
    text = value.strip()
    if text:
        info[key] = text


def _project_file(name: str) -> Path | None:
    root = Path(__file__).resolve().parents[2]
    path = root / name
    return path if path.is_file() else None


def _license_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "file"):
            text = value.get(key)
            if isinstance(text, str):
                return text
    return ""


def project_info() -> dict[str, str]:
    info: dict[str, str] = {}
    try:
        package = metadata.metadata("gipler")
        _put(info, "version", metadata.version("gipler"))
        _put(info, "description", package.get("Summary"))
        _put(info, "website", package.get("Home-page"))
        for entry in package.get_all("Project-URL") or []:
            label, _, url = entry.partition(",")
            key = label.strip().lower()
            if key in {"homepage", "website", "home-page"}:
                _put(info, "website", url)
            elif key in {"documentation", "docs"}:
                _put(info, "docs", url)
        _put(
            info,
            "license",
            package.get("License-Expression") or package.get("License"),
        )
    except metadata.PackageNotFoundError:
        pass

    pyproject = _project_file("pyproject.toml")
    if pyproject is not None:
        try:
            with open(pyproject, "rb") as file:
                project = tomllib.load(file).get("project", {})
        except (OSError, tomllib.TOMLDecodeError):
            project = {}
        _put(info, "version", project.get("version"))
        _put(info, "description", project.get("description"))
        _put(info, "license", _license_text(project.get("license")))
        urls = project.get("urls") or {}
        _put(info, "website", urls.get("Homepage") or urls.get("Website"))
        _put(info, "docs", urls.get("Documentation") or urls.get("Docs"))
        readme = project.get("readme")
        if isinstance(readme, dict):
            readme = readme.get("file")
        readme_path = _project_file(readme) if isinstance(readme, str) else None
        if readme_path is not None:
            _put(info, "docs", str(readme_path))
    return info


def _open_target(target: str) -> None:
    url = QUrl(target) if "://" in target else QUrl.fromLocalFile(target)
    QDesktopServices.openUrl(url)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        info = project_info()
        self.setWindowTitle("Acerca de Gipler")
        apply_window_icon(self)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        heading.setSpacing(14)
        logo_path = master_icon()
        if os.path.isfile(logo_path):
            logo = QLabel()
            logo.setFixedSize(64, 64)
            logo.setAlignment(Qt.AlignCenter)
            logo.setPixmap(
                QPixmap(logo_path).scaled(
                    64,
                    64,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            heading.addWidget(logo, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        name = QLabel("Gipler")
        name_font = QFont(name.font())
        name_font.setPointSizeF(name_font.pointSizeF() + 7)
        name_font.setWeight(QFont.Weight.Bold)
        name.setFont(name_font)
        titles.addWidget(name)
        version = info.get("version")
        if version:
            version_label = QLabel(f"Versión {version}")
            version_label.setObjectName("aboutVersion")
            titles.addWidget(version_label)
        heading.addLayout(titles)
        heading.addStretch(1)
        layout.addLayout(heading)

        description = info.get("description")
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("aboutDescription")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        license_text = info.get("license")
        if license_text:
            license_label = QLabel(f"Licencia: {license_text}")
            license_label.setObjectName("aboutLicense")
            license_label.setWordWrap(True)
            layout.addWidget(license_label)

        links = QHBoxLayout()
        links.setSpacing(8)
        for key, text in (("website", "Sitio web"), ("docs", "Documentación")):
            target = info.get(key)
            if not target:
                continue
            button = QPushButton(text)
            button.setToolTip(target)
            button.clicked.connect(
                lambda _checked=False, value=target: _open_target(value)
            )
            links.addWidget(button)
        links.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)
        links.addWidget(close_button)
        layout.addLayout(links)
