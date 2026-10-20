"""The sidebar of the window: the three sections (Mask, Restore, Cases), the one that is chosen on
the accent, and under them a note that goes with the screen that is showing.

The sections are real buttons: they are reached with Tab, the arrows move between them, Space and
Return choose one, and they paint themselves from the palette they are in, so that they follow
light and dark with the rest of the window. A click only asks (``sectionRequested``): which
section is chosen is the window's to say (``set_current``), because the Mask section also stands
for the review, and because the sections are switched off while a file is analysed.

The note under the sections is one block for each screen: the engine's state and where the
settings are (home), the legend of the colours (review), and a sentence of what the screen's
work leaves behind (restore, cases).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFocusEvent, QFont, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from themask.model import PlaceholderType
from themask.ui import icons, theme
from themask.ui.theme import TYPE_COLOURS
from themask.ui.widgets import Swatch, is_keyboard_focus

WIDTH = 220
ITEM_HEIGHT = 34
ICON_SIZE = 18
# The sections, in order: the name the window asks for, the icon and the words.
SECTIONS = (
    ("mask", "mask", "Mask"),
    ("restore", "restore", "Restore"),
    ("cases", "cases", "Cases"),
)
# The section each screen of the window belongs to: the review is a part of Mask.
SECTION_OF_SCREEN = {"home": "mask", "review": "mask", "restore": "restore", "cases": "cases"}

ENGINE_TEXT = {
    "ready": "Engine ready · offline",
    "loading": "Loading the engine…",
    "problem": "The engine is not available",
}
# The token the colour of the dot is, for each state of the engine.
DOT_TOKEN = {"ready": "success", "loading": "tertiary", "problem": "danger"}
SETTINGS_HINT = "Settings: The MASK › Settings… (⌘,)"
RESTORE_NOTE = (
    "The restored file is written next to the AI’s file, never over it."
    " Copied text is on the clipboard in clear."
)
LEGEND = (
    ("Person", PlaceholderType.PERSON),
    ("Company", PlaceholderType.COMPANY),
    ("Amount", PlaceholderType.AMOUNT),
    ("Address", PlaceholderType.ADDRESS),
    ("E-mail", PlaceholderType.EMAIL),
    ("IBAN", PlaceholderType.IBAN),
)


def cases_note(days: int) -> str:
    """What the Cases screen's note says of the time a case is kept."""
    return (
        f"A case expires {days} {'day' if days == 1 else 'days'} after its export (change it in"
        " Settings). An expired or deleted case can never restore its files."
    )


class SidebarItem(QPushButton):
    """One section: its icon and its name, 34 points high, on the accent when it is chosen.

    It is a checkable button whose check mark the sidebar sets, not a click: ``click`` does not
    change which item is chosen.
    """

    neighbourRequested = Signal(int)  # -1 for the arrow up, 1 for the arrow down

    def __init__(self, icon_name: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._icon_name = icon_name
        self.setCheckable(True)
        self.setFlat(True)
        self.setFixedHeight(ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # a click does not leave a ring behind
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setAccessibleName(text)
        self._ring = False  # the focus ring shows when the keyboard brought the focus

    def focusInEvent(self, event: QFocusEvent) -> None:
        self._ring = is_keyboard_focus(event.reason())
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._ring = False
        super().focusOutEvent(event)

    def nextCheckState(self) -> None:
        """A click does not check the item: the window says which section is chosen."""

    def sizeHint(self) -> QSize:
        return QSize(WIDTH - 20, ITEM_HEIGHT)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.neighbourRequested.emit(-1 if key == Qt.Key.Key_Up else 1)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        t = theme.tokens_of(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        area = QRectF(self.rect())
        ink = QColor(t.text)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.accent))
            painter.drawRoundedRect(area, 8, 8)
            ink = QColor(t.on_accent)
        elif self.isEnabled() and self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.hairline))
            painter.drawRoundedRect(area, 8, 8)
        icon_box = QRectF(10, (area.height() - ICON_SIZE) / 2, ICON_SIZE, ICON_SIZE)
        icons.draw(painter, self._icon_name, icon_box, ink)
        font = self.font()
        font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(ink)
        text_x = 10 + ICON_SIZE + 10
        painter.drawText(
            QRectF(text_x, 0, area.width() - text_x - 10, area.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
        if self.hasFocus() and self._ring:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.text), 1.5))
            painter.drawRoundedRect(area.adjusted(1.5, 1.5, -1.5, -1.5), 7, 7)


