"""The line icons of the window: the sidebar's Mask (a document with a mask on it), Restore (a
key) and Cases (an archive box), the sidebar toggle of the tool bar, and the magnifier of the find
fields.

They are drawn from paths, the ones of the approved mockups (an 18-unit box and a stroke of 1.6
for the sidebar), so they are as sharp at 1x as at 2x and take any colour. ``draw`` paints one on
a painter, which is how a widget that paints itself uses them, and ``icon`` and ``pixmap`` make a
``QIcon`` and a ``QPixmap`` of one for the places that want those.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_TOKEN = re.compile(r"[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4}


def svg_path(data: str) -> QPainterPath:
    """The path an SVG ``d`` attribute describes. The commands are the ones the mockups use: M, L,
    H, V, C, S and Z, each in its absolute (capital) and its relative (small) form.
    """
    tokens = _TOKEN.findall(data)
    path = QPainterPath()
    x = y = start_x = start_y = 0.0
    handle: tuple[float, float] | None = None  # the second handle of the curve before, for S
    command = ""
    i = 0
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command.upper() not in _ARITY and command not in "Zz":
                raise ValueError(f"The path command {command} is not known here.")
            if command in "Zz":
                path.closeSubpath()
                x, y, handle = start_x, start_y, None
                continue
        elif command in ("M", "m"):  # numbers after a move go on as lines
            command = "L" if command == "M" else "l"
        n = _ARITY[command.upper()]
        numbers = [float(token) for token in tokens[i : i + n]]
        i += n
        dx, dy = (x, y) if command.islower() else (0.0, 0.0)
        kind = command.upper()
        if kind == "M":
            x, y = numbers[0] + dx, numbers[1] + dy
            path.moveTo(x, y)
            start_x, start_y, handle = x, y, None
        elif kind == "L":
            x, y = numbers[0] + dx, numbers[1] + dy
            path.lineTo(x, y)
            handle = None
        elif kind == "H":
            x = numbers[0] + dx
            path.lineTo(x, y)
            handle = None
        elif kind == "V":
            y = numbers[0] + dy
            path.lineTo(x, y)
            handle = None
        elif kind == "C":
            first = (numbers[0] + dx, numbers[1] + dy)
            second = (numbers[2] + dx, numbers[3] + dy)
            x, y = numbers[4] + dx, numbers[5] + dy
            path.cubicTo(QPointF(*first), QPointF(*second), QPointF(x, y))
            handle = second
        else:  # S: the first handle is the mirror of the last one in the point the curve starts
            first = (2 * x - handle[0], 2 * y - handle[1]) if handle else (x, y)
            second = (numbers[0] + dx, numbers[1] + dy)
            x, y = numbers[2] + dx, numbers[3] + dy
            path.cubicTo(QPointF(*first), QPointF(*second), QPointF(x, y))
            handle = second
    return path


def _with(path: QPainterPath, *more: QPainterPath) -> QPainterPath:
    for other in more:
        path.addPath(other)
    return path


def _mask() -> QPainterPath:
    # A document with a folded corner, and the little mask on it.
    return _with(
        svg_path("M5 2.5h5.5L14 6v9.5H5z M10.5 2.5V6H14"),
        svg_path("M7 10.5c0-1 .9-1.5 2-1.5s2 .5 2 1.5-.9 2-2 2-2-1-2-2z"),
    )


def _restore() -> QPainterPath:
    # A key: the ring, and the shaft with two teeth.
    ring = QPainterPath()
    ring.addEllipse(QPointF(6.5, 9), 3.5, 3.5)
    return _with(ring, svg_path("M10 9h6M13.5 9v2.5M15.5 9v2"))


def _cases() -> QPainterPath:
    # An archive box: the lid, the box under it and the handle.
    lid = QPainterPath()
    lid.addRoundedRect(QRectF(2.5, 4, 13, 3.5), 1, 1)
    return _with(lid, svg_path("M4 7.5v7h10v-7"), svg_path("M7.5 10.5h3"))


def _sidebar() -> QPainterPath:
    # A window with its sidebar marked off on the left.
    window = QPainterPath()
    window.addRoundedRect(QRectF(0.75, 0.75, 14.5, 12.5), 2.5, 2.5)
    return _with(window, svg_path("M5.5 0.75V13.25"))


def _search() -> QPainterPath:
    glass = QPainterPath()
    glass.addEllipse(QPointF(6, 6), 4.2, 4.2)
    return _with(glass, svg_path("M9.2 9.2L12.5 12.5"))


class _Icon(NamedTuple):
    width: float  # the box the drawing is made in, in units
    height: float
    stroke: float  # the width of its line, in units
    shape: Callable[[], QPainterPath]


_ICONS: dict[str, _Icon] = {
    "mask": _Icon(18, 18, 1.6, _mask),
    "restore": _Icon(18, 18, 1.6, _restore),
    "cases": _Icon(18, 18, 1.6, _cases),
    "sidebar": _Icon(16, 14, 1.5, _sidebar),
    "search": _Icon(14, 14, 1.6, _search),
}
NAMES = tuple(_ICONS)


def draw(painter: QPainter, name: str, rect: QRectF, colour: QColor | str) -> None:
    """Paint the icon ``name`` in ``colour``, as large as fits in ``rect`` and in the middle of it.
    The painter's own settings are left as they were.
    """
    spec = _ICONS[name]
    scale = min(rect.width(), rect.height()) / max(spec.width, spec.height)
    pen = QPen(QColor(colour), spec.stroke)  # the stroke scales with the drawing
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(
        rect.x() + (rect.width() - spec.width * scale) / 2,
        rect.y() + (rect.height() - spec.height * scale) / 2,
    )
    painter.scale(scale, scale)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(spec.shape())
    painter.restore()


def pixmap(name: str, colour: QColor | str, size: int = 18, ratio: float = 1.0) -> QPixmap:
    """The icon ``name`` in a square of ``size`` points, as a pixmap of ``ratio`` pixels to the
    point (2 for a Retina screen).
    """
    if name not in _ICONS:
        raise KeyError(name)  # before the painter: a pixmap must not be dropped while it paints
    result = QPixmap(round(size * ratio), round(size * ratio))
    result.setDevicePixelRatio(ratio)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    try:
        draw(painter, name, QRectF(0, 0, size, size), colour)
    finally:
        painter.end()
    return result


def icon(name: str, colour: QColor | str, size: int = 18) -> QIcon:
    """The icon ``name`` in ``colour`` for a square of ``size`` points: it holds a 1x and a 2x
    pixmap, and Qt takes the one that fits the screen.
    """
    result = QIcon()
    for ratio in (1.0, 2.0):
        result.addPixmap(pixmap(name, colour, size, ratio))
    return result
