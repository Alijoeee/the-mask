"""The parts the export sheet, the restore screen and the cases screen are made of.

``Themed`` gives a widget a style sheet made from the tokens of the appearance it is shown in and
makes it again when the system changes between light and dark (the sheet of the application,
``theme.stylesheet``, is made the same way, but it is one for the whole window and these screens
need rules of their own: cards, captions, small buttons). ``style_vars`` are the values such a
sheet is filled with: the tokens, and the few colours of the mockups that no token names.

The rest draws itself from the tokens of its own palette (``theme.tokens_of``), so it follows the
appearance without any wiring: ``MarkBadge`` (the round check or exclamation mark of a result),
``DocGlyph`` (the little document of a file card) and ``TickLabel`` (a line of text that starts
with a tick). ``FlowLayout`` lays cards out side by side and wraps them onto the next row when the
window is narrow. ``folder_trail`` writes a folder the way the mockups do: Documents › The MASK.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QLabel, QLayout, QLayoutItem, QWidget

from themask.ui.theme import Appearance, Tokens, appearance_of, tokens, tokens_of

# The colours the approved mockups use that no theme token is: the ground of a file card (the
# window's ground in the light appearance, the sidebar's in the dark one), the text on the
# accent-soft box of the export sheet, the grey of an explanation on the notice card, and the
# little document.
_EXTRAS: dict[str, dict[str, str]] = {
    "light": {
        "soft_ground": "#FBFAF8",
        "soft_text": "#5B4300",
        "change_text": "#6B655E",
        "glyph_fill": "#FFFFFF",
        "glyph_stroke": "#C9C2B8",
        "glyph_fold": "#F3F0EB",
    },
    "dark": {
        "soft_ground": "#262523",
        "soft_text": "#E8D2C0",
        "change_text": "#C9BFAE",
        "glyph_fill": "#33312D",
        "glyph_stroke": "#6B655E",
        "glyph_fold": "#3A3733",
    },
}


def appearance_name(t: Tokens) -> Appearance:
    """The appearance the tokens ``t`` belong to."""
    return "dark" if t == tokens("dark") else "light"


def blend(top: str, bottom: str, amount: float) -> str:
    """``top`` laid over ``bottom`` with ``amount`` (0 to 1) of its strength, as ``#RRGGBB``."""
    one, other = QColor(top), QColor(bottom)

    def channel(a: int, b: int) -> int:
        return round(a * amount + b * (1 - amount))

    mixed = QColor(
        channel(one.red(), other.red()),
        channel(one.green(), other.green()),
        channel(one.blue(), other.blue()),
    )
    return mixed.name().upper()


def style_vars(t: Tokens) -> dict[str, str]:
    """What a style sheet of these screens is filled with: every token by its name, the colours
    of ``_EXTRAS``, ``accent_ink`` (the accent for text: the brand colour is too pale to read
    as small text on the white panel and on a chosen row, so text takes the darker shade the
    theme keeps for the hover of a button), and the red tints of a card that says something
    went wrong (``danger_bg``, ``danger_disc`` for a round badge on it and ``danger_border``:
    the danger colour laid over the panel, thinly to strongly; thinner in the dark appearance,
    where the red is the brighter and the text on the tint would lose its contrast).
    """
    appearance = appearance_name(t)
    thin = 0.10 if appearance == "light" else 0.07
    values = {**asdict(t), **_EXTRAS[appearance]}
    values["accent_ink"] = t.accent_hover
    values["danger_bg"] = blend(t.danger, t.panel, thin)
    values["danger_disc"] = blend(t.danger, t.panel, 0.22)
    values["danger_border"] = blend(t.danger, t.panel, 0.40)
    return values


class Themed(QObject):
    """Keeps the style sheet of ``widget`` in step with the appearance.

    ``build(tokens)`` makes the sheet; it is set on ``widget`` now and again whenever the palette
    of ``widget`` says the appearance changed. ``after(tokens)``, if given, runs with each new
    set of tokens (for what a sheet cannot reach, such as an icon's colour). The appearance is
    read from the palette of ``widget`` itself, so ``widget`` must not be given a background by
    its own rules: the sheet is for what is inside it.
    """

    def __init__(
        self,
        widget: QWidget,
        build: Callable[[Tokens], str],
        after: Callable[[Tokens], None] | None = None,
    ) -> None:
        super().__init__(widget)
        self._widget = widget
        self._build = build
        self._after = after
        self._applied: str | None = None
        widget.installEventFilter(self)
        self.refresh()

    def refresh(self) -> None:
        """Make the sheet again if the appearance is another than the one it was made for."""
        appearance = appearance_of(self._widget.palette())
        if appearance == self._applied:
            return
        self._applied = appearance
        t = tokens(appearance)
        self._widget.setStyleSheet(self._build(t))
        if self._after is not None:
            self._after(t)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._widget and event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            self.refresh()
        return False


def folder_trail(folder: Path) -> str:
    """``folder`` as the mockups write it: Documents › The MASK. A folder in the owner's home is
    written from there, any other from its root.
    """
    try:
        parts = folder.relative_to(Path.home()).parts
    except ValueError:
        parts = tuple(part for part in folder.parts if part not in ("/", folder.anchor))
    return " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} ".join(parts) or "Home"


# ---- what draws itself -------------------------------------------------------------------------


