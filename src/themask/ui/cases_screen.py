"""The Cases screen: the saved cases, and what can be done with one.

A case holds the key that puts the real values back into the files The MASK masked. Each export
makes one, and it is deleted when its time is up. The table lists them, newest first: the code,
the files it was made from, when it was exported, when it expires and how many values its key
holds. An expiry within a week is written "in 3 days" in the danger colour. With a case selected
the owner can restore a file with it (``restoreRequested``), add another file to it
(``addFilesRequested``: the files are analysed with the case's key, so a value keeps its
placeholder from file to file) or delete it, and a card under the table says what the case holds:
its files and the masked copy, and how many values of what kind (never the values: they are shown
only on the Restore screen). The filter above the table keeps the rows whose code or file names
contain what is typed.

Deleting asks first: it cannot be undone, and the files masked with the case can no longer be
restored afterwards. "Delete…" is a button with a menu: "Delete this case" and "Delete all cases".

Case files that cannot be opened (damaged, or written by another computer) are not cases: they
stand at the end of the table as grey rows with a Delete button of their own, which asks first.
"Delete all cases" takes every file of the case folder, those among them, and what a crashed save
left behind.

The window supplies the title and the "New case" button of its tool bar: ``title()`` says what to
show (``titleChanged`` when it changes) and ``primary()`` is what the button does, it asks for a
new case (``newCaseRequested``).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from string import Template
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME
from themask.errors import MaskError
from themask.keystore.crypto import CORRUPT_MESSAGE
from themask.model import Case, PlaceholderType
from themask.ui import icons
from themask.ui.cards import TableHead, Themed, folder_trail, style_vars, tokens_for
from themask.ui.drop_zone import ask_for_files, contract_paths
from themask.ui.theme import Tokens, mono_font, set_status

if TYPE_CHECKING:
    from themask.ui.app import AppContext

TITLE = ("Cases", "The keys that put real values back \N{MIDDLE DOT} kept on this Mac, encrypted")
COLUMNS = ("Code", "Files", "Exported", "Expires", "Values")
CODE_COLUMN, FILES_COLUMN, EXPORTED_COLUMN, EXPIRES_COLUMN, VALUES_COLUMN = range(5)
COLUMN_WIDTHS = {CODE_COLUMN: 84, EXPORTED_COLUMN: 150, EXPIRES_COLUMN: 210, VALUES_COLUMN: 92}
ROW_HEIGHT = 40  # points
HEADER_HEIGHT = 32
TOOLBAR_HEIGHT = 30  # the filter and the buttons above the table
CASE_ROLE = Qt.ItemDataRole.UserRole  # on the first cell of a row: the id of the case
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 1  # on the first cell: what the filter looks in
TONE_ROLE = (
    Qt.ItemDataRole.UserRole + 2
)  # on a cell: how it is coloured ("code", "danger", "muted")
DAMAGED_ROLE = Qt.ItemDataRole.UserRole + 3  # on the first cell of a case file that cannot open
EXPIRY_WARNING_DAYS = 7  # an expiry this near is written in the danger colour

NOT_READ = "The saved cases could not be read:"
NO_CASES = "No cases yet. A case is made each time you export a masked file."
NO_MATCH = "No case matches that filter."
FILTER_PLACEHOLDER = "Filter by file or code"
DAMAGED_MANY = (
    "These case files are damaged or were written by another computer and cannot be opened."
)
NO_FILE_NAMES = "No file names are kept for this case."
KEYCHAIN_NOTE = (
    "Encrypted with the key in your Keychain. Values are shown only on the Restore screen."
)
# What the kinds of value are called in "14 values: 2 companies, 2 people, ...": in the order they
# are listed, as (singular, plural).
KINDS: dict[PlaceholderType, tuple[str, str]] = {
    PlaceholderType.COMPANY: ("company", "companies"),
    PlaceholderType.PERSON: ("person", "people"),
    PlaceholderType.AMOUNT: ("amount", "amounts"),
    PlaceholderType.ADDRESS: ("address", "addresses"),
    PlaceholderType.EMAIL: ("e-mail", "e-mails"),
    PlaceholderType.IBAN: ("bank account", "bank accounts"),
    PlaceholderType.PERCENT: ("percentage", "percentages"),
    PlaceholderType.QUANTITY: ("quantity", "quantities"),
    PlaceholderType.PHONE: ("phone number", "phone numbers"),
    PlaceholderType.ID: ("ID", "IDs"),
    PlaceholderType.URL: ("web address", "web addresses"),
    PlaceholderType.CUSTOM: ("other value", "other values"),
}
KINDS_SHOWN = 6  # kinds the card names; the values of the rest are counted as "n more"

_SHEET = Template("""
QFrame[card="true"] {
    background: $panel;
    border: 1px solid $border;
    border-radius: 14px;
}
QLabel#empty { color: $secondary; padding: 36px 16px; }
QLineEdit#filter { min-height: 22px; padding: 2px 8px; border-radius: 8px; }
QPushButton[toolbar="true"] { min-height: 28px; border-radius: 8px; font-size: 12px; }
QToolButton#deleteButton {
    min-height: 28px;
    padding: 0 12px;
    color: $danger;
    background: $control;
    border: 1px solid $border_strong;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
}
QToolButton#deleteButton:hover { background: $hairline; }
QToolButton#deleteButton:focus { border-color: $accent; }
QToolButton#deleteButton:disabled { color: $tertiary; border-color: $border; }
QToolButton#deleteButton::menu-indicator { image: none; }
QTableWidget#casesTable {
    background: $panel;
    color: $text;
    border: 1px solid $border;
    border-radius: 12px;
    selection-background-color: $accent_soft;
    selection-color: $text;
    outline: none;
}
QTableWidget#casesTable::item { padding: 0 6px 0 10px; border-bottom: 1px solid $hairline; }
QPushButton[rowButton="true"] {
    min-height: 20px;
    padding: 0 10px;
    color: $danger;
    border-radius: 6px;
    font-size: 11px;
}
QLabel[role="kicker"] { font-size: 11px; font-weight: 600; color: $secondary; }
QLabel#caseFiles { font-size: 15px; font-weight: 600; color: $text; }
QLabel#caseNote { font-size: 12px; color: $secondary; }
QLabel#caseHolds { color: $text; }
""")


def _sheet(t: Tokens) -> str:
    return _SHEET.substitute(style_vars(t))


def confirm(parent: QWidget | None, message: str) -> bool:
    """Ask the owner a yes-or-no question before something that cannot be undone. The answer
    offered first is no.
    """
    yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
    return QMessageBox.question(parent, APP_NAME, message, yes | no, no) == yes


def format_moment(moment: datetime) -> str:
    """``moment`` on the owner's clock, written the same in every language: 2026-10-17 09:00."""
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def format_expiry(moment: datetime) -> str:
    """The day ``moment`` falls on, on the owner's clock: 2026-11-16."""
    return moment.astimezone().strftime("%Y-%m-%d")


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_date(moment: datetime) -> str:
    """The day ``moment`` falls on, on the owner's clock, as the screens say it: 18 Nov 2026
    (the month is the same three English letters in every language, as in ``format_moment``).
    """
    local = moment.astimezone()
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}"


