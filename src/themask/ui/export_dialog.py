"""The export sheet: the files are masked and checked in a thread of their own, and the owner is
told what was saved, or why nothing was.

``ExportDialog.run`` hands ``export_case`` to an ``ExportWorker``, so that the window stays alive
while the files are made. The dialog cannot be closed before the worker is done: a thread cannot
be interrupted, and the files it writes must not be left half done. At the end it shows one of
three things:

- *saved*: a green check, the files (their folder, the case that holds their key and for how
  long), the instruction for the AI tool with a button that copies it, and under "Details" what
  the detection still finds in the masked copy that the owner never marked, the places the owner
  left visible on purpose and the values too short to be checked; "Show in Finder" shows the
  folder, "Back to review" and "Done" close the sheet;
- *blocked*: a value the owner marked is still in a file. The places are named in a red-tinted
  sheet and only the way back to the review is offered; nothing is saved;
- *failed*: the export could not be made, in plain words; nothing is saved either.

On the Mac the dialog is a sheet that slides down from the title bar of the window it belongs to
(``Qt.Sheet``, window modal); elsewhere it is a modal dialog in the middle of its window. It is
560 points wide in every state. What the sheet looks like is in its style sheet, ``_sheet``.

What the worker tells the owner is plain English. What it writes to the log is the kind of an
unexpected error and nothing else, as the rule in logging_setup.py says: the text of an error may
quote a file name, and a file name tells who the parties are.

``ExportWorker.finished`` takes the place of QThread's own signal of that name, which has no
payload, as ``AnalysisWorker.finished`` does (see workers.py).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSize,
    Qt,
    QThread,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from themask.errors import MaskError
from themask.export import ExportOptions, ExportResult, export_case
from themask.instruction import AI_INSTRUCTION
from themask.leakcheck import LeakHit
from themask.ui.cards import DocGlyph, MarkBadge, Themed, folder_trail, style_vars, tokens_for
from themask.ui.theme import Tokens
from themask.ui.widgets import ElidedLines

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.export import SourceDoc
    from themask.model import Case
    from themask.review import ReviewState
    from themask.ui.app import AppContext

_LOG = logging.getLogger(__name__)

WIDTH = 560  # points: the width of the sheet in every state
WORKING = "Masking…"
WORKING_HINT = (
    "The files are masked first and then checked for every value you marked. Nothing is saved"
    " unless the check passes."
)
SAVED_ONE = "Masked copy saved"
SAVED_MANY = "Masked copies saved"
SAVED_CAPTION = (
    "Every marked value was replaced and checked twice. Nothing of the original left this Mac."
)
NEXT_STEP = "Next: upload the masked copy with this instruction"
BLOCKED = "Saving blocked: a marked value is still present"
FAILED = "The masked files could not be saved"
NOTHING_SAVED = "Nothing was saved."
BLOCKED_ADVICE = (
    f"{NOTHING_SAVED} A value you marked still shows in the places below. Go back to the review,"
    " or take the value out of the file in Word and open the file again."
)
UNMARKED = "Also found in the masked copy — not marked by you:"
LEFT_VISIBLE = "Left visible on purpose:"
SHOWN_ON_PURPOSE = "Groups you chose to show (switched off or answered Show):"
STILL_ASKED = "Under \u201cNot sure \u2014 hide?\u201d and never answered, so they stay visible:"
NOT_CHECKABLE = "Not checkable (too short):"
NOTHING_TO_REPORT = "Nothing to report."
UNEXPECTED_MESSAGE = "Something went wrong while saving the masked files."
DISK_MESSAGE = "The masked files could not be written:"
NO_ENGINE_MESSAGE = "The detection engine is not loaded, so the files cannot be checked."
ALREADY_RUNNING = "An export is already running in this dialog."

HITS_SHOWN = 5  # places the list of a block shows before it scrolls
HIT_ROW = 46  # points: the height of a place in that list: the part, and what is round the hit
DETAILS_LINE = 18  # points a line of the details takes
DETAILS_LINES = 8  # lines the details show before they scroll

_SHEET = Template("""
QFrame#sheet { background: $panel; }
QFrame#header[tone="danger"] {
    background: $danger_bg;
    border: 1px solid $danger_border;
    border-radius: 12px;
}
QLabel#headline { font-size: 17px; font-weight: 600; color: $text; }
QFrame#header[tone="danger"] QLabel#headline { color: $danger; }
QLabel#caption { color: $secondary; }
QFrame#fileCard {
    background: $ground;
    border: 1px solid $border;
    border-radius: 10px;
}
QLabel#fileName { font-weight: 600; color: $text; }
QLabel#fileCaption { font-size: 12px; color: $secondary; }
QFrame#instructionBox { background: $accent_soft; border: none; border-radius: 10px; }
QLabel#instructionTitle { font-weight: 600; color: $accent_text_on_soft; }
QLabel#instructionText { font-size: 12px; color: $notice_text; }
QToolButton#detailsButton {
    background: transparent;
    border: none;
    padding: 2px 0;
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QPlainTextEdit#details {
    background: $ground;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 12px;
    color: $secondary;
}
QListWidget#hits { background: $ground; border: 1px solid $border; border-radius: 10px; }
QPushButton[small="true"] { font-size: 12px; }
QPushButton[large="true"] { min-height: 28px; padding: 0 16px; border-radius: 8px; }
""")


def _sheet(t: Tokens) -> str:
    return _SHEET.substitute(style_vars(t))


def _is_mac() -> bool:
    """Whether the dialog is a sheet. Tests replace this."""
    return sys.platform == "darwin"


def reveal(folder: Path) -> None:
    """Show ``folder`` in Finder. Tests replace this function: they must not open a window."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


