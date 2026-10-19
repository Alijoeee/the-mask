"""The home screen: the drop card, what the app is doing, and the cases made lately.

The card (``drop_zone``) is where a contract is dropped or chosen; while the engine loads or a
file is analysed the card says so under its caption (``status_label``, ``progress_bar`` and
``step_label``), and a line that asks the owner to look (a problem that does not stop the app, a
file that was not opened) is a notice under the card (``notice_label`` and ``refused_label``).
Under that are the recent cases: up to three rows from the case store, newest first, each with the
code, the names of the files, a caption worked out from the case and a link that restores with it.
The section is not there while there are no cases.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from themask.errors import MaskError
from themask.ui import theme
from themask.ui.drop_zone import DropZone
from themask.ui.widgets import ElidedLabel, LinkButton

if TYPE_CHECKING:
    from themask.keystore.cases import CaseSummary
    from themask.ui.app import AppContext

RECENT_LIMIT = 3
COLUMN_WIDTH = 640  # the card and the cases are in a column this wide at most

# What the home screen says for each step of an analysis (the names are the worker's).
STEP_TEXT = {
    "loading": "Opening the files…",
    "reading": "Reading the text…",
    "finding": "Finding the confidential values…",
    "grouping": "Putting the values in groups…",
    "done": "Done",
}


def current_time() -> datetime:
    """Now, for the captions of the cases. Tests and the screenshots replace it."""
    return datetime.now(UTC)


def _plural(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def describe_case(summary: CaseSummary, now: datetime) -> str:
    """The caption of a case in the list, on the owner's clock: when it was exported (today with
    the time, yesterday, a few days ago, else the date), how many files it holds if more than one,
    how many values were hidden and when it expires.
    """
    created = summary.created_at.astimezone()
    days_ago = (now.astimezone().date() - created.date()).days
    if days_ago <= 0:  # a clock that went back makes a case of the future: it is of today
        when = f"Exported today at {created:%H:%M}"
    elif days_ago == 1:
        when = "Exported yesterday"
    elif days_ago < 7:
        when = f"Exported {days_ago} days ago"
    else:
        when = f"Exported on {created:%Y-%m-%d}"
    parts = [when]
    if len(summary.source_files) > 1:
        parts.append(f"{len(summary.source_files)} files")
    parts.append(f"{_plural(summary.n_entries, 'value')} hidden")
    remaining = summary.expires_at - now
    if remaining <= timedelta(0):
        parts.append("expired")
    elif remaining < timedelta(days=1):
        parts.append("expires in less than a day")
    else:
        parts.append(f"expires in {_plural(math.ceil(remaining / timedelta(days=1)), 'day')}")
    return " · ".join(parts)


class CaseRow(QFrame):
    """A row of the list: the code of a case in a chip, the names of its files over its caption,
    and the link that restores with it (``restoreRequested`` with the code).
    """

    restoreRequested = Signal(str)

    def __init__(
        self, summary: CaseSummary, now: datetime, last: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("recentRow")
        self.setProperty("last", last)  # the last row has no line under it
        self.case_id = summary.id
        self.code_label = QLabel(summary.id)
        self.code_label.setObjectName("caseCode")
        code_font = theme.mono_font(12)
        code_font.setWeight(QFont.Weight.DemiBold)
        self.code_label.setFont(code_font)
        names = ", ".join(summary.source_files) or f"Case {summary.id}"
        self.files_label = ElidedLabel(names)
        self.files_label.setObjectName("caseFiles")
        self.caption_label = ElidedLabel(describe_case(summary, now))
        self.caption_label.setObjectName("caseCaption")
        self.restore_button = LinkButton("Restore")
        self.restore_button.setAccessibleName(f"Restore with case {summary.id}")
        self.restore_button.setToolTip(f"Restore a file with case {summary.id}")
        self.restore_button.clicked.connect(lambda: self.restoreRequested.emit(summary.id))

        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(self.files_label)
        texts.addWidget(self.caption_label)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(14)
        row.addWidget(self.code_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(texts, 1)
        row.addWidget(self.restore_button, alignment=Qt.AlignmentFlag.AlignVCenter)


class RecentCases(QWidget):
    """The section "Recent cases": its header with the link to all of them, and the panel of rows.

    It is hidden while it has no rows. ``restoreRequested(code)`` and ``casesRequested`` pass on
    the clicks of the links.
    """

    restoreRequested = Signal(str)
    casesRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[CaseRow] = []
        self.header_label = QLabel("Recent cases")
        self.header_label.setObjectName("sectionTitle")
        font = self.header_label.font()
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        self.header_label.setFont(font)
        self.all_cases_button = LinkButton("All cases")
        self.all_cases_button.clicked.connect(self.casesRequested)
        self.panel = QFrame()
        self.panel.setObjectName("recentPanel")
        self._rows_layout = QVBoxLayout(self.panel)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)

        header = QHBoxLayout()
        header.addWidget(self.header_label)
        header.addStretch(1)
        header.addWidget(self.all_cases_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.panel)
        self.hide()

    def set_cases(self, summaries: list[CaseSummary], now: datetime) -> None:
        """Show ``summaries`` as the rows, or hide the section when there are none."""
        for row in self.rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self.rows = []
        for index, summary in enumerate(summaries):
            row = CaseRow(summary, now, last=index == len(summaries) - 1)
            row.restoreRequested.connect(self.restoreRequested)
            self._rows_layout.addWidget(row)
            self.rows.append(row)
        self.setVisible(bool(self.rows))


class HomeScreen(QWidget):
    """The first screen: the drop card, what the app is doing, and the recent cases.

    ``refresh_recent`` reads the cases of ``ctx.case_store`` again; the window does that when the
    screen is shown. ``restoreRequested(code)`` and ``casesRequested`` are the links of the cases,
    and ``engineStateChanged(state)`` ("loading", "ready" or "problem") tells the sidebar how the
    engine is.
    """

    restoreRequested = Signal(str)
    casesRequested = Signal()
    engineStateChanged = Signal(str)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.drop_zone = DropZone(art="mask", shortcut_hint="or press ⌘O")
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumWidth(240)
        self.progress_bar.setMaximumWidth(360)
        self.step_label = QLabel()
        self.step_label.setObjectName("step")
        self.notice_label = QLabel()
        self.notice_label.setObjectName("notice")
        self.notice_label.setWordWrap(True)
        self.refused_label = QLabel()
        self.refused_label.setObjectName("notice")
        self.refused_label.setWordWrap(True)
        self.refused_label.hide()
        self.recent = RecentCases()
        self.recent.restoreRequested.connect(self.restoreRequested)
        self.recent.casesRequested.connect(self.casesRequested)
        self._notices: list[str] = []

        for label in (self.status_label, self.step_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status = self.drop_zone.status_layout  # in the card, under its caption
        status.addWidget(self.status_label)
        status.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        status.addWidget(self.step_label)

        top = QVBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.drop_zone)
        top.addWidget(self.notice_label)
        top.addWidget(self.refused_label)
        column = QWidget()
        column.setMaximumWidth(COLUMN_WIDTH)
        stack = QVBoxLayout(column)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(32)
        stack.addLayout(top)
        stack.addWidget(self.recent)
        # The column is centred and as wide as it can be, up to its width: a layout that is told to
        # centre a widget would size it by its hint instead.
        centred = QHBoxLayout()
        centred.addStretch(1)
        centred.addWidget(column, 100)
        centred.addStretch(1)
        content = QWidget()
        content.setObjectName("homeContent")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(40, 48, 40, 32)
        outer.addLayout(centred)
        outer.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("homeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.addWidget(scroll)
        self.show_ready()
        self._show_notices()

    # ---- the engine and the analysis --------------------------------------------------------

    def show_loading(self) -> None:
        """The engine is loading: nothing can be dropped yet."""
        self._rest("Loading…", dropping=False)
        self.engineStateChanged.emit("loading")

    def show_ready(self) -> None:
        """Nothing is running: files can be dropped."""
        self._rest("Ready", dropping=True)
        self.engineStateChanged.emit("ready")

    def show_busy(self) -> None:
        """An analysis is running: its progress is shown, and nothing more can be dropped."""
        self.status_label.setText("Analysing…")
        self.status_label.show()
        self.drop_zone.setEnabled(False)
        self.recent.setEnabled(False)  # nothing leads away from the analysis
        self.show_progress(0, "loading")

    def show_engine_problem(self, message: str) -> None:
        """The engine could not be loaded: say so, and keep the drop zone off."""
        self._rest("The detection engine could not be loaded.", dropping=False)
        self.add_notice(message)
        self.engineStateChanged.emit("problem")

    def show_progress(self, percent: int, step: str) -> None:
        """Show how far an analysis has come, and in which step."""
        self.progress_bar.setValue(percent)
        self.step_label.setText(STEP_TEXT.get(step, step))
        self.progress_bar.show()
        self.step_label.show()

    def add_notice(self, text: str) -> None:
        """Add a line to the notices under the card (a problem that does not stop the app)."""
        self._notices.append(text)
        self._show_notices()

    def show_refused(self, text: str) -> None:
        """Say which files were not opened, and why, until the next files are dropped. This is on
        the screen only: a file's name tells who the parties are, so it is never logged.
        """
        self.refused_label.setText(text)
        self.refused_label.setVisible(bool(text))

    def clear_refused(self) -> None:
        self.show_refused("")

    # ---- the cases --------------------------------------------------------------------------

    def refresh_recent(self) -> None:
        """Read the recent cases again. A store that cannot be read (the Keychain refuses, the
        folder is closed to the app) leaves no section: the Cases screen says what is wrong, and
        the window already told at the start.
        """
        try:
            summaries = self.ctx.case_store.list()
        except (MaskError, OSError):
            summaries = []
        self.recent.set_cases(summaries[:RECENT_LIMIT], current_time())

    # ---- the parts --------------------------------------------------------------------------

    def _rest(self, status: str, dropping: bool) -> None:
        self.status_label.setText(status)
        self.status_label.setVisible(status != "Ready")  # nothing to say when all is well
        self.drop_zone.setEnabled(dropping)
        self.recent.setEnabled(True)
        self.progress_bar.hide()
        self.step_label.hide()

    def _show_notices(self) -> None:
        self.notice_label.setText("\n".join(self._notices))
        self.notice_label.setVisible(bool(self._notices))