class StatusDot(QWidget):
    """A dot of 8 points that says how the engine is: green when it is ready, red when it could
    not be loaded, grey while it loads.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = "ready"
        self.setFixedSize(8, 8)

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        if state not in DOT_TOKEN:
            raise ValueError(f"Not an engine state: {state!r}.")
        self._state = state
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(getattr(theme.tokens_of(self), DOT_TOKEN[self._state])))
        painter.drawEllipse(QRectF(self.rect()))


def _note(text: str = "") -> QLabel:
    """A label of the notes under the sections: small, secondary and wrapping."""
    label = QLabel(text)
    label.setObjectName("sidebarNote")
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _block(*layouts_and_widgets: QWidget | QHBoxLayout | QGridLayout, spacing: int = 6) -> QWidget:
    """A page of the notes' stack, its content at the foot of the sidebar."""
    page = QWidget()
    box = QVBoxLayout(page)
    box.setContentsMargins(10, 10, 10, 6)
    box.setSpacing(spacing)
    box.addStretch(1)
    for part in layouts_and_widgets:
        if isinstance(part, QWidget):
            box.addWidget(part)
        else:
            box.addLayout(part)
    return page


class Sidebar(QFrame):
    """The sections and the notes of the window (see the module).

    ``items`` are the sections by name ("mask", "restore", "cases"). ``sectionRequested(name)`` is
    sent when one is clicked, or chosen with the keyboard. ``set_context(screen)`` shows the note
    of a screen ("home", "review", "restore" or "cases").
    """

    sectionRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAccessibleName("Sections")
        self.setFixedWidth(WIDTH)
        self.items: dict[str, SidebarItem] = {}
        self._notes = QStackedWidget()
        self._pages: dict[str, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(2)
        for name, icon_name, text in SECTIONS:
            item = SidebarItem(icon_name, text)
            item.clicked.connect(
                lambda checked=False, section=name: self.sectionRequested.emit(section)
            )
            item.neighbourRequested.connect(lambda step, it=item: self._focus_beside(it, step))
            self.items[name] = item
            layout.addWidget(item)
        layout.addStretch(1)
        layout.addWidget(self._notes)

        self.engine_dot = StatusDot()
        self.engine_label = _note(ENGINE_TEXT["ready"])
        self.settings_hint = _note(SETTINGS_HINT)
        engine = QHBoxLayout()
        engine.setSpacing(8)
        engine.addWidget(self.engine_dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        engine.addWidget(self.engine_label, 1)
        self._add_page("home", _block(engine, self.settings_hint))

        self.legend: dict[str, Swatch] = {}
        self._add_page("review", self._legend_block())
        self.restore_note = _note(RESTORE_NOTE)
        self._add_page("restore", _block(self.restore_note))
        self.cases_note = _note(cases_note(30))
        self._add_page("cases", _block(self.cases_note))
        self.set_current("mask")

    # ---- what the window says ---------------------------------------------------------------

    def current(self) -> str | None:
        """The section that is chosen, if any."""
        return next((name for name, item in self.items.items() if item.isChecked()), None)

    def set_current(self, section: str | None) -> None:
        """Choose ``section`` (None chooses none)."""
        for name, item in self.items.items():
            item.setChecked(name == section)

    def set_navigation_enabled(self, enabled: bool) -> None:
        """Switch the sections on or off (they are off while a file is analysed)."""
        for item in self.items.values():
            item.setEnabled(enabled)

    def set_context(self, screen: str) -> None:
        """Show the note of ``screen``. Raises KeyError for a screen that has none."""
        self._notes.setCurrentIndex(self._pages[screen])

    def context(self) -> str:
        """The screen whose note is showing."""
        index = self._notes.currentIndex()
        return next(name for name, page in self._pages.items() if page == index)

    def set_engine_state(self, state: str) -> None:
        """Say how the engine is: "ready", "loading" or "problem"."""
        if state not in ENGINE_TEXT:
            raise ValueError(f"Not an engine state: {state!r}.")
        self.engine_dot.set_state(state)
        self.engine_label.setText(ENGINE_TEXT[state])

    def set_retention_days(self, days: int) -> None:
        """Tell the note of the Cases screen how many days a case is kept."""
        self.cases_note.setText(cases_note(days))

    # ---- building and moving the focus ------------------------------------------------------

    def _add_page(self, screen: str, page: QWidget) -> None:
        self._pages[screen] = self._notes.addWidget(page)

    def _legend_block(self) -> QWidget:
        title = QLabel("Legend")
        title.setObjectName("legendTitle")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for index, (name, kind) in enumerate(LEGEND):
            swatch = Swatch(TYPE_COLOURS[kind])
            self.legend[name] = swatch
            row = QHBoxLayout()
            row.setSpacing(5)
            row.addWidget(swatch, alignment=Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(_note(name), 1)
            grid.addLayout(row, index // 2, index % 2)
        return _block(title, grid, spacing=2)

    def _focus_beside(self, item: SidebarItem, step: int) -> None:
        items = list(self.items.values())
        index = items.index(item) + step
        if 0 <= index < len(items) and items[index].isEnabled():
            items[index].setFocus(Qt.FocusReason.TabFocusReason)
