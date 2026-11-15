"""Iconos vectoriales embebidos de Gipler.

Los SVG viven en este módulo: no se descargan recursos, no se leen archivos
externos y no se distribuyen PNG individuales.  El color se sustituye en el
momento de renderizar para seguir la paleta activa de Qt.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

# Trazo común: mismo grosor, extremos redondeados y sin relleno.
_STROKE = (
    'fill="none" stroke="{color}" stroke-width="1.4" '
    'stroke-linecap="round" stroke-linejoin="round"'
)

SVG_ICONS: dict[str, str] = {
    "fetch": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
<path d="M12 12v9"/><path d="m8 17 4 4 4-4"/>
</g></svg>''',
    "pull": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M12 17V3"/><path d="m6 11 6 6 6-6"/><path d="M19 21H5"/>
</g></svg>''',
    "commit": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<circle cx="12" cy="12" r="3"/><path d="M3 12h6"/><path d="M15 12h6"/>
</g></svg>''',
    "push": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
<path d="M12 12v9"/><path d="m8 17 4-4 4 4"/>
</g></svg>''',
    "check": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="m4.5 12.5 5 5 10-11"/>
</g></svg>''',
    "cancel": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M6 6l12 12"/><path d="M18 6 6 18"/>
</g></svg>''',
    "folder": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h5l2 2h7a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5Z"/>
</g></svg>''',
    "file": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M6 3.5h7l5 5v12H6Z"/><path d="M13 3.5v5h5"/>
</g></svg>''',
    "search": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4.5 4.5"/>
</g></svg>''',
    "refresh": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v5h-5"/>
</g></svg>''',
    "workspace": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M9 4.5v15"/><path d="M9 10h11.5"/>
</g></svg>''',
    "settings": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<g {_STROKE}>
<path d="M4 6h16"/><circle cx="9" cy="6" r="2"/><path d="M4 12h16"/><circle cx="15" cy="12" r="2"/><path d="M4 18h16"/><circle cx="11" cy="18" r="2"/>
</g></svg>''',
}

ICON_NAMES = tuple(SVG_ICONS)


def _theme_color() -> str:
    app = QApplication.instance()
    if app is None:
        return "#E5EAF0"
    return app.palette().color(QPalette.ColorRole.ButtonText).name()


def current_color() -> str:
    """Return the active icon stroke color (useful after theme changes)."""
    return _theme_color()


def _disabled_color() -> str:
    app = QApplication.instance()
    if app is None:
        return "#7C8594"
    return app.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText).name()


def svg_source(name: str, color: str | None = None) -> str:
    """Return the embedded SVG source with the requested stroke color."""
    try:
        template = SVG_ICONS[name]
    except KeyError as exc:
        raise KeyError(f"icono Gipler desconocido: {name}") from exc
    return template.replace("{color}", color or _theme_color())


def _pixmap(
    name: str, color: str, size: int = 64, *, template: str | None = None
) -> QPixmap:
    source = (template or SVG_ICONS[name]).replace("{color}", color)
    renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


@lru_cache(maxsize=128)
def _icon_cached(
    name: str, color: str, disabled_color: str, template: str
) -> QIcon:
    icon = QIcon()
    icon.addPixmap(
        _pixmap(name, color, template=template),
        QIcon.Mode.Normal,
        QIcon.State.Off,
    )
    icon.addPixmap(
        _pixmap(name, disabled_color, template=template),
        QIcon.Mode.Disabled,
        QIcon.State.Off,
    )
    return icon


def icon(name: str, color: str | None = None) -> QIcon:
    """Build a themed QIcon from the embedded SVG for *name*."""
    if name not in SVG_ICONS:
        raise KeyError(f"icono Gipler desconocido: {name}")
    normal = color or _theme_color()
    disabled = color or _disabled_color()
    return _icon_cached(name, normal, disabled, SVG_ICONS[name])


def clear_cache() -> None:
    """Drop rendered icons after a theme change."""
    _icon_cached.cache_clear()