class ExportWorker(QThread):
    """Masks, checks and saves the files in a thread of its own.

    ``finished(result)`` carries the ``ExportResult`` (a blocked export is a result, not a
    failure); or ``failed(message)`` says in plain words why there is none. Nothing here touches
    the screen: the signals reach the thread of the dialog.
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        sources: list[SourceDoc],
        review: ReviewState,
        options: ExportOptions,
        engine: Engine,
        user_lists: UserLists,
        save_case: Callable[[Case], object],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._sources = sources
        self._review = review
        self._options = options
        self._engine = engine
        self._user_lists = user_lists
        self._save_case = save_case

    def run(self) -> None:
        try:
            result = export_case(
                self._sources,
                self._review,
                self._options,
                self._engine,
                self._user_lists,
                self._save_case,
            )
        except MaskError as error:  # the Keychain among them
            self.failed.emit(error.user_message)
        except OSError as error:
            # strerror is what the system says ("No space left on device"), without the name.
            self.failed.emit(f"{DISK_MESSAGE} {error.strerror or error}")
        except Exception as error:  # noqa: BLE001 - a thread must not end by an unseen error
            _LOG.error("export failed error=%s", type(error).__name__)
            self.failed.emit(UNEXPECTED_MESSAGE)
        else:
            self.finished.emit(result)


class _HitDelegate(QStyledItemDelegate):
    """Draws a place of a block in two lines: the part of the file (and how many places read
    the same), and the words round the hit.
    """

    PART_ROLE = Qt.ItemDataRole.UserRole
    CONTEXT_ROLE = Qt.ItemDataRole.UserRole + 1
    PLACES_ROLE = Qt.ItemDataRole.UserRole + 2

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(0, HIT_ROW)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        t = tokens_for(option.widget)
        rect = option.rect.adjusted(12, 0, -12, 0)
        painter.save()
        painter.setPen(QColor(t.border))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        font = QFont(option.font)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(t.text))
        places = str(index.data(self.PLACES_ROLE) or "")
        top = rect.adjusted(0, 7, 0, 0)
        top.setHeight(16)
        if places:
            painter.setPen(QColor(t.secondary))
            painter.drawText(
                top, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, places
            )
            top.setRight(top.right() - painter.fontMetrics().horizontalAdvance(places) - 12)
            painter.setPen(QColor(t.text))
        part = str(index.data(self.PART_ROLE) or "")
        painter.drawText(
            top,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(part, Qt.TextElideMode.ElideMiddle, top.width()),
        )
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(t.secondary))
        bottom = rect.adjusted(0, 25, 0, 0)
        bottom.setHeight(16)
        context = str(index.data(self.CONTEXT_ROLE) or "")
        painter.drawText(
            bottom,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(context, Qt.TextElideMode.ElideRight, bottom.width()),
        )
        painter.restore()


class ExportDialog(QDialog):
    """Makes the masked files and shows what came of it. ``run`` starts it, once.

    ``finishedExport`` is sent when the outcome is on the screen, whatever it is, so that a caller
    never waits for nothing. ``result`` is the ``ExportResult`` (None while the files are made and
    after a failure), ``summary_text()`` the words of the outcome in plain text, ``copy_button``
    puts the instruction for the AI tool on the clipboard and is off unless the files are saved.
    ``close_button`` ("Done") and ``back_button`` ("Back to review") close the sheet;
    ``finder_button`` shows the folder; ``details_button`` opens and closes ``details``, the lists
    of what was found beyond the marks.
    """

    finishedExport = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        if _is_mac():
            super().__init__(parent, Qt.WindowType.Sheet)  # a sheet of the window it belongs to
            self.setWindowModality(Qt.WindowModality.WindowModal)
        else:
            super().__init__(parent)
            self.setModal(True)
        self.setAccessibleName("Export")
        self.setFixedWidth(WIDTH)
        self._outcome: ExportResult | None = None
        self._worker: ExportWorker | None = None
        self._folder: Path | None = None
        self._summary = ""
        self._build()
        Themed(self, _sheet)
        self._show_working()

    # ---- building the sheet ----------------------------------------------------------------

    def _build(self) -> None:
        self.header = QFrame()
        self.header.setObjectName("header")
        self.header.setProperty("tone", "plain")
        self.badge = MarkBadge("check")
        self.headline_label = QLabel()
        self.headline_label.setObjectName("headline")
        self.headline_label.setWordWrap(True)
        self.caption_label = QLabel()
        self.caption_label.setObjectName("caption")
        self.caption_label.setWordWrap(True)
        self.caption_label.setTextFormat(Qt.TextFormat.PlainText)  # it may carry a message
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addWidget(self.headline_label)
        words.addWidget(self.caption_label)
        words.addStretch(1)
        self._header_row = QHBoxLayout(self.header)
        self._header_row.setSpacing(16)
        self._header_row.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        self._header_row.addLayout(words, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # busy: the export cannot say how far it has come
        self.progress_bar.setTextVisible(False)

        self.hits_list = QListWidget()
        self.hits_list.setObjectName("hits")
        self.hits_list.setItemDelegate(_HitDelegate(self.hits_list))
        self.hits_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.hits_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.hits_list.setAccessibleName("Places where a marked value is still present")

        self.saved_body = self._build_saved()

        self.back_button = QPushButton("Back to review")
        self.back_button.setProperty("large", True)
        self.back_button.clicked.connect(self.reject)
        self.close_button = QPushButton("Done")
        self.close_button.setObjectName("primary")
        self.close_button.setProperty("large", True)
        self.close_button.clicked.connect(self.accept)
        self.buttons = QWidget()
        row = QHBoxLayout(self.buttons)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(10)
        row.addStretch(1)
        row.addWidget(self.back_button)
        row.addWidget(self.close_button)

        sheet = QFrame()
        sheet.setObjectName("sheet")
        column = QVBoxLayout(sheet)
        column.setContentsMargins(28, 28, 28, 24)
        column.setSpacing(18)
        for part in (
            self.header,
            self.progress_bar,
            self.hits_list,
            self.saved_body,
            self.buttons,
        ):
            column.addWidget(part)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(sheet)

    def _build_saved(self) -> QWidget:
        """What the sheet says after a save, under the headline: the file, the instruction and
        the details.
        """
        self.file_names_label = ElidedLines()
        self.file_names_label.setObjectName("fileName")
        self.file_names_label.setTextFormat(Qt.TextFormat.PlainText)
        self.file_caption_label = QLabel()
        self.file_caption_label.setObjectName("fileCaption")
        self.file_caption_label.setWordWrap(True)
        self.file_caption_label.setTextFormat(Qt.TextFormat.PlainText)
        self.finder_button = QPushButton("Show in Finder")
        self.finder_button.setProperty("small", True)
        self.finder_button.clicked.connect(self._show_in_finder)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(self.file_names_label)
        names.addWidget(self.file_caption_label)
        card = QFrame()
        card.setObjectName("fileCard")
        file_row = QHBoxLayout(card)
        file_row.setContentsMargins(14, 12, 14, 12)
        file_row.setSpacing(12)
        file_row.addWidget(DocGlyph())
        file_row.addLayout(names, 1)
        file_row.addWidget(self.finder_button)

        self.copy_button = QPushButton("Copy instruction")
        self.copy_button.setObjectName("primary")
        self.copy_button.setProperty("small", True)
        self.copy_button.setToolTip("Put the instruction for the AI tool on the clipboard.")
        self.copy_button.clicked.connect(self._copy_instruction)
        next_step = QLabel(NEXT_STEP)
        next_step.setObjectName("instructionTitle")
        next_step.setWordWrap(True)
        self.instruction_label = QLabel(AI_INSTRUCTION)
        self.instruction_label.setObjectName("instructionText")
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setTextFormat(Qt.TextFormat.PlainText)
        self.instruction_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box = QFrame()
        box.setObjectName("instructionBox")
        inside = QVBoxLayout(box)
        inside.setContentsMargins(14, 12, 14, 12)
        inside.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.addWidget(next_step, 1)
        title_row.addWidget(self.copy_button)
        inside.addLayout(title_row)
        inside.addWidget(self.instruction_label)

        self.details_button = QToolButton()
        self.details_button.setObjectName("detailsButton")
        self.details_button.setCheckable(True)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_button.toggled.connect(self._toggle_details)
        self.details = QPlainTextEdit()
        self.details.setObjectName("details")
        self.details.setReadOnly(True)
        self.details.setAccessibleName("What was found beyond the marks")
        self.details.hide()

        body = QWidget()
        stack = QVBoxLayout(body)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(18)
        stack.addWidget(card)
        stack.addWidget(box)
        disclosure = QVBoxLayout()
        disclosure.setSpacing(8)
        disclosure.addWidget(self.details_button, alignment=Qt.AlignmentFlag.AlignLeft)
        disclosure.addWidget(self.details)
        stack.addLayout(disclosure)
        return body

    # ---- the interface the rest of the app uses --------------------------------------------

    @property
    def result(self) -> ExportResult | None:  # type: ignore[override]  # not QDialog.result()
        """What the export did; None while it is running and after a failure."""
        return self._outcome

    def run(
        self,
        sources: list[SourceDoc],
        review: ReviewState,
        options: ExportOptions,
        ctx: AppContext,
    ) -> None:
        """Mask, check and save ``sources`` as ``review`` says, with ``options``.

        The case is saved in the case store of ``ctx``, the detection runs with its engine and the
        owner's lists. Returns at once; ``finishedExport`` follows. Raises RuntimeError when a run
        is already going: a dialog works for one export.
        """
        if self._worker is not None:
            raise RuntimeError(ALREADY_RUNNING)
        self._folder = options.out_dir
        self._show_working()
        if ctx.engine is None:
            self._show_failed(NO_ENGINE_MESSAGE)
            return
        worker = ExportWorker(
            sources, review, options, ctx.engine, ctx.user_lists, ctx.case_store.save
        )
        worker.finished.connect(self._worker_finished)
        worker.failed.connect(self._worker_failed)
        self._worker = worker
        worker.start()

    def is_running(self) -> bool:
        """Whether the files are still being made."""
        return self._worker is not None

    def wait_for_worker(self) -> None:
        """Wait until the thread, if there is one, has ended, and let go of it.

        A thread must not be destroyed while it runs, and an export cannot be interrupted, so the
        window waits here when it closes. Its result is dropped.
        """
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait()
            worker.deleteLater()

    def summary_text(self) -> str:
        """The words of the outcome in plain text: the headline, then what the sheet says under
        it (the files and the case, what was found beyond the marks, or why nothing was saved).
        """
        return "\n\n".join(text for text in (self.headline_label.text(), self._summary) if text)

    def reject(self) -> None:
        """Close the dialog, unless the files are still being made (Escape and the window's close
        button come here too).
        """
        if self._worker is None:
            super().reject()

    def showEvent(self, event: QShowEvent) -> None:
        self._fit()  # the style sheet is in force now: the sizes are the real ones
        super().showEvent(event)

    # ---- the outcome -----------------------------------------------------------------------

    def _worker_finished(self, result: object) -> None:
        self._release_worker()
        outcome = result if isinstance(result, ExportResult) else None
        if outcome is None:
            self._show_failed(UNEXPECTED_MESSAGE)
        elif outcome.blocked:
            self._show_blocked(outcome)
        else:
            self._show_saved(outcome)

    def _worker_failed(self, message: str) -> None:
        self._release_worker()
        self._show_failed(message)

    def _release_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait()  # it has sent its last signal; this is the end of its run()
            worker.deleteLater()

    def _show_working(self) -> None:
        self._say(WORKING, WORKING_HINT, badge=None)
        self._summary = WORKING_HINT
        self._offer(body="progress", copy=False, finder=False, close=False, back=False)

    def _show_saved(self, result: ExportResult) -> None:
        self._outcome = result
        many = len(result.outputs) > 1
        self._say(SAVED_MANY if many else SAVED_ONE, SAVED_CAPTION, badge="check")
        self.instruction_label.setText(result.instruction)
        folder = result.outputs[0].parent if result.outputs else self._folder
        self.file_names_label.setText("\n".join(path.name for path in result.outputs))
        self.file_caption_label.setText(self._file_caption(result, folder))
        sections = self._sections(result)
        extra = ""
        if result.shown_on_purpose:
            extra += f" · {len(result.shown_on_purpose)} shown by choice"
        if result.still_asked:
            extra += f" · {len(result.still_asked)} never answered"
        self.details_button.setText(
            f"Details · {len(result.allowed_hits)} left visible on purpose"
            f" · {len(result.unverifiable)} not checkable · {len(result.unmarked)} found unmarked"
            + extra
        )
        self.details.setPlainText("\n\n".join(sections) if sections else NOTHING_TO_REPORT)
        lines = self.details.blockCount()
        self.details.setFixedHeight(min(lines, DETAILS_LINES) * DETAILS_LINE + 16)
        # What the owner never marked is not fine print: it is shown without being asked for.
        self.details_button.setChecked(bool(result.unmarked or result.still_asked))
        self._toggle_details(self.details_button.isChecked())
        self._summary = self._saved_text(result)
        self._offer(body="saved", copy=True, finder=True, close=True, back=True)
        self.close_button.setDefault(True)
        self.close_button.setFocus()
        self.setAccessibleDescription(self.summary_text())
        self.finishedExport.emit()

    def _show_blocked(self, result: ExportResult) -> None:
        self._outcome = result
        self._say(BLOCKED, BLOCKED_ADVICE, badge="alert", tone="danger")
        self.hits_list.clear()
        for hit in result.leak_hits:
            item = QListWidgetItem(_hit_line(hit))
            item.setToolTip(_hit_line(hit))
            item.setData(_HitDelegate.PART_ROLE, hit.part)
            item.setData(_HitDelegate.CONTEXT_ROLE, hit.context)
            item.setData(
                _HitDelegate.PLACES_ROLE, _count(hit.count, "place") if hit.count > 1 else ""
            )
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.hits_list.addItem(item)
        self.hits_list.setFixedHeight(min(self.hits_list.count(), HITS_SHOWN) * HIT_ROW + 2)
        lines = [BLOCKED_ADVICE, "", *(f"  {_hit_line(hit)}" for hit in result.leak_hits)]
        self._summary = "\n".join(lines)
        self._offer(body="hits", copy=False, finder=False, close=False, back=True)
        self.back_button.setDefault(True)
        self.back_button.setFocus()
        self.setAccessibleDescription(self.summary_text())
        self.finishedExport.emit()

    def _show_failed(self, message: str) -> None:
        self._outcome = None
        self._say(FAILED, f"{NOTHING_SAVED} {message}", badge=None)
        self._summary = f"{NOTHING_SAVED} {message}"
        self._offer(body=None, copy=False, finder=False, close=False, back=True)
        self.back_button.setDefault(True)
        self.back_button.setFocus()
        self.setAccessibleDescription(self.summary_text())
        self.finishedExport.emit()

    def _say(self, headline: str, caption: str, badge: str | None, tone: str = "plain") -> None:
        """Put the words at the top of the sheet: the headline, the line under it, and the round
        mark beside them ("check" or "alert", or none). ``tone`` "danger" tints the whole top.
        """
        self.headline_label.setText(headline)
        self.caption_label.setText(caption)
        self.badge.setVisible(badge is not None)
        if badge is not None:
            self.badge.set_kind("check" if badge == "check" else "alert")
        if self.header.property("tone") != tone:
            self.header.setProperty("tone", tone)  # the style sheet reads it
            self.header.style().unpolish(self.header)
            self.header.style().polish(self.header)
        margin = 14 if tone == "danger" else 0
        self._header_row.setContentsMargins(margin + 2, margin, margin + 2, margin)

    def _offer(self, body: str | None, copy: bool, finder: bool, close: bool, back: bool) -> None:
        """Show what makes sense now: one of the bodies (the progress bar, the places of a block
        or the saved files), and the buttons. A button that is not offered is off too.
        """
        self.progress_bar.setVisible(body == "progress")
        self.hits_list.setVisible(body == "hits")
        self.saved_body.setVisible(body == "saved")
        for button, shown in (
            (self.copy_button, copy),
            (self.finder_button, finder),
            (self.close_button, close),
            (self.back_button, back),
        ):
            button.setVisible(shown)
            button.setEnabled(shown)
        self.buttons.setVisible(close or back)
        self._fit()

    def _fit(self) -> None:
        """Give the sheet the height its words need at its width: the layout cannot, as the
        words wrap.
        """
        layout = self.layout()
        if layout is None:
            return
        self.ensurePolished()
        for inner in self.findChildren(QLayout):
            inner.invalidate()  # a widget that was just shown or hidden is not yet in their sums
        layout.activate()
        height = layout.totalHeightForWidth(WIDTH) if layout.hasHeightForWidth() else 0
        self.setFixedHeight(max(height, layout.totalMinimumSize().height()))

    def _toggle_details(self, shown: bool) -> None:
        self.details_button.setArrowType(
            Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow
        )
        self.details.setVisible(shown)
        self._fit()

    def _file_caption(self, result: ExportResult, folder: Path | None) -> str:
        """Where the files are, which case holds their key, how many values are hidden in them,
        and for how long the key is kept.
        """
        parts = [folder_trail(folder)] if folder is not None else []
        if result.case is not None:
            parts += [
                f"case {result.case.id}",
                f"{_count(len(result.case.entries), 'value')} hidden",
                f"key kept for {_count(result.case.retention_days, 'day')}",
            ]
        return " · ".join(parts)

    @staticmethod
    def _sections(result: ExportResult) -> list[str]:
        """What the check found beyond the marks, each part under its heading."""
        blocks: list[str] = []
        if result.unmarked:
            found = "\n".join(
                f"  • {group.canonical} ({group.type.value})" for group in result.unmarked
            )
            blocks.append(f"{UNMARKED}\n{found}")
        if result.still_asked:
            asked = "\n".join(f"  • {g.canonical} ({g.type.value})" for g in result.still_asked)
            blocks.append(f"{STILL_ASKED}\n{asked}")
        if result.shown_on_purpose:
            chosen = "\n".join(
                f"  • {g.canonical} ({g.type.value})" for g in result.shown_on_purpose
            )
            blocks.append(f"{SHOWN_ON_PURPOSE}\n{chosen}")
        if result.allowed_hits:
            shown = "\n".join(f"  • {_hit_line(hit)}" for hit in result.allowed_hits)
            blocks.append(f"{LEFT_VISIBLE}\n{shown}")
        if result.unverifiable:
            blocks.append(f"{NOT_CHECKABLE} {', '.join(result.unverifiable)}")
        return blocks

    def _saved_text(self, result: ExportResult) -> str:
        folder = result.outputs[0].parent if result.outputs else self._folder
        names = "\n".join(f"  {path.name}" for path in result.outputs)
        blocks = [f"Saved in {folder}:\n{names}" if folder is not None else names]
        if result.case is not None:
            blocks.append(
                f"The key that restores them is kept on this Mac as case {result.case.id},"
                f" for {_count(result.case.retention_days, 'day')}."
            )
        return "\n\n".join([*blocks, *self._sections(result)])

    # ---- the buttons -----------------------------------------------------------------------

    def _copy_instruction(self) -> None:
        # The result's own instruction: it says that every name in brackets is a placeholder
        # when the owner named some (ruling R127); the plain one stands only before a result.
        result = self._outcome
        QApplication.clipboard().setText(AI_INSTRUCTION if result is None else result.instruction)

    def _show_in_finder(self) -> None:
        result = self._outcome
        folder = result.outputs[0].parent if result is not None and result.outputs else self._folder
        if folder is not None:
            reveal(folder)


def _hit_line(hit: LeakHit) -> str:
    """Where a value of the key stands in a file, as one line: the part, what is round the hit,
    and how many places read the same when it is more than one.
    """
    places = f" ({_count(hit.count, 'place')})" if hit.count > 1 else ""
    return f"{hit.part}: {hit.context}{places}"