def _days_ago(moment: datetime, now: datetime | None) -> int:
    """How many calendar days before ``now`` (by default the time it is) ``moment`` falls, on the
    owner's clock: 0 for today, 1 for yesterday.
    """
    here = (now or datetime.now().astimezone()).astimezone().date()
    return (here - moment.astimezone().date()).days


def format_when(moment: datetime, now: datetime | None = None) -> str:
    """When ``moment`` was, for a line of a list: "today 14:02", "yesterday 09:41", and for
    anything older the day, "12 Oct 2026".
    """
    clock = moment.astimezone().strftime("%H:%M")
    return {0: f"today {clock}", 1: f"yesterday {clock}"}.get(
        _days_ago(moment, now), format_date(moment)
    )


def format_exported(moment: datetime, now: datetime | None = None) -> str:
    """When a case was exported, for the Exported column: "Today, 14:02", "Yesterday, 09:41",
    and for anything older the day, "12 Oct 2026".
    """
    clock = moment.astimezone().strftime("%H:%M")
    return {0: f"Today, {clock}", 1: f"Yesterday, {clock}"}.get(
        _days_ago(moment, now), format_date(moment)
    )


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def describe_holds(counts: Mapping[PlaceholderType, int]) -> str:
    """What a case holds, as the card under the table says it: "14 values: 2 companies, 2 people,
    2 amounts, 1 address, 1 e-mail, 1 bank account, 6 more". The first ``KINDS_SHOWN`` kinds the
    case has, in the order of ``KINDS``; the values of the other kinds are counted as "n more".
    """
    total = sum(counts.values())
    kinds = [(kind, number) for kind in KINDS if (number := counts.get(kind, 0))]
    named = [
        f"{number} {KINDS[kind][0] if number == 1 else KINDS[kind][1]}"
        for kind, number in kinds[:KINDS_SHOWN]
    ]
    more = sum(number for _, number in kinds[KINDS_SHOWN:])
    if more:
        named.append(f"{more} more")
    return f"{_count(total, 'value')}: {', '.join(named)}" if named else _count(total, "value")


