"""Small widgets the screens share: a label that cuts a long line short, a button that looks like
a link, and a small square of colour.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPalette, QResizeEvent
from PySide6.QtWidgets import QLabel, QPushButton, QWidget


def is_keyboard_focus(reason: Qt.FocusReason) -> bool:
    """Whether a widget that got the focus for ``reason`` should show a focus ring: it did by the
    keyboard (Tab, Shift-Tab or a shortcut), not because its window opened or it was clicked.
    """
    return reason in (
        Qt.FocusReason.TabFocusReason,
        Qt.FocusReason.BacktabFocusReason,
        Qt.FocusReason.ShortcutFocusReason,
    )


class ElidedLabel(QLabel):
    """A label of one line that cuts its text short with an ellipsis when it has no room for all
    of it, and then says all of it in its tooltip.

    The label's ``text`` is always the whole line, which is what a screen reader reads. It asks
    for the room the whole line needs but may be made as narrow as the layout wants.
    """

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        elide: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
    ) -> None:
        super().__init__(text, parent)
        self._elide = elide
        self._update_tooltip()

    def displayed_text(self) -> str:
        """The text as it is drawn now: all of it, or cut short."""
        return self.fontMetrics().elidedText(self.text(), self._elide, self.contentsRect().width())

    def setText(self, text: str) -> None:
        super().setText(text)
        self._update_tooltip()

    def sizeHint(self) -> QSize:
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(width + margins.left() + margins.right(), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_tooltip()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        area: QRect = self.contentsRect()
        self.style().drawItemText(
            painter,
            area,
            int(self.alignment() | Qt.AlignmentFlag.AlignVCenter),
            self.palette(),
            self.isEnabled(),
            self.displayed_text(),
            QPalette.ColorRole.WindowText,
        )

    def _update_tooltip(self) -> None:
        self.setToolTip(self.text() if self.displayed_text() != self.text() else "")


class LinkButton(QPushButton):
    """A button that looks like a link (the accent's colour, no frame) and acts like a button:
    it can be reached with Tab and pressed with Space, which a link in a label cannot.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("link")
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)


class Swatch(QWidget):
    """A small rounded square in one colour: the key of the legend, the chip of a placeholder type."""

    def __init__(
        self, colour: str, size: int = 9, radius: float = 2, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._colour = QColor(colour)
        self._radius = radius
        self.setFixedSize(size, size)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._colour)
        painter.drawRoundedRect(QRectF(self.rect()), self._radius, self._radius)
