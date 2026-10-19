"""The Restore screen: the real values put back into what the AI tool gave back.

There are two things to restore: the Word file the AI tool wrote (dropped on the file card, or
chosen with its button) and the text it wrote in its chat (pasted into the box beside it). Either
is restored with the key of one case, chosen in the case card under them. A placeholder tells
nothing by itself: [PERSON_1] of one case is another person in the next, so a wrong case writes
another contract's values into the file and nothing looks amiss. The screen therefore never
guesses between cases (ruling R103). The cases come best fit first (``suggest_cases``: the code
of a case in the name of the file, then the one that holds most of the placeholders of the file or
the text). If one case fits best it is preselected. If another case holds as many of the
placeholders as the best and the name of the file does not decide, no case is selected, the screen
says "Several cases fit this file — choose one." and nothing can be restored until the owner
chooses (a case holding none of the placeholders is no fit: nothing would be written, and the
newest is selected). A case the owner chose, in the box or by asking for it in the Cases screen, is
never replaced by the screen, whatever fits better: when another case holds more of the
placeholders the screen says "Another case fits this file better — check the case." and leaves the
choice, and Restore, alone. The choice is for the file or text it was made for: it stands while
that is edited and the screen is visited, and ends with a restore, or when another file is dropped
(the case asked for in the Cases screen counts for the next file). A case the screen selected
because its code is in the name of the file says "Chosen from the file name". Under the case the
screen shows the values the selected case would put back for the placeholders it found, three to a
row, so that a wrong case is seen before anything is written, and under each source how many of
its placeholders the chosen case holds.

What the AI changed ("[PERSON 1]" for [PERSON_1]: no brackets, lower case, spaces) is listed in a
notice card (for the file) or in the paste card (for the text) with a check box for each place, and
put back only when the owner confirms it. The plan of the file (``plan_docx``) or of the text
(``plan_restore``) numbers every placeholder, and ``restore_docx`` and ``restore_text`` take the
numbers of the ones the owner confirmed (ruling R91), or True when every one is ticked, which also
puts back the changed placeholders in a text box's backup copy. A line is a plan item as the AI
wrote it, with where it stands; a place that a tracked change of the AI runs through says so, and
says that it stands for every placeholder in that change (ruling R96). What was not confirmed is
left as the AI wrote it and reported as needing a check, as is a place that cannot be put back.
The restore of a file is always given the fingerprint the plan holds (ruling R96); if the file was
saved by another program meanwhile, nothing is restored, the owner is told in the words of the
error, and the list is made again from the file as it is now. So it is for a file that could not
be read when the list was made: with no plan there is no fingerprint to give. The plan of the
pasted text is made again whenever the text changes.

A restored Word file is a new file next to the AI's (``restore_docx`` never writes over a file);
the result card names it and shows its folder in Finder. Restored text is shown, read-only, with a
Copy button: what is copied is on the clipboard in clear, which the About box says. A restore is
fast (20 ms for the largest contract of the corpus), so it runs in the window's own thread.
Whatever goes wrong is said in the screen in plain words, never as a trace.

The window supplies the title and the Restore button of its tool bar: ``title()`` says what to
show (``titleChanged`` when it changes), ``primary()`` is what the Restore button does, and the
button of the screen itself (``restore_button``) goes when ``set_primary_in_toolbar(True)`` says
the tool bar has one (``primaryEnabledChanged`` says whether it may be pressed).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import (
    Qt,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.errors import MaskError
from themask.model import Case
from themask.restore.docx_restore import FILE_CHANGED_MESSAGE, plan_docx, restore_docx
from themask.restore.matcher import case_in_file_name, plan_restore, suggest_cases
from themask.restore.report import TRACKED_CHANGE, RestoreItem, RestoreReport
from themask.restore.text import restore_text
from themask.ui.cards import (
    Box,
    ChevronCombo,
    FlowLayout,
    MarkBadge,
    Themed,
    TickLabel,
    style_vars,
)
from themask.ui.cases_screen import NOT_READ, format_when
from themask.ui.export_dialog import reveal
from themask.ui.restore_parts import (
    CHANGE_ROW,
    CHOOSE_FILE,
    DROP_HINT,
    DROP_TITLE,
    SEPARATOR,
    ChangeDelegate,
    FileCard,
    PreviewGrid,
)
from themask.ui.theme import Tokens, set_status

if TYPE_CHECKING:
    from themask.ui.app import AppContext

_LOG = logging.getLogger(__name__)
_T = TypeVar("_T")

TITLE = ("Restore", "Put the real values back into the file an AI tool returned")
CHOOSE_ANOTHER = "Choose another file\N{HORIZONTAL ELLIPSIS}"
CASE_LABEL = "Case"
PASTE_LABEL = "Or paste the AI\N{RIGHT SINGLE QUOTATION MARK}s answer"
PASTE_HINT = (
    "Paste text with placeholders such as [PERSON_1] here. It is restored on screen; nothing is"
    " written to disk."
)
CHANGED = "These placeholders were changed by the AI — restore them?"
CHOSEN = "Chosen from the file name"
CHOOSE_CASE = "Several cases fit this file — choose one."
BETTER_FIT = "Another case fits this file better — check the case."
CHOOSE_PLACEHOLDER = "Choose a case"
NO_CASES = (
    "There is no saved case to restore with. A case is made each time you export a masked file."
)
ONLY_WORD = "Only a Word (.docx) file can be restored."
ONE_AT_A_TIME = "One file at a time: the first one was taken."
FILE_NOT_READ = "The file could not be read:"
NOT_RESTORED = "The file could not be restored:"
UNEXPECTED = "Something went wrong while restoring."

TRACKED_NOTE = f"{TRACKED_CHANGE}: this stands for every placeholder in that change"
PREVIEW_LINES = 5  # placeholders the preview under the case shows
PREVIEW_LENGTH = 60  # characters of a value it shows
CHANGE_ROWS = 6  # lines a list of changes shows before it scrolls
# On a line of a list of changes: the ordinal of its item in the plan.
ORDINAL_ROLE = Qt.ItemDataRole.UserRole

# A case that holds nothing: what the placeholders of a text are counted with.
_NOBODY = Case("-", datetime(2000, 1, 1, tzinfo=UTC), [], [], [])

_SHEET = Template("""
QFrame[card="true"] {
    background: $panel;
    border: 1px solid $border;
    border-radius: 14px;
}
QFrame#fileCard {
    background: $panel;
    border: 1px solid $border;
    border-radius: 14px;
}
QFrame#fileCard[dragOver="true"] { background: $accent_soft; border-color: $accent; }
QLabel#fileName { font-size: 15px; font-weight: 600; color: $text; }
QLabel#fileCaption { font-size: 12px; color: $secondary; }
QLabel#fitLine { font-size: 12px; color: $text; }
QLabel[role="label"] { font-weight: 600; color: $text; }
QPlainTextEdit#pasteBox, QPlainTextEdit#resultBox {
    background: $ground;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px;
}
QPlainTextEdit#pasteBox:focus, QPlainTextEdit#resultBox:focus { border-color: $accent; }
QComboBox#caseCombo {
    min-height: 28px;
    color: $text;
    background: $control;
    border: 1px solid $border_strong;
    border-radius: 8px;
    padding: 0 8px;
}
QComboBox#caseCombo:focus { border-color: $accent; }
QComboBox#caseCombo::drop-down { border: none; width: 26px; }
QComboBox#caseCombo::down-arrow { image: none; }
QLabel#chosen { font-size: 12px; color: $success_text; }
QLabel#previewToken { font-size: 12px; color: $secondary; }
QLabel#previewValue { font-size: 12px; color: $text; }
QLabel#previewMore { font-size: 12px; color: $secondary; }
QFrame#noticeCard {
    background: $notice_card_bg;
    border: 1px solid $notice_border;
    border-radius: 14px;
}
QFrame#noticeCard[inner="true"] { border-radius: 10px; }
QLabel#noticeTitle { font-weight: 600; color: $notice_text; }
QListWidget#changes { background: $notice_card_bg; border: none; outline: none; }
QLabel#resultLine { font-weight: 600; color: $text; }
QLabel#resultNote { font-size: 12px; color: $secondary; }
QLabel#resultCheck { font-size: 12px; color: $text; }
QPushButton[small="true"] { font-size: 12px; }
""")


def _sheet(t: Tokens) -> str:
    return _SHEET.substitute(style_vars(t))


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def file_text(path: Path) -> str:
    """The text of the Word file at ``path``, every tracked change accepted: what the cases are
    put in order of fit for.

    Raises what ``DocxPackage.open`` raises for a file that is not a Word file or is protected.
    """
    return extract_text(DocxPackage.open(path)).text


def _held(case: Case, text: str) -> int:
    """How many of the placeholders in ``text`` the key of ``case`` holds, each counted once."""
    return len({item.entry.placeholder for item in plan_restore(text, case) if item.entry})


def _placeholders_in(text: str) -> int:
    """How many different placeholders ``text`` holds (The MASK's own lines do not count)."""
    return len({item.match.placeholder for item in plan_restore(text, _NOBODY)})


def _case_title(case: Case) -> str:
    """The line of a case in the case box: its code, the files it was made from (a case that
    stores no file names has none), when it was made and how many values its key holds.
    """
    parts = [case.id]
    if case.source_files:
        parts.append(", ".join(case.source_files))
    parts += [format_when(case.created_at), _count(len(case.entries), "value")]
    return " \N{MIDDLE DOT} ".join(parts)


def _short(value: str) -> str:
    """``value`` on one line, cut short when it is long."""
    line = " ".join(value.split())
    if len(line) <= PREVIEW_LENGTH:
        return line
    return line[: PREVIEW_LENGTH - 1].rstrip() + "…"


def _preview(plans: Iterable[list[RestoreItem]]) -> tuple[list[tuple[str, str]], int]:
    """What the selected case would put back: ``(placeholder, value)`` for each placeholder in
    ``plans`` (the file's, then the text's) that the case holds, each once, in the order they
    stand, up to ``PREVIEW_LINES``; and how many more there are. A changed form counts: the owner
    may confirm it.
    """
    values: dict[str, str] = {}
    for plan in plans:
        for item in plan:
            if item.entry is not None:
                values.setdefault(item.entry.placeholder, item.entry.value)
    shown = [
        (placeholder, _short(value)) for placeholder, value in islice(values.items(), PREVIEW_LINES)
    ]
    return shown, len(values) - len(shown)


def _written(items: list[RestoreItem]) -> str:
    """How the placeholders of ``items`` were written, each form once; a place that a tracked
    change of the AI runs through says so.
    """
    return ", ".join(
        dict.fromkeys(
            f"{item.match.raw} ({TRACKED_NOTE})" if item.reason else item.match.raw
            for item in items
        )
    )


def _where(part: str) -> str:
    """Where in a Word file the part called ``part`` is, in words: nothing for the document
    itself and for a text.
    """
    for marker, words in (
        ("/comments", "in a comment"),
        ("/header", "in a header"),
        ("/footer", "in a footer"),
        ("/footnotes", "in a footnote"),
        ("/endnotes", "in an endnote"),
    ):
        if marker in part:
            return words
    return ""


def _row_text(item: RestoreItem) -> str:
    """The line of a placeholder the AI changed: how it was written, what it stands for, where
    it stands, and for a place that a tracked change runs through what that means.
    """
    placeholder = item.entry.placeholder if item.entry is not None else ""
    where = f", {_where(item.part)}" if _where(item.part) else ""
    note = f"  ({TRACKED_NOTE})" if item.reason else ""
    return f"{item.match.raw}{SEPARATOR}{placeholder}{where}{note}"


def _show_changes(card: QWidget, choices: QListWidget, plan: list[RestoreItem]) -> None:
    """List what the AI changed in ``plan``: an unticked line for each item with a changed form,
    in ``choices``, which ``card`` (the notice it stands in) shows when there is a line.

    Items the key does not hold, or that the AI wrote exactly, need no answer; those that cannot
    be put back are reported after the restore.
    """
    changed = [item for item in plan if item.status == "altered" and item.entry is not None]
    choices.clear()
    for item in changed:
        row = QListWidgetItem(_row_text(item))
        row.setToolTip(row.text())  # the line may be longer than the list is wide
        row.setData(ORDINAL_ROLE, item.ordinal)
        row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        row.setCheckState(Qt.CheckState.Unchecked)
        choices.addItem(row)
    choices.setFixedHeight(min(len(changed), CHANGE_ROWS) * CHANGE_ROW + 2)
    card.setVisible(bool(changed))


def _confirmation(choices: QListWidget) -> bool | set[int]:
    """What the owner confirmed: True when every line is ticked (a restore then also puts back
    the changed placeholders of a text box's backup copy), else the ordinals of the ticked lines.
    """
    rows = [row for row in (choices.item(n) for n in range(choices.count())) if row is not None]
    ticked = [row for row in rows if row.checkState() == Qt.CheckState.Checked]
    if rows and len(ticked) == len(rows):
        return True
    return {int(row.data(ORDINAL_ROLE)) for row in ticked}


def _counts(plan: list[RestoreItem]) -> tuple[int, int]:
    """How many of the placeholders found in ``plan`` the case holds, and how many there are."""
    total = len({item.match.placeholder for item in plan})
    held = len({item.entry.placeholder for item in plan if item.entry is not None})
    return held, total


def _fit(plan: list[RestoreItem]) -> str:
    """How well the case fits the text that ``plan`` was made for, in a sentence."""
    held, total = _counts(plan)
    if not total:
        return "No placeholders found."
    return f"{held} of {_count(total, 'placeholder')} found in this case."


class RestoreScreen(QWidget):
    """Restore a Word file or pasted text with the key of a saved case.

    ``drop_zone`` is the file card and ``paste_box`` the box beside it; ``case_combo`` holds the
    cases, best fit first, with the case's id as the data of each line; no line is selected
    (index -1) while ``choose_label`` asks the owner to choose, ``chosen_label`` says the case
    was taken from the name of the file, ``better_fit_label`` says that another case fits better
    than the selected one (which stays), and ``preview_grid`` shows the values the selected case
    would put back. ``load_file`` takes the AI's Word file. ``altered_list`` (for the file) and
    ``text_altered_list`` (for the text) list what the AI changed, with a check box for each.
    ``restore_button`` restores the file, ``restore_text_button`` the text. The result is in
    ``result_panel``: ``report_label`` (the report's one line), what was saved, what needs a check
    and what the case does not hold; restored text is in ``result_box``. ``restoreFinished`` is
    sent when a Word restore has ended, with a result or with a message.
    """

    restoreFinished = Signal()
    titleChanged = Signal(str, str)  # the title and the caption, when they change
    primaryEnabledChanged = Signal(bool)  # whether Restore may be pressed, when that changes

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._cases: dict[str, Case] = {}
        self._file: Path | None = None
        self._file_plan: list[RestoreItem] = []
        self._file_sha256: str | None = None  # the fingerprint of the file the plan was made from
        self._file_text = ""  # what the file says: what the cases are put in order for
        self._file_total = 0  # how many different placeholders it holds
        self._text_plan: list[RestoreItem] = []
        self._ranked_on = ""  # the text the cases were last put in order for
        self._ranked_name: str | None = None  # and the name of its file; None for pasted text
        self._manual = False  # the owner chose the case that is selected, for what is on screen
        self._for_next_file = False  # ... or asked for it in the Cases screen, for the next file
        self._unclear = False  # several cases fit alike, so none was selected for the owner
        self._fits: dict[str, int] = {}  # placeholders each case holds of the text ranked on
        self._folder: Path | None = None  # where the restored file was written
        self._primary_enabled = False

        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self._build_sources()
        self._build_case()
        self.altered_card, self.altered_label, self.altered_list = self._changes_card(inner=False)
        self._build_result()

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(32, 28, 32, 28)
        column.setSpacing(20)
        column.addWidget(self.status_label)
        column.addWidget(self._sources)
        column.addWidget(self._case_card)
        column.addWidget(self.altered_card)
        column.addWidget(self.result_panel)
        column.addStretch(1)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll_area)
        Themed(self, _sheet)
        self.refresh_cases()

    # ---- the interface the rest of the app uses --------------------------------------------

    def title(self) -> tuple[str, str]:
        """What the window shows above the screen: its title and the caption under it."""
        return TITLE

    @Slot()
    def primary(self) -> None:
        """What the Restore button of the window does: restore the Word file, if there is one to
        restore with the selected case.
        """
        self._restore_file()

    def primary_enabled(self) -> bool:
        """Whether there is a file to restore with the selected case."""
        return self._primary_enabled

    def set_primary_in_toolbar(self, in_toolbar: bool) -> None:
        """Say that the window has a Restore button of its own (``primary``): the screen's own
        goes. Without one the screen's button is shown, so that a file can always be restored.
        """
        self.restore_button.setVisible(not in_toolbar)

    def load_file(self, path: Path) -> None:
        """Take the AI's Word file at ``path``: read the placeholders in it, preselect the case that
        fits best (the one whose code is in the file's name, else the one that holds most of its
        placeholders) or ask the owner to choose between cases that fit alike, and list what the
        AI changed. A file that cannot be read is said in words.
        """
        text = self._guarded(lambda: file_text(path), FILE_NOT_READ)
        if text is None:
            return
        if self._file is not None and not self._for_next_file:
            self._manual = False  # what the owner chose was for the file before this one
        self._for_next_file = False
        self._file, self._file_text = path, text
        self._file_total = _placeholders_in(text)
        self._ranked_on, self._ranked_name = text, path.name
        if self._order_cases(self._selected_id() if self._manual else None):
            self._replan_text()  # another case: the pasted text reads differently too
        self._replan_file()
        self._clear_result()

    def refresh_cases(self, select: str | None = None) -> None:
        """Load the saved cases again and put them in order for what is on the screen.

        When no case has changed, what is on the screen stands: a visit changes nothing. A case
        the owner chose stays selected, however it fits what is on the screen. ``select`` is the
        case the owner asked for in the Cases screen; when it is there it counts as chosen, for
        the next file even if one is loaded already.
        """
        unreadable = True
        try:
            cases = self.ctx.case_store.load_all()
        except MaskError as error:
            self._cases = {}
            self._status(error.user_message, problem=True)
        except OSError as error:
            self._cases = {}
            self._status(f"{NOT_READ} {error.strerror or error}", problem=True)
        else:
            unreadable = False
            loaded = {case.id: case for case in cases}
            self._status("")
            if select is None and loaded and loaded == self._cases:
                return  # the same cases as before: nothing to put in order again
            self._cases = loaded
        wanted = (
            select if select in self._cases else (self._selected_id() if self._manual else None)
        )
        if wanted is not None and wanted == select:
            self._for_next_file = True
        self._order_cases(wanted)
        if unreadable:
            self.no_cases_label.hide()  # not that there are none: they cannot be read
        self._case_changed()  # the cases may have changed under the same id

    # ---- building the screen ---------------------------------------------------------------

    def _build_sources(self) -> None:
        """The file card and the paste card, side by side (one under the other when narrow)."""
        self.drop_zone = FileCard()
        self.drop_zone.setAccessibleName("The AI\N{RIGHT SINGLE QUOTATION MARK}s Word file")
        self.drop_zone.filesDropped.connect(self._files_dropped)
        self.drop_zone.filesRefused.connect(self._files_refused)
        self.file_label = (
            self.drop_zone.title_label
        )  # the file's name, or the invitation to drop it
        self.file_fit_label = QLabel()
        self.file_fit_label.setObjectName("fitLine")
        self.file_fit_label.setWordWrap(True)
        self.file_fit_label.hide()
        self.drop_zone.add_line(self.file_fit_label)

        self.paste_label = QLabel(PASTE_LABEL)
        self.paste_label.setProperty("role", "label")
        self.paste_box = Box(110)
        self.paste_box.setObjectName("pasteBox")
        self.paste_box.setPlaceholderText(PASTE_HINT)
        self.paste_box.textChanged.connect(self._text_changed)
        self.paste_label.setBuddy(self.paste_box)
        self.text_altered_card, self.text_altered_label, self.text_altered_list = (
            self._changes_card(inner=True)
        )
        self.text_fit_label = QLabel()
        self.text_fit_label.setObjectName("fitLine")
        self.text_fit_label.setWordWrap(True)
        self.text_fit_label.hide()
        self.restore_text_button = QPushButton("Restore text")
        self.restore_text_button.setProperty("small", True)
        self.restore_text_button.clicked.connect(self._restore_text)
        paste_card = QFrame()
        paste_card.setProperty("card", True)
        paste = QVBoxLayout(paste_card)
        paste.setContentsMargins(18, 16, 18, 16)
        paste.setSpacing(8)
        paste.addWidget(self.paste_label)
        paste.addWidget(self.paste_box, 1)
        paste.addWidget(self.text_altered_card)
        paste.addWidget(self.text_fit_label)
        paste_row = QHBoxLayout()
        paste_row.addStretch(1)
        paste_row.addWidget(self.restore_text_button)
        paste.addLayout(paste_row)

        self._sources = QWidget()
        flow = FlowLayout(self._sources, min_width=300, spacing=16)
        flow.addWidget(self.drop_zone)
        flow.addWidget(paste_card)

    def _build_case(self) -> None:
        """The case card: the case box with what the screen says of the choice, the button that
        restores the file, and the values the case would put back.
        """
        case_label = QLabel(CASE_LABEL)
        case_label.setProperty("role", "label")
        self.case_combo = ChevronCombo()
        self.case_combo.setObjectName("caseCombo")
        self.case_combo.setMinimumWidth(360)
        self.case_combo.setSizeAdjustPolicy(
            ChevronCombo.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.case_combo.setMinimumContentsLength(44)
        self.case_combo.activated.connect(self._owner_chose_case)
        self.case_combo.currentIndexChanged.connect(self._case_changed)
        case_label.setBuddy(self.case_combo)
        self.chosen_label = TickLabel(CHOSEN)
        self.chosen_label.setObjectName("chosen")
        self.chosen_label.hide()
        self.restore_button = QPushButton("Restore")
        self.restore_button.setObjectName("primary")
        self.restore_button.clicked.connect(self._restore_file)
        self.choose_label = QLabel(CHOOSE_CASE)
        self.choose_label.setObjectName("notice")
        self.choose_label.setWordWrap(True)
        self.choose_label.hide()
        self.better_fit_label = QLabel(BETTER_FIT)
        self.better_fit_label.setObjectName("notice")
        self.better_fit_label.setWordWrap(True)
        self.better_fit_label.hide()
        self.no_cases_label = QLabel(NO_CASES)
        self.no_cases_label.setObjectName("notice")
        self.no_cases_label.setWordWrap(True)
        self.preview_grid = PreviewGrid()
        self.preview_grid.setAccessibleName("The values the case would put back")
        self.preview_grid.hide()

        self._case_card = QFrame()
        self._case_card.setProperty("card", True)
        card = QVBoxLayout(self._case_card)
        card.setContentsMargins(18, 16, 18, 16)
        card.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(case_label)
        row.addWidget(self.case_combo)
        row.addWidget(self.chosen_label)
        row.addStretch(1)
        row.addWidget(self.restore_button)
        card.addLayout(row)
        for part in (
            self.choose_label,
            self.better_fit_label,
            self.no_cases_label,
            self.preview_grid,
        ):
            card.addWidget(part)

    def _build_result(self) -> None:
        """The result card: the report with what was saved, what needs a check and what the case
        does not hold, and the button for the folder or for the text; restored text is in the
        box under them.
        """
        self.report_label = QLabel()
        self.report_label.setObjectName("resultLine")
        self.report_label.setWordWrap(True)
        self.saved_label = self._note("resultNote")
        self.check_label = self._note("resultCheck")
        self.unknown_label = self._note("resultNote")
        self.finder_button = QPushButton("Show in Finder")
        self.finder_button.setProperty("small", True)
        self.finder_button.clicked.connect(self._show_in_finder)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setProperty("small", True)
        self.copy_button.setToolTip("Put the restored text on the clipboard (in clear).")
        self.copy_button.clicked.connect(self._copy)
        self.result_box = Box(140)
        self.result_box.setObjectName("resultBox")
        self.result_box.setReadOnly(True)
        self.result_box.setAccessibleName("The restored text")
        self.result_panel = QFrame()
        self.result_panel.setProperty("card", True)
        panel = QVBoxLayout(self.result_panel)
        panel.setContentsMargins(18, 14, 18, 14)
        panel.setSpacing(12)
        words = QVBoxLayout()
        words.setSpacing(2)
        for label in (self.report_label, self.saved_label, self.check_label, self.unknown_label):
            words.addWidget(label)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(MarkBadge("check", 36), 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(words, 1)
        top.addWidget(self.finder_button, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignVCenter)
        panel.addLayout(top)
        panel.addWidget(self.result_box)
        self.result_panel.hide()

    @staticmethod
    def _note(name: str) -> QLabel:
        label = QLabel()
        label.setObjectName(name)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)  # it names placeholders and files
        return label

    @staticmethod
    def _changes_card(inner: bool) -> tuple[QFrame, QLabel, QListWidget]:
        """A notice with the title ``CHANGED`` over a list of what the AI changed. ``inner`` is
        the one in the paste card (a smaller notice); the other stands alone.
        """
        card = QFrame()
        card.setObjectName("noticeCard")
        card.setProperty("inner", inner)
        title = QLabel(CHANGED)
        title.setObjectName("noticeTitle")
        title.setWordWrap(True)
        choices = QListWidget()
        choices.setObjectName("changes")
        choices.setItemDelegate(ChangeDelegate(choices))
        choices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        choices.setTextElideMode(Qt.TextElideMode.ElideRight)
        choices.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        choices.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        choices.setAccessibleName(CHANGED)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(*((14, 12, 14, 8) if inner else (18, 14, 18, 10)))
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(choices)
        card.hide()
        return card, title, choices

    def _status(self, text: str, problem: bool = False) -> None:
        """Say ``text`` in the status line at the top (and show the top, where it is)."""
        set_status(self.status_label, text, problem)
        if text:
            self.scroll_area.verticalScrollBar().setValue(0)

    # ---- the cases -------------------------------------------------------------------------

    def _selected_id(self) -> str | None:
        data = self.case_combo.currentData()
        return None if data is None else str(data)

    def _selected_case(self) -> Case | None:
        return self._cases.get(self._selected_id() or "")

    def _owner_chose_case(self, index: int) -> None:
        self._manual = True
        self._for_next_file = False  # chosen for what is on the screen now
        self._update_state()  # the box says "activated" after it said "changed": what is said of
        # the choice (that the screen made it, that it fits best) was said for a choice of its own

    def _order_cases(self, chosen: str | None) -> bool:
        """Put the cases in order of fit for the text (and the file name) they were last asked
        about, and select one. ``chosen``, the case the owner picked by hand or came for from the
        Cases screen, is always the one: the screen never replaces it, whatever fits better (the
        hint under the case box says when another case does). Without one the best fit is
        selected, but when another case fits as well and the name of the file does not decide,
        none is selected and the owner is asked to choose (ruling R103). Returns whether that is
        another case than the one that was selected.
        """
        before = self._selected_id()
        self._fits = {}  # the text or the cases are new: nothing is known of how they fit
        ranked = suggest_cases(self._ranked_on, list(self._cases.values()), self._ranked_name)
        best = ranked[0] if ranked else None
        keep = chosen if chosen in self._cases else None
        self._manual = keep is not None
        self._unclear = keep is None and self._is_a_guess(ranked)
        if keep is not None:
            target = keep
        elif best is not None and not self._unclear:
            target = best.id
        else:
            target = None
        self.case_combo.blockSignals(True)
        self.case_combo.clear()
        for case in ranked:
            title = _case_title(case)
            self.case_combo.addItem(title, case.id)
            self.case_combo.setItemData(
                self.case_combo.count() - 1, title, Qt.ItemDataRole.ToolTipRole
            )
        self.case_combo.setCurrentIndex(-1 if target is None else self.case_combo.findData(target))
        self.case_combo.blockSignals(False)
        self.no_cases_label.setVisible(not ranked)
        return self._selected_id() != before

    def _fit_of(self, case: Case) -> int:
        """How many of the placeholders in the text the cases were last put in order for ``case``
        holds. Each case is looked at once for each ranking: the text may be long.
        """
        if case.id not in self._fits:
            self._fits[case.id] = _held(case, self._ranked_on)
        return self._fits[case.id]

    def _is_a_guess(self, ranked: list[Case]) -> bool:
        """Whether choosing the first of ``ranked``, the best fit, would be a guess: another case
        holds as many of the placeholders, and the name of the file does not point to the first.
        Cases that hold none of the placeholders are no fit, so nothing is a guess then.
        """
        name = self._ranked_name
        if len(ranked) < 2 or (name and case_in_file_name(name, ranked)):
            return False
        best = self._fit_of(ranked[0])
        return best > 0 and self._fit_of(ranked[1]) == best

    def _another_fits_better(self, chosen: Case) -> bool:
        """Whether another case holds more of the placeholders in the text the cases were last put
        in order for than ``chosen`` does.
        """
        held = self._fit_of(chosen)
        return any(
            self._fit_of(other) > held for other in self._cases.values() if other.id != chosen.id
        )

    def _show_choice_notice(self) -> None:
        """Ask the owner to choose while several cases fit alike and none is selected."""
        asking = self._unclear and self._selected_id() is None
        self.choose_label.setVisible(asking)
        self.case_combo.setPlaceholderText(CHOOSE_PLACEHOLDER if asking else "")

    def _case_changed(self) -> None:
        """The case has changed: look at both sources again, for that case."""
        self._replan_file()
        self._replan_text()

    def _replan_file(self) -> None:
        """Plan the Word file again, for the selected case, and list what the AI changed in it.
        The ticks of the list are lost: they were for another plan.
        """
        case = self._selected_case()
        self._file_plan = self._plan_file(case) if case else []
        _show_changes(self.altered_card, self.altered_list, self._file_plan)
        self.file_fit_label.setText(_fit(self._file_plan) if case and self._file else "")
        held, total = _counts(self._file_plan)
        # The card already says how many placeholders there are: this says more only when the case
        # lacks some of them.
        self.file_fit_label.setVisible(case is not None and self._file is not None and held < total)
        self._update_state()

    def _replan_text(self) -> None:
        """The same for the pasted text."""
        case, text = self._selected_case(), self.paste_box.toPlainText()
        self._text_plan = plan_restore(text, case) if case and text else []
        _show_changes(self.text_altered_card, self.text_altered_list, self._text_plan)
        self.text_fit_label.setText(_fit(self._text_plan) if case and text else "")
        self.text_fit_label.setVisible(case is not None and bool(text))
        self._update_state()

    def _update_state(self) -> None:
        """Show what the selected case would put back, and offer to restore what there is to
        restore with it (nothing is offered while no case is selected). Another case that fits
        better is pointed out, never put in the place of the selected one.
        """
        case = self._selected_case()
        self._show_choice_notice()
        self.better_fit_label.setVisible(case is not None and self._another_fits_better(case))
        self._show_chosen(case)
        shown, more = _preview([self._file_plan, self._text_plan]) if case else ([], 0)
        self.preview_grid.show_lines(shown, more)
        self.preview_grid.setVisible(bool(shown))
        self._show_file(case)
        can_restore = case is not None and self._file is not None
        self.restore_button.setEnabled(can_restore)
        self.restore_text_button.setEnabled(
            case is not None and bool(self.paste_box.toPlainText().strip())
        )
        if can_restore != self._primary_enabled:
            self._primary_enabled = can_restore
            self.primaryEnabledChanged.emit(can_restore)

    def _show_chosen(self, case: Case | None) -> None:
        """Say "Chosen from the file name" when the screen took the case because its code stands
        in the name of the file.
        """
        named = (
            case_in_file_name(self._ranked_name, list(self._cases.values()))
            if self._ranked_name
            else None
        )
        self.chosen_label.setVisible(
            case is not None and not self._manual and named is not None and named.id == case.id
        )

    def _show_file(self, case: Case | None) -> None:
        """The file card: the name of the file and what is known of it, or the invitation to drop
        one while there is none.
        """
        zone = self.drop_zone
        if self._file is None:
            zone.title_label.setText(DROP_TITLE)
            zone.title_label.setToolTip("")
            zone.hint_label.setText(DROP_HINT)
            zone.choose_button.setText(CHOOSE_FILE)
            return
        zone.title_label.setText(self._file.name)
        zone.title_label.setToolTip(self._file.name)
        zone.hint_label.setText(self._file_caption(case))
        zone.choose_button.setText(CHOOSE_ANOTHER)

    def _file_caption(self, case: Case | None) -> str:
        """The line under the file's name: that it was just dropped, how many placeholders it
        holds, and which case fits it best when the screen chose the case for the file.
        """
        total = self._file_total
        parts = [
            "Dropped just now",
            f"{_count(total, 'placeholder')} found" if total else "No placeholders found",
        ]
        held, _ = _counts(self._file_plan)
        if case is not None and not self._manual and self._ranked_name is not None and held:
            parts.append(f"case {case.id} fits best")
        return " \N{MIDDLE DOT} ".join(parts)

    def _plan_file(self, case: Case) -> list[RestoreItem]:
        """The plan of the Word file for ``case``: empty when there is no file, or when the file
        cannot be read now (which is said in the status line).
        """
        path = self._file
        self._file_sha256 = None
        if path is None:
            return []
        plan = self._guarded(lambda: plan_docx(path, case), FILE_NOT_READ, clear=False)
        if plan is None:
            return []
        self._file_sha256 = plan.sha256
        return plan.items

    def _text_changed(self) -> None:
        text = self.paste_box.toPlainText()
        if text.strip():
            self._ranked_on, self._ranked_name = text, None  # pasted text has no file name
        elif self._file is not None:
            self._ranked_on, self._ranked_name = self._file_text, self._file.name  # the file again
        else:
            self._ranked_on, self._ranked_name = "", None  # nothing to fit: as at the start
        if self._order_cases(self._selected_id() if self._manual else None):
            self._replan_file()  # another case: the file reads differently too
        self._replan_text()  # the file's ticks stay: typing here does not change its plan

    # ---- the files -------------------------------------------------------------------------

    def _files_dropped(self, paths: list[Path]) -> None:
        self.load_file(paths[0])
        if len(paths) > 1 and self.status_label.isHidden():  # unless the first one failed to load
            self._status(ONE_AT_A_TIME)

    def _files_refused(self, paths: list[Path]) -> None:
        names = ", ".join(path.name for path in paths)
        self._status(f"{ONLY_WORD} Not opened: {names}.", problem=True)

    # ---- restoring -------------------------------------------------------------------------

    def _restore_file(self) -> None:
        case, path = self._selected_case(), self._file
        if case is None or path is None:
            return
        self._restore_file_with(case, path)
        self.restoreFinished.emit()

    def _restore_file_with(self, case: Case, path: Path) -> None:
        """Restore the Word file with the placeholders the owner confirmed, if it is still the
        file the list was made from; else say so and show the list again, made from the file as
        it is now.
        """
        sha256 = self._file_sha256
        if sha256 is None:
            # No plan was made for this case (the file could not be read then). A restore is
            # always given the fingerprint of the plan it follows (ruling R96), so the file is
            # looked at again, and the owner sees the list before it is restored.
            self._replan_file()
            if self._file_sha256 is not None:
                self._status(FILE_CHANGED_MESSAGE, problem=True)
            return
        confirmed = _confirmation(self.altered_list)

        def restore() -> tuple[Path, RestoreReport]:
            try:
                return restore_docx(path, case, confirmed, expected_sha256=sha256)
            except MaskError as error:
                if error.user_message == FILE_CHANGED_MESSAGE:
                    self._replan_file()  # the message is said by the caller, after this
                raise

        done = self._guarded(restore, NOT_RESTORED)
        if done is not None:
            target, report = done
            self._show_result(report, target, None)
            self._spend_choice()

    def _restore_text(self) -> None:
        case, text = self._selected_case(), self.paste_box.toPlainText()
        if case is None or not text.strip():
            return
        confirmed = _confirmation(self.text_altered_list)
        done = self._guarded(lambda: restore_text(text, case, confirmed), UNEXPECTED)
        if done is not None:
            restored, report = done
            self._show_result(report, None, restored)
            self._spend_choice()

    def _spend_choice(self) -> None:
        """The case the owner chose was for what has just been restored: the next file or text is
        a new decision (ruling R103). The case stays selected, so the same file or text can be
        restored again.
        """
        self._manual = self._for_next_file = False

    def _guarded(self, work: Callable[[], _T], disk_message: str, clear: bool = True) -> _T | None:
        """The result of ``work``, or None after saying in the status line why there is none:
        what a ``MaskError`` says, what the system says of a file that cannot be read or written,
        and a plain sentence for anything else (only the kind of error is logged, as its text
        may quote the document). A result clears the status line, unless ``clear`` is off.
        """
        try:
            result = work()
        except MaskError as error:
            self._status(error.user_message, problem=True)
        except OSError as error:
            self._status(f"{disk_message} {error.strerror or error}", problem=True)
        except Exception as error:  # noqa: BLE001 - the owner is told, the app goes on
            _LOG.error("restore failed error=%s", type(error).__name__)
            self._status(UNEXPECTED, problem=True)
        else:
            if clear:
                self._status("")
            return result
        return None

    # ---- the result ------------------------------------------------------------------------

    def _show_result(self, report: RestoreReport, saved: Path | None, text: str | None) -> None:
        """Show the report; a Word restore also names the file it wrote, and a text restore shows
        the text.
        """
        self.report_label.setText(report.summary())
        self.saved_label.setText(
            f"Saved as \N{LEFT DOUBLE QUOTATION MARK}{saved.name}\N{RIGHT DOUBLE QUOTATION MARK}"
            " next to the AI\N{RIGHT SINGLE QUOTATION MARK}s file."
            if saved
            else ""
        )
        self.saved_label.setVisible(saved is not None)
        check = _written(report.needs_check)
        self.check_label.setText(f"Left as the AI wrote them, check them: {check}" if check else "")
        self.check_label.setVisible(bool(check))
        unknown = ", ".join(report.unknown)
        self.unknown_label.setText(f"Unknown: {unknown}." if unknown else "")
        self.unknown_label.setVisible(bool(unknown))
        self._folder = saved.parent if saved is not None else None
        self.finder_button.setVisible(saved is not None)
        self.copy_button.setVisible(text is not None)
        self.result_box.setVisible(text is not None)
        self.result_box.setPlainText(text or "")
        self.result_panel.show()

    def _clear_result(self) -> None:
        self.result_panel.hide()
        self.result_box.clear()
        self._folder = None

    def _show_in_finder(self) -> None:
        if self._folder is not None:
            reveal(self._folder)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.result_box.toPlainText())