def days_left(expires_at: datetime, now: datetime | None = None) -> int:
    """How many days a case that expires at ``expires_at`` has left, counting a part of a day as
    a day (a case exported a moment ago has its whole 30). Zero or less when it is due.
    """
    now = now or datetime.now().astimezone()
    return math.ceil((expires_at - now).total_seconds() / 86400)


def describe_expiry(expires_at: datetime, now: datetime | None = None) -> tuple[str, bool]:
    """What the Expires column says of ``expires_at`` and whether it is near: "18 Nov 2026 · 30
    days", or within ``EXPIRY_WARNING_DAYS`` "in 3 days" (and True: the danger colour).
    """
    left = days_left(expires_at, now)
    if left <= 0:
        return "expired", True
    if left <= EXPIRY_WARNING_DAYS:
        return f"in {_count(left, 'day')}", True
    return f"{format_date(expires_at)} \N{MIDDLE DOT} {_count(left, 'day')}", False


@dataclass(frozen=True)
class CaseRow:
    """What the screen keeps of a case: what its row and its card say, and never a value."""

    id: str
    created_at: datetime
    expires_at: datetime
    source_files: list[str]
    masked_files: list[str]
    counts: dict[PlaceholderType, int]

    @classmethod
    def of(cls, case: Case) -> CaseRow:
        return cls(
            case.id,
            case.created_at,
            case.expires_at,
            list(case.source_files),
            [file.name for file in case.masked_files],
            dict(Counter(entry.type for entry in case.entries)),
        )

    @property
    def n_values(self) -> int:
        return sum(self.counts.values())


class _CaseDelegate(QStyledItemDelegate):
    """Draws the cells as the style sheet says and colours their text by tone: a code in the
    accent colour (on the chosen row, which is accent-soft, in the colour for text on it), an
    expiry that is near in the danger colour, a file that cannot be opened in the quiet one. The
    colour is looked up as the cell is drawn, so it follows the appearance, and it stays on the
    chosen row, where the view would draw every text in its own colour.
    """

    def initStyleOption(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        tone = index.data(TONE_ROLE)
        if not tone:
            return
        t = tokens_for(option.widget)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        colour = {
            "code": t.accent_text_on_soft if selected else t.accent,
            "danger": t.danger,
            "muted": t.secondary,
        }[str(tone)]
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.HighlightedText):
            option.palette.setColor(role, QColor(colour))


class FilterField(QLineEdit):
    """The filter above the table: 260 points wide when there is room, and as narrow as 140 when
    the window is not wide enough for it and the buttons beside it.
    """

    WIDTH = 260
    LEAST = 140

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(self.LEAST)
        self.setMaximumWidth(self.WIDTH)
        self.setFixedHeight(TOOLBAR_HEIGHT)

    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, TOOLBAR_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.LEAST, TOOLBAR_HEIGHT)


