"""The illustrations of the screens: PNG files drawn by ``tools/make_art.py`` (the mask on a
document of the home screen, the document with a check of the restore screen), each in a light
and a dark form and at 1x and 2x.

The files are named ``<kind>-<appearance>.png`` and ``<kind>-<appearance>@2x.png``. ``pixmap``
loads one by its name, ``icon`` makes the 1x and the 2x of a kind and appearance one icon, so that
Qt takes the sharp one on a Retina screen, and ``Illustration`` is the widget that shows a kind in
the appearance of its palette.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget

from themask.ui.theme import appearance_of

FOLDER = Path(__file__).resolve().parent
# The kinds of picture, and the size each is drawn at in points (the 1x file has this many pixels).
KINDS: dict[str, QSize] = {"mask": QSize(112, 88), "check": QSize(64, 64)}


def pixmap(name: str) -> QPixmap:
    """The picture in the file ``name``.png of this folder, e.g. "mask-light" or "mask-light@2x".

    The pixel ratio of a file whose name ends in @2x is 2, so that the picture is as large on the
    screen as the 1x one. Raises FileNotFoundError when there is no such picture.
    """
    result = QPixmap(str(FOLDER / f"{name}.png"))
    if result.isNull():
        raise FileNotFoundError(f"There is no picture called {name!r} in {FOLDER}.")
    if name.endswith("@2x"):
        result.setDevicePixelRatio(2.0)
    return result


def icon(kind: str, appearance: str) -> QIcon:
    """The picture of ``kind`` ("mask" or "check") for "light" or "dark", as an icon that holds
    its 1x and its 2x file.
    """
    if kind not in KINDS:
        raise KeyError(kind)
    result = QIcon()
    for suffix in ("", "@2x"):
        result.addPixmap(pixmap(f"{kind}-{appearance}{suffix}"))
    return result


class Illustration(QWidget):
    """A picture of ``kind`` at its natural size, drawn in the appearance its palette is in (so it
    follows light and dark with the rest of the window) and dimmed while it is disabled.
    """

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = KINDS[kind]
        self._kind = kind
        self._icons: dict[str, QIcon] = {}
        self.setFixedSize(self._size)

    def sizeHint(self) -> QSize:
        return self._size

    def paintEvent(self, event: QPaintEvent) -> None:
        appearance = appearance_of(self.palette())
        if appearance not in self._icons:
            self._icons[appearance] = icon(self._kind, appearance)
        painter = QPainter(self)
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        self._icons[appearance].paint(painter, self.rect(), Qt.AlignmentFlag.AlignCenter, mode)
