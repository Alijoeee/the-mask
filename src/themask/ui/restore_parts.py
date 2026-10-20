"""The parts of the Restore screen that are widgets of their own: the grid that previews the values
a case would put back, the lines of a list of what the AI changed (a check box, the placeholder as
the AI wrote it and what it stands for), and the file card, which is the home screen's drop zone
dressed as the mockup's card. The screen itself is in ``restore_screen``, whose style sheet draws
them (by the object names they set).
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPointF,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from themask.ui.cards import tokens_for
from themask.ui.drop_zone import DropZone
from themask.ui.theme import mono_font
from themask.ui.widgets import ElidedLabel

DROP_TITLE = "Drop the AI\N{RIGHT SINGLE QUOTATION MARK}s Word file here"
DROP_HINT = "The .docx file the AI tool gave back, with the placeholders in it."
CHOOSE_FILE = "Choose file\N{HORIZONTAL ELLIPSIS}"
CHANGE_ROW = 26  # points: the height of a line of a list of changes
ARROW = " \N{RIGHTWARDS ARROW} "
SEPARATOR = "  \N{RIGHTWARDS ARROW}  "  # between how the AI wrote it and what it stands for


class PreviewGrid(QWidget):
    """The values the selected case would put back, three to a row as "[PLACEHOLDER] → value"
    (the placeholder in the mono font, secondary), and "and 9 more" after the last.

    ``show_lines`` fills it; ``lines()`` and ``more_text()`` say in words what it shows, and
    ``text()`` the lines one under the other.
    """

    COLUMNS = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(6)
        for column in range(self.COLUMNS):
            self._grid.setColumnStretch(column, 1)
        self._lines: list[tuple[str, str]] = []
        self._more = 0

    def show_lines(self, lines: list[tuple[str, str]], more: int) -> None:
        """Show ``lines`` ((placeholder, value) pairs) and "and ``more`` more" when there are."""
        if lines == self._lines and more == self._more:
            return
        self._lines, self._more = list(lines), more
        while (item := self._grid.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        cells = [self._cell(placeholder, value) for placeholder, value in lines]
        if more > 0:
            note = QLabel(f"and {more} more")
            note.setObjectName("previewMore")
            cells.append(note)
        for number, cell in enumerate(cells):
            cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self._grid.addWidget(cell, number // self.COLUMNS, number % self.COLUMNS)

    def lines(self) -> list[str]:
        """The lines shown, each as "[PLACEHOLDER] → value"."""
        return [f"{placeholder}{ARROW}{value}" for placeholder, value in self._lines]

    def more_text(self) -> str:
        """ "and 9 more", or nothing when everything is shown."""
        return f"and {self._more} more" if self._more > 0 else ""

    def text(self) -> str:
        return "\n".join(self.lines())

    @staticmethod
    def _cell(placeholder: str, value: str) -> QWidget:
        token = QLabel(placeholder)
        token.setObjectName("previewToken")
        token.setFont(mono_font(12))
        token.setTextFormat(Qt.TextFormat.PlainText)
        what = QLabel(f"\N{RIGHTWARDS ARROW} {value}")
        what.setObjectName("previewValue")
        what.setTextFormat(Qt.TextFormat.PlainText)  # a value may hold < > or &
        what.setWordWrap(True)
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(token, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(what, 1)
        return cell


class ChangeDelegate(QStyledItemDelegate):
    """Draws a line of a list of changes as the notice card does: a check box in the accent
    colour, how the AI wrote the placeholder in the mono font, and what it stands for (and where)
    in a quieter colour. A click on the line and the space key tick it.
    """

    BOX = 14

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(0, CHANGE_ROW)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        t = tokens_for(option.widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        box = QRectF(rect.left() + 1.5, rect.center().y() - self.BOX / 2 + 0.5, self.BOX, self.BOX)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
        if checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.accent))
            painter.drawRoundedRect(box, 3.5, 3.5)
            tick = QPen(QColor(t.on_accent), 1.8)
            tick.setCapStyle(Qt.PenCapStyle.RoundCap)
            tick.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(tick)
            painter.drawPolyline(
                [
                    QPointF(box.left() + 3.2, box.top() + 7.4),
                    QPointF(box.left() + 5.9, box.top() + 10.0),
                    QPointF(box.left() + 10.8, box.top() + 4.2),
                ]
            )
        else:
            painter.setPen(QPen(QColor(t.border_strong), 1.4))
            painter.setBrush(QColor(t.panel))
            painter.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 3, 3)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        token, found, rest = text.partition(SEPARATOR)
        left = int(box.right()) + 10
        space = rect.right() - left
        mono = mono_font(12)
        painter.setFont(mono)
        painter.setPen(QColor(t.text))
        metrics = painter.fontMetrics()
        token_text = metrics.elidedText(token, Qt.TextElideMode.ElideRight, space)
        line = rect.adjusted(left - rect.left(), 0, 0, 0)
        painter.drawText(
            line, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, token_text
        )
        if found:
            gap = metrics.horizontalAdvance(token_text) + 10
            font = QFont(option.font)
            font.setPixelSize(12)
            painter.setFont(font)
            painter.setPen(QColor(t.notice_text))
            tail = painter.fontMetrics().elidedText(
                f"\N{RIGHTWARDS ARROW} {rest}", Qt.TextElideMode.ElideRight, space - gap
            )
            if space - gap > 20:
                painter.drawText(
                    line.adjusted(gap, 0, 0, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    tail,
                )
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor(t.accent), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(rect).adjusted(0.6, 1.6, -0.6, -1.6), 5, 5)
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        flags = model.flags(index)
        if not (flags & Qt.ItemFlag.ItemIsUserCheckable and flags & Qt.ItemFlag.ItemIsEnabled):
            return False
        toggle = False
        if isinstance(event, QMouseEvent) and event.type() == QEvent.Type.MouseButtonRelease:
            toggle = event.button() == Qt.MouseButton.LeftButton
        elif isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            toggle = event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select)
        if not toggle:
            return False
        ticked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
        state = Qt.CheckState.Unchecked if ticked else Qt.CheckState.Checked
        return bool(model.setData(index, state.value, Qt.ItemDataRole.CheckStateRole))


class FileCard(DropZone):
    """The drop zone of the AI's Word file, dressed as the file card of the mockup: the picture
    of a document with a check, the name of the file (the invitation to drop one until there is
    a file) in 15-point weight 600, a caption, and the button that chooses a file.

    It is the drop zone of the home screen as it is, with its own object name (so that this
    screen's style sheet draws it, not the home screen's) and its own spacing; everything that
    takes and refuses files is the drop zone's.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            suffixes=frozenset({".docx"}),
            title=DROP_TITLE,
            hint=DROP_HINT,
            dialog_title="Choose the AI's Word file",
            file_filter="Word files (*.docx)",
            art="check",
            choose_text=CHOOSE_FILE,
            shortcut_hint=None,
        )
        self.setObjectName("fileCard")
        self.setMinimumHeight(0)
        self.choose_button.setProperty("small", True)
        # A name without a space in it cannot wrap: the title is cut in the middle instead.
        old = self.title_label
        title = ElidedLabel(old.text(), elide=Qt.TextElideMode.ElideMiddle)
        title.setObjectName("fileName")
        title.setTextFormat(Qt.TextFormat.PlainText)  # a file name may hold < >
        title.setFont(old.font())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = self.layout()
        if isinstance(layout, QBoxLayout):
            layout.replaceWidget(old, title)
        old.deleteLater()
        old.hide()
        self.title_label = title
        self.hint_label.setObjectName("fileCaption")
        if layout is not None:
            layout.setContentsMargins(20, 22, 20, 22)
            layout.setSpacing(8)

    def add_line(self, label: QLabel) -> None:
        """Put ``label`` under the caption, above the button."""
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_layout.addWidget(label)