class CasesTable(QTableWidget):
    """The table of cases. It asks for the height of its rows, so that it is as tall as the cases
    it lists and the card under it follows, and gives way when the window is short.
    """

    def sizeHint(self) -> QSize:
        hidden = sum(self.isRowHidden(row) for row in range(self.rowCount()))
        rows = (self.rowCount() - hidden) * ROW_HEIGHT
        return QSize(super().sizeHint().width(), HEADER_HEIGHT + rows + 2)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), HEADER_HEIGHT + 3 * ROW_HEIGHT + 2)


class CasesScreen(QWidget):
    """The saved cases of ``ctx.case_store``: ``refresh`` shows what the store holds now.

    ``table`` has a row for each case and, after them, a grey row for each file that cannot be
    opened (``unreadable_buttons`` are their Delete buttons, by the name of the file);
    ``status_label`` says what could not be done. ``restoreRequested(case_id)`` and
    ``addFilesRequested(paths, case_id)`` ask the window to go on with the selected case.
    ``filter_edit`` keeps the rows that match; ``delete_button`` opens the menu whose actions are
    ``delete_case_action`` and ``delete_all_action``; ``detail_card`` says what the selected case
    holds.
    """

    restoreRequested = Signal(str)
    addFilesRequested = Signal(list, str)  # list[Path], the id of the case
    newCaseRequested = Signal()
    titleChanged = Signal(str, str)  # the title and the caption, when they change

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._rows: dict[str, CaseRow] = {}
        self._damaged: list[str] = []
        self.unreadable_buttons: dict[str, QPushButton] = {}
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self._build_toolbar()
        self.table = self._build_table()
        self.empty_label = QLabel(NO_CASES)
        self.empty_label.setObjectName("empty")
        self.empty_label.setProperty("card", True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.unreadable_label = QLabel()
        self.unreadable_label.setObjectName("notice")
        self.unreadable_label.setWordWrap(True)
        self.unreadable_label.hide()
        self.detail_card = self._build_detail()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(self.status_label)
        layout.addLayout(self._toolbar)
        layout.addWidget(self.table)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.unreadable_label)
        layout.addWidget(self.detail_card)
        layout.addStretch(1)
        Themed(self, _sheet, after=self._recolour)
        self.refresh()

    # ---- the interface the rest of the app uses --------------------------------------------

    def title(self) -> tuple[str, str]:
        """What the window shows above the screen: its title and the caption under it."""
        return TITLE

    @Slot()
    def primary(self) -> None:
        """What the "New case" button of the window does: ask for a new case."""
        self.newCaseRequested.emit()

    def refresh(self) -> None:
        """Show the cases the store holds now, and the files of its folder that cannot be opened.

        A store that cannot be read (the Keychain refuses, the folder is closed to the app) is
        said in the status line; the app goes on.
        """
        store = self.ctx.case_store
        try:
            cases = store.load_all()
        except MaskError as error:
            self._show_unreadable(error.user_message)
            return
        except OSError as error:
            self._show_unreadable(f"{NOT_READ} {error.strerror or error}")
            return
        set_status(self.status_label, "")
        self._show([CaseRow.of(case) for case in cases], [path.name for path in store.unreadable])

    # ---- building the screen ---------------------------------------------------------------

    def _build_toolbar(self) -> None:
        """The filter at the left, the three things to do with a case at the right."""
        self.filter_edit = FilterField()
        self.filter_edit.setObjectName("filter")
        self.filter_edit.setPlaceholderText(FILTER_PLACEHOLDER)
        self.filter_edit.setAccessibleName("Filter cases")
        self.filter_edit.setClearButtonEnabled(True)
        self._search_action = self.filter_edit.addAction(
            QIcon(), QLineEdit.ActionPosition.LeadingPosition
        )
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.restore_button = QPushButton("Restore from this case")
        self.restore_button.setProperty("toolbar", True)
        self.restore_button.clicked.connect(self._restore)
        self.add_button = QPushButton("Add a file to this case")
        self.add_button.setProperty("toolbar", True)
        self.add_button.setToolTip(
            "Mask another file with this case's key, so its values keep their placeholders."
        )
        self.add_button.clicked.connect(self._add_file)
        self.delete_case_action = QAction("Delete this case", self)
        self.delete_case_action.triggered.connect(self._delete)
        self.delete_all_action = QAction("Delete all cases", self)
        self.delete_all_action.triggered.connect(self._delete_all)
        menu = QMenu(self)
        menu.addAction(self.delete_case_action)
        menu.addAction(self.delete_all_action)
        self.delete_button = QToolButton()
        self.delete_button.setObjectName("deleteButton")
        self.delete_button.setText("Delete\N{HORIZONTAL ELLIPSIS}")
        self.delete_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.delete_button.setMenu(menu)
        self.delete_button.setAccessibleName("Delete\N{HORIZONTAL ELLIPSIS}")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setFixedHeight(TOOLBAR_HEIGHT)
        self._toolbar = QHBoxLayout()
        self._toolbar.setSpacing(10)
        self._toolbar.addWidget(self.filter_edit)
        self._toolbar.addStretch(1)
        for button in (self.restore_button, self.add_button, self.delete_button):
            self._toolbar.addWidget(button)

    def _build_table(self) -> CasesTable:
        table = CasesTable(0, len(COLUMNS))
        table.setObjectName("casesTable")
        table.setHorizontalHeader(TableHead(table))
        table.setHorizontalHeaderLabels(list(COLUMNS))
        table.setAccessibleName("Cases")
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setWordWrap(False)  # a long name is cut short, not set in two lines
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setItemDelegate(_CaseDelegate(table))
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        header = table.horizontalHeader()
        header.setFixedHeight(HEADER_HEIGHT)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(FILES_COLUMN, QHeaderView.ResizeMode.Stretch)
        for column, width in COLUMN_WIDTHS.items():
            header.resizeSection(column, width)
        values = table.horizontalHeaderItem(VALUES_COLUMN)
        if values is not None:
            values.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.itemSelectionChanged.connect(self._selection_changed)
        return table

    def _build_detail(self) -> QFrame:
        """The card of the selected case: its code, files and masked copy at the left, what it
        holds at the right.
        """
        self.case_kicker = self._kicker()
        self.case_files_label = self._text("caseFiles")
        self.case_copy_label = self._text("caseNote")
        self.holds_kicker = self._kicker()
        self.holds_kicker.setText("What it holds")
        self.holds_label = self._text("caseHolds")
        self.keychain_label = self._text("caseNote")
        self.keychain_label.setText(KEYCHAIN_NOTE)
        card = QFrame()
        card.setProperty("card", True)
        columns = QHBoxLayout(card)
        columns.setContentsMargins(18, 16, 18, 16)
        columns.setSpacing(32)
        for stretch, parts in (
            (2, (self.case_kicker, self.case_files_label, self.case_copy_label)),
            (3, (self.holds_kicker, self.holds_label, self.keychain_label)),
        ):
            lines = QVBoxLayout()
            lines.setSpacing(4)
            for part in parts:
                lines.addWidget(part)
            lines.addStretch(1)
            columns.addLayout(lines, stretch)
        card.setAccessibleName("The selected case")
        card.hide()
        return card

    @staticmethod
    def _kicker() -> QLabel:
        """A small label over a line of the card: 11 points, weight 600, capitals."""
        label = QLabel()
        label.setProperty("role", "kicker")
        font = QFont(label.font())
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        label.setFont(font)
        return label

    @staticmethod
    def _text(name: str) -> QLabel:
        label = QLabel()
        label.setObjectName(name)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)  # file names may hold < > or &
        return label

    def _recolour(self, t: Tokens) -> None:
        """Whatever the style sheet cannot colour: the magnifier of the filter."""
        self._search_action.setIcon(icons.icon("search", t.secondary, 14))

    # ---- showing the cases -----------------------------------------------------------------

    def _show_unreadable(self, message: str) -> None:
        """Say that the store cannot be read. It is not empty as far as anyone knows, so the
        screen does not say there are no cases.
        """
        self._show([], [])
        self.empty_label.hide()
        set_status(self.status_label, message, problem=True)

    def _show(self, rows: list[CaseRow], damaged: list[str]) -> None:
        table = self.table
        table.clearSelection()
        table.setRowCount(0)  # the cells' buttons go with their rows
        self._rows = {row.id: row for row in rows}
        self._damaged = damaged
        self.unreadable_buttons = {}
        table.setRowCount(len(rows) + len(damaged))
        for number, row in enumerate(rows):
            self._fill_case_row(number, row)
        for number, name in enumerate(damaged, start=len(rows)):
            self._fill_damaged_row(number, name)
        self.unreadable_label.setText(CORRUPT_MESSAGE if len(damaged) == 1 else DAMAGED_MANY)
        self.unreadable_label.setVisible(bool(damaged))
        self._apply_filter()
        self._selection_changed()

    def _fill_case_row(self, number: int, row: CaseRow) -> None:
        expiry, near = describe_expiry(row.expires_at)
        cells = (
            (row.id, "code"),
            (", ".join(row.source_files), ""),
            (format_exported(row.created_at), ""),
            (expiry, "danger" if near else ""),
            (str(row.n_values), ""),
        )
        for column, (text, tone) in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if tone:
                item.setData(TONE_ROLE, tone)
            if column == CODE_COLUMN:
                font = mono_font(13)
                font.setWeight(QFont.Weight.DemiBold)
                item.setFont(font)
                item.setData(CASE_ROLE, row.id)
                item.setData(SEARCH_ROLE, " ".join([row.id, *row.source_files]).casefold())
            if column in (EXPORTED_COLUMN, EXPIRES_COLUMN):
                item.setToolTip(text)  # whole, should the native style's wider text not fit
            if column == FILES_COLUMN:
                item.setToolTip("\n".join(row.source_files))
                font = item.font()
                font.setWeight(QFont.Weight.DemiBold)
                item.setFont(font)
            if column == VALUES_COLUMN:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(number, column, item)

    def _fill_damaged_row(self, number: int, name: str) -> None:
        """A grey row for a case file that cannot be opened, with a Delete button of its own."""
        cells = (
            "\N{EM DASH}",
            f"{name} \N{MIDDLE DOT} cannot be read",
            "\N{EM DASH}",
            "\N{EM DASH}",
            "",
        )
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not a case: nothing to select
            item.setData(TONE_ROLE, "muted")
            if column == CODE_COLUMN:
                item.setData(DAMAGED_ROLE, name)
                item.setData(SEARCH_ROLE, name.casefold())
                item.setFont(mono_font(13))
            if column == FILES_COLUMN:
                item.setToolTip(CORRUPT_MESSAGE)
            self.table.setItem(number, column, item)
        button = QPushButton("Delete")
        button.setProperty("rowButton", True)
        button.setAccessibleName(f"Delete {name}")
        button.clicked.connect(lambda _checked=False, file=name: self._delete_unreadable(file))
        self.unreadable_buttons[name] = button
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 8, 0)
        row.addStretch(1)
        row.addWidget(button)
        self.table.setCellWidget(number, VALUES_COLUMN, holder)

    def _apply_filter(self) -> None:
        """Keep the rows whose code or file names hold what the filter says (a file that cannot
        be opened is looked for by its name). The table is not there when no row is left, and the
        empty line says why: that nothing matches, or that there are no cases.
        """
        needle = self.filter_edit.text().strip().casefold()
        cases = damaged = 0
        for number in range(self.table.rowCount()):
            first = self.table.item(number, CODE_COLUMN)
            haystack = str(first.data(SEARCH_ROLE)) if first is not None else ""
            visible = not needle or needle in haystack
            self.table.setRowHidden(number, not visible)
            if visible:
                is_case = first is not None and first.data(CASE_ROLE) is not None
                cases, damaged = cases + is_case, damaged + (not is_case)
        selected = self._selected_case()
        if selected is not None and self._row_hidden(selected):
            self.table.clearSelection()
        self.table.setVisible(cases + damaged > 0)
        self.empty_label.setVisible(cases == 0)  # no case to be seen: there may be damaged files
        searching = bool(needle) and self.table.rowCount() > 0
        self.empty_label.setText(NO_MATCH if searching else NO_CASES)
        self.table.updateGeometry()
        self._update_buttons()

    def _row_hidden(self, case_id: str) -> bool:
        for number in range(self.table.rowCount()):
            item = self.table.item(number, CODE_COLUMN)
            if item is not None and item.data(CASE_ROLE) == case_id:
                return self.table.isRowHidden(number)
        return True

    def _selection_changed(self) -> None:
        case_id = self._selected_case()
        row = self._rows.get(case_id or "")
        self.detail_card.setVisible(row is not None)
        if row is not None:
            self._describe(row)
        self._update_buttons()

    def _describe(self, row: CaseRow) -> None:
        """Fill the card with what the case ``row`` is."""
        self.case_kicker.setText(f"Case {row.id}")
        self.case_files_label.setText(", ".join(row.source_files) or NO_FILE_NAMES)
        folder = folder_trail(self.ctx.settings.out_dir)
        if row.masked_files:
            noun = "copy" if len(row.masked_files) == 1 else "copies"
            where = f"Masked {noun}: {', '.join(row.masked_files)} in {folder}"
        else:
            where = f"Masked copies are saved in {folder}"
        self.case_copy_label.setText(where)
        self.holds_label.setText(describe_holds(row.counts))

    def _update_buttons(self) -> None:
        """Offer what can be done with what is selected."""
        case_selected = self._selected_case() is not None
        for button in (self.restore_button, self.add_button):
            button.setEnabled(case_selected)
        something = bool(self._rows) or bool(self._damaged)
        self.delete_case_action.setEnabled(case_selected)
        self.delete_all_action.setEnabled(something)
        self.delete_button.setEnabled(something)

    def _selected_case(self) -> str | None:
        """The id of the case whose row is selected, if one is."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), CODE_COLUMN)
        data = None if item is None else item.data(CASE_ROLE)
        return None if data is None else str(data)

    # ---- the buttons -----------------------------------------------------------------------

    def _restore(self) -> None:
        case_id = self._selected_case()
        if case_id is not None:
            self.restoreRequested.emit(case_id)

    def _add_file(self) -> None:
        case_id = self._selected_case()
        if case_id is None:
            return
        paths = contract_paths(ask_for_files(self))
        if paths:
            self.addFilesRequested.emit(paths, case_id)

    def _delete(self) -> None:
        case_id = self._selected_case()
        if case_id is None:
            return
        if not confirm(
            self,
            f"Delete case {case_id}? The files masked with it can then no longer be restored.",
        ):
            return
        try:
            self.ctx.case_store.delete(case_id)
        except OSError as error:
            self.refresh()
            set_status(
                self.status_label,
                f"The case could not be deleted: {error.strerror or error}",
                problem=True,
            )
            return
        self.refresh()

    def _delete_all(self) -> None:
        cases, damaged = len(self._rows), len(self._damaged)
        what = " and ".join(
            part
            for part in (
                _count(cases, "saved case") if cases else "",
                _count(damaged, "damaged case file") if damaged else "",
            )
            if part
        )
        if not confirm(
            self, f"Delete {what}? The files masked with them can then no longer be restored."
        ):
            return
        try:
            self.ctx.case_store.delete_all()
        except OSError as error:
            self.refresh()
            set_status(
                self.status_label,
                f"The cases could not be deleted: {error.strerror or error}",
                problem=True,
            )
            return
        self.refresh()

    def _delete_unreadable(self, name: str) -> None:
        if not confirm(
            self, f"Delete the case file {name}? It cannot be opened, so it cannot be used."
        ):
            return
        try:
            self.ctx.case_store.delete_unreadable(name)
        except ValueError:  # the folder changed since the list was made: show it as it is
            pass
        except OSError as error:
            self.refresh()
            set_status(
                self.status_label,
                f"The file could not be deleted: {error.strerror or error}",
                problem=True,
            )
            return
        self.refresh()