class MarkBadge(QWidget):
    """A round badge with a mark in it: a check on the success colours (a thing is done) or an
    exclamation mark on the danger colours (something is wrong). It is drawn from the 56-unit
    box of the mockup at any size.
    """

    def __init__(
        self, kind: Literal["check", "alert"], size: int = 56, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._kind: Literal["check", "alert"] = kind
        self.setFixedSize(size, size)

    def set_kind(self, kind: Literal["check", "alert"]) -> None:
        """Show the other mark."""
        if kind != self._kind:
            self._kind = kind
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens_of(self)
        check = self._kind == "check"
        mark = QColor(t.success if check else t.danger)
        fill = QColor(t.success_bg if check else style_vars(t)["danger_disc"])
        unit = self.width() / 56.0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(2 * unit, 2 * unit, 52 * unit, 52 * unit))
        pen = QPen(mark, (3.5 if self.width() >= 48 else 4.0) * unit)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if check:
            path = QPainterPath(QPointF(16 * unit, 29 * unit))
            path.lineTo(24 * unit, 37 * unit)
            path.lineTo(40 * unit, 19 * unit)
            painter.drawPath(path)
        else:
            painter.drawLine(QPointF(28 * unit, 15 * unit), QPointF(28 * unit, 30 * unit))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mark)
            painter.drawEllipse(QPointF(28 * unit, 39 * unit), 2.6 * unit, 2.6 * unit)
        painter.end()


class DocGlyph(QWidget):
    """The little document of a file card, 34 by 40 points, as the mockup draws it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(34, 40)

    def paintEvent(self, event: QPaintEvent) -> None:
        values = style_vars(tokens_of(self))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(values["glyph_stroke"]), 1.5)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        page = QPainterPath(QPointF(3, 2))
        for x, y in ((21, 2), (31, 12), (31, 38), (3, 38)):
            page.lineTo(x, y)
        page.closeSubpath()
        painter.setPen(pen)
        painter.setBrush(QColor(values["glyph_fill"]))
        painter.drawPath(page)
        fold = QPainterPath(QPointF(21, 2))
        fold.lineTo(21, 12)
        fold.lineTo(31, 12)
        painter.setBrush(QColor(values["glyph_fold"]))
        painter.drawPath(fold)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(values["glyph_stroke"]))
        painter.drawRoundedRect(QRectF(8, 20, 18, 2.5), 1, 1)
        painter.drawRoundedRect(QRectF(8, 26, 13, 2.5), 1, 1)
        painter.end()


class TickLabel(QLabel):
    """A line of text that starts with a tick in the success colour ("Chosen from the file name")."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setContentsMargins(18, 0, 0, 0)

    def paintEvent(self, arg__1: QPaintEvent) -> None:
        super().paintEvent(arg__1)
        top = (self.height() - 12) / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(tokens_of(self).success_text), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath(QPointF(2, top + 6.5))
        path.lineTo(4.5, top + 9)
        path.lineTo(9.5, top + 3)
        painter.drawPath(path)
        painter.end()


# ---- the layout ----------------------------------------------------------------------------------


class FlowLayout(QLayout):
    """Lays its items out side by side, all of one width and one height, and as many in a row as
    fit when each is at least ``min_width`` wide; the rest wrap onto the next row (the cards of a
    screen are two across on a wide window and one under the other on a narrow one).
    """

    def __init__(self, parent: QWidget | None = None, min_width: int = 300, spacing: int = 16):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._min_width = min_width
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, arg__1: QLayoutItem) -> None:
        self._items.append(arg__1)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, arg__1: int) -> int:
        return self._arrange(QRect(0, 0, arg__1, 0), place=False)

    def setGeometry(self, arg__1: QRect) -> None:
        super().setGeometry(arg__1)
        self._arrange(arg__1, place=True)

    def sizeHint(self) -> QSize:
        shown = self._shown()
        width = len(shown) * self._min_width + max(0, len(shown) - 1) * self.spacing()
        margins = self.contentsMargins()
        width += margins.left() + margins.right()
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:
        margins = self.contentsMargins()
        width = max([self._min_width, *(item.minimumSize().width() for item in self._shown())])
        width += margins.left() + margins.right()
        return QSize(width, self.heightForWidth(width))

    def _shown(self) -> list[QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    def _height_of(self, item: QLayoutItem, width: int) -> int:
        wanted = (
            item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
        )
        return max(wanted, item.minimumSize().height())

    def _arrange(self, rect: QRect, place: bool) -> int:
        """Lay the items out in ``rect`` (when ``place``) and say how tall that takes."""
        margins = self.contentsMargins()
        shown = self._shown()
        gap = self.spacing()
        inner = rect.width() - margins.left() - margins.right()
        across = max(1, min(len(shown) or 1, (inner + gap) // (self._min_width + gap)))
        cell = max(0, (inner - (across - 1) * gap) // across)
        y = rect.y() + margins.top()
        for start in range(0, len(shown), across):
            row = shown[start : start + across]
            height = max(self._height_of(item, cell) for item in row)
            if place:
                for number, item in enumerate(row):
                    x = rect.x() + margins.left() + number * (cell + gap)
                    item.setGeometry(QRect(x, y, cell, height))
            y += height + gap
        used = y - gap - rect.y() if shown else margins.top()
        return used + margins.bottom()
