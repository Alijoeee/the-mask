"""The Cases screen: the saved cases, and what can be done with one.

A case holds the key that puts the real values back into the files The MASK masked. Each export
makes one, and it is deleted when its time is up. The table lists them, newest first: the code,
when it was made and when it expires, the files it was made from and how many values its key
holds. With a case selected the owner can restore a file with it (``restoreRequested``), add
another file to it (``addFilesRequested``: the files are analysed with the case's key, so a value
keeps its placeholder from file to file) or delete it. Deleting asks first: it cannot be undone,
and the files masked with the case can no longer be restored afterwards.

Case files that cannot be opened (damaged, or written by another computer) are not cases, so they
are not in the table; they are listed apart, with a way to delete them. "Delete all" takes every
file of the case folder, those among them, and what a crashed save left behind.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME
from themask.errors import MaskError
from themask.keystore.crypto import CORRUPT_MESSAGE
from themask.ui.drop_zone import ask_for_files, contract_paths
from themask.ui.theme import set_status

if TYPE_CHECKING:
    from themask.keystore.cases import CaseSummary
    from themask.ui.app import AppContext

COLUMNS = ("Case", "Created", "Expires", "Files", "Entries")
FILES_COLUMN = 3
CASE_ROLE = Qt.ItemDataRole.UserRole  # on the first cell of a row: the id of the case

NOT_READ = "The saved cases could not be read:"
NO_CASES = "No cases yet. A case is made each time you export a masked file."
EXPLANATION = (
    "A case holds the key that puts the real values back into the files The MASK masked. It is"
    " deleted when its time is up. Delete it sooner and those files can no longer be restored."
)
DAMAGED_MANY = (
    "These case files are damaged or were written by another computer and cannot be opened."
)


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


class CasesScreen(QWidget):
    """The saved cases of ``ctx.case_store``: ``refresh`` shows what the store holds now.

    ``table`` has a row for each case, ``unreadable_list`` a line for each file that cannot be
    opened, and ``status_label`` says what could not be done. ``restoreRequested(case_id)`` and
    ``addFilesRequested(paths, case_id)`` ask the window to go on with the selected case.
    """

    restoreRequested = Signal(str)
    addFilesRequested = Signal(list, str)  # list[Path], the id of the case

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        heading = QLabel("Cases")
        heading.setObjectName("heading")
        explanation = QLabel(EXPLANATION)
        explanation.setWordWrap(True)
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self.table = self._build_table()
        self.empty_label = QLabel(NO_CASES)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.restore_button = QPushButton("Restore from this case")
        self.restore_button.setObjectName("primary")
        self.restore_button.clicked.connect(self._restore)
        self.add_button = QPushButton("Add file to this case")
        self.add_button.setToolTip(
            "Mask another file with this case's key, so its values keep their placeholders."
        )
        self.add_button.clicked.connect(self._add_file)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete)
        self.delete_all_button = QPushButton("Delete all")
        self.delete_all_button.clicked.connect(self._delete_all)
        self.unreadable_label = QLabel()
        self.unreadable_label.setObjectName("notice")
        self.unreadable_label.setWordWrap(True)
        self.unreadable_list = QListWidget()
        self.unreadable_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.unreadable_list.setMaximumHeight(90)
        self.unreadable_list.itemSelectionChanged.connect(self._update_buttons)
        self.delete_unreadable_button = QPushButton("Delete damaged file")
        self.delete_unreadable_button.clicked.connect(self._delete_unreadable)

        buttons = QHBoxLayout()
        for button in (self.restore_button, self.add_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_all_button)
        damaged = QHBoxLayout()
        damaged.addWidget(self.unreadable_list, 1)
        damaged.addWidget(self.delete_unreadable_button, alignment=Qt.AlignmentFlag.AlignTop)
        self._damaged = (self.unreadable_label, self.unreadable_list, self.delete_unreadable_button)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(explanation)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty_label, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.unreadable_label)
        layout.addLayout(damaged)
        self.refresh()

    # ---- the interface the rest of the app uses --------------------------------------------

    def refresh(self) -> None:
        """Show the cases the store holds now, and the files of its folder that cannot be opened.

        A store that cannot be read (the Keychain refuses, the folder is closed to the app) is
        said in the status line; the app goes on.
        """
        store = self.ctx.case_store
        try:
            summaries = store.list()
        except MaskError as error:
            self._show_unreadable(error.user_message)
            return
        except OSError as error:
            self._show_unreadable(f"{NOT_READ} {error.strerror or error}")
            return
        set_status(self.status_label, "")
        self._show(summaries, [path.name for path in store.unreadable])

    # ---- building the screen ---------------------------------------------------------------

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(COLUMNS))
        table.setHorizontalHeaderLabels(list(COLUMNS))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(FILES_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.itemSelectionChanged.connect(self._update_buttons)
        return table

    def _show_unreadable(self, message: str) -> None:
        """Say that the store cannot be read. It is not empty as far as anyone knows, so the
        screen does not say there are no cases.
        """
        self._show([], [])
        self.empty_label.hide()
        set_status(self.status_label, message, problem=True)

    def _show(self, summaries: list[CaseSummary], damaged: list[str]) -> None:
        self.table.clearSelection()
        self.table.setRowCount(len(summaries))
        for row, summary in enumerate(summaries):
            cells = (
                summary.id,
                format_moment(summary.created_at),
                format_expiry(summary.expires_at),
                ", ".join(summary.source_files),
                str(summary.n_entries),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if column == 0:
                    item.setData(CASE_ROLE, summary.id)
                if column == FILES_COLUMN:
                    item.setToolTip("\n".join(summary.source_files))
                self.table.setItem(row, column, item)
        self.table.setVisible(bool(summaries))
        self.empty_label.setVisible(not summaries)
        self.unreadable_list.clear()
        self.unreadable_list.addItems(damaged)
        self.unreadable_label.setText(CORRUPT_MESSAGE if len(damaged) == 1 else DAMAGED_MANY)
        for widget in self._damaged:
            widget.setVisible(bool(damaged))
        self._update_buttons()

    def _update_buttons(self) -> None:
        """Offer what can be done with what is selected."""
        case_selected = self._selected_case() is not None
        for button in (self.restore_button, self.add_button, self.delete_button):
            button.setEnabled(case_selected)
        self.delete_all_button.setEnabled(
            self.table.rowCount() > 0 or self.unreadable_list.count() > 0
        )
        self.delete_unreadable_button.setEnabled(bool(self.unreadable_list.selectedItems()))

    def _selected_case(self) -> str | None:
        """The id of the case whose row is selected, if one is."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return None if item is None else str(item.data(CASE_ROLE))

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
        cases, damaged = self.table.rowCount(), self.unreadable_list.count()
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

    def _delete_unreadable(self) -> None:
        selected = self.unreadable_list.selectedItems()
        if not selected:
            return
        name = selected[0].text()
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
