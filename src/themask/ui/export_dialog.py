"""The export dialog: the files are masked and checked in a thread of their own, and the owner is
told what was saved, or why nothing was.

``ExportDialog.run`` hands ``export_case`` to an ``ExportWorker``, so that the window stays alive
while the files are made. The dialog cannot be closed before the worker is done: a thread cannot
be interrupted, and the files it writes must not be left half done. At the end it shows one of
three things:

- *saved*: the names of the files, the case that holds their key, what the detection still finds
  in the masked copy that the owner never marked, the places the owner left visible on purpose and
  the values too short to be checked; with buttons to copy the instruction for the AI tool and to
  show the folder in Finder;
- *blocked*: a value the owner marked is still in a file. The places are named and only the way
  back to the review is offered; nothing is saved;
- *failed*: the export could not be made, in plain words; nothing is saved either.

What the worker tells the owner is plain English. What it writes to the log is the kind of an
unexpected error and nothing else, as the rule in logging_setup.py says: the text of an error may
quote a file name, and a file name tells who the parties are.

``ExportWorker.finished`` takes the place of QThread's own signal of that name, which has no
payload, as ``AnalysisWorker.finished`` does (see workers.py).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME
from themask.errors import MaskError
from themask.export import ExportOptions, ExportResult, export_case
from themask.instruction import AI_INSTRUCTION
from themask.leakcheck import LeakHit

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.export import SourceDoc
    from themask.model import Case
    from themask.review import ReviewState
    from themask.ui.app import AppContext

_LOG = logging.getLogger(__name__)

WORKING = "Masking and checking the files…"
WORKING_HINT = (
    "The files are masked first and then checked for every value you marked. Nothing is saved"
    " unless the check passes."
)
SAVED_ONE = "The masked copy is saved"
SAVED_MANY = "The masked copies are saved"
BLOCKED = "Saving blocked: a marked value is still present"
FAILED = "The masked files could not be saved"
NOTHING_SAVED = "Nothing was saved."
BLOCKED_ADVICE = (
    f"{NOTHING_SAVED} A value you marked still shows in the places below. Go back to the review,"
    " or take the value out of the file in Word and open the file again."
)
UNMARKED = "Also found in the masked copy — not marked by you:"
LEFT_VISIBLE = "Left visible on purpose:"
NOT_CHECKABLE = "Not checkable (too short):"
UNEXPECTED_MESSAGE = "Something went wrong while saving the masked files."
DISK_MESSAGE = "The masked files could not be written:"
NO_ENGINE_MESSAGE = "The detection engine is not loaded, so the files cannot be checked."
ALREADY_RUNNING = "An export is already running in this dialog."


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


class ExportDialog(QDialog):
    """Makes the masked files and shows what came of it. ``run`` starts it, once.

    ``finishedExport`` is sent when the outcome is on the screen, whatever it is, so that a caller
    never waits for nothing. ``result`` is the ``ExportResult`` (None while the files are made and
    after a failure), ``summary_text()`` the words on the screen, ``copy_button`` puts the
    instruction for the AI tool on the clipboard and is off unless the files are saved.
    """

    finishedExport = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Export")
        self.setModal(True)
        self.setMinimumSize(560, 380)
        self._outcome: ExportResult | None = None
        self._worker: ExportWorker | None = None
        self._folder: Path | None = None

        self.headline_label = QLabel(WORKING)
        self.headline_label.setObjectName("heading")
        self.headline_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # busy: the export cannot say how far it has come
        self.progress_bar.setTextVisible(False)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.copy_button = QPushButton("Copy instruction")
        self.copy_button.setToolTip("Put the instruction for the AI tool on the clipboard.")
        self.copy_button.clicked.connect(self._copy_instruction)
        self.finder_button = QPushButton("Show in Finder")
        self.finder_button.clicked.connect(self._show_in_finder)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("primary")
        self.close_button.clicked.connect(self.accept)
        self.back_button = QPushButton("Back to review")
        self.back_button.setObjectName("primary")
        self.back_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.finder_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.back_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.headline_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.details, 1)
        layout.addLayout(buttons)
        self._show_working()

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
        """The words on the screen: the headline, then the details under it."""
        return "\n\n".join(
            text for text in (self.headline_label.text(), self.details.toPlainText()) if text
        )

    def reject(self) -> None:
        """Close the dialog, unless the files are still being made (Escape and the window's close
        button come here too).
        """
        if self._worker is None:
            super().reject()

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
        self.headline_label.setText(WORKING)
        self.details.setPlainText(WORKING_HINT)
        self.progress_bar.show()
        self._offer(copy=False, finder=False, close=False, back=False)

    def _show_saved(self, result: ExportResult) -> None:
        self._outcome = result
        many = len(result.outputs) > 1
        self.headline_label.setText(SAVED_MANY if many else SAVED_ONE)
        self.details.setPlainText(self._saved_text(result))
        self._offer(copy=True, finder=True, close=True, back=False)
        self.finishedExport.emit()

    def _show_blocked(self, result: ExportResult) -> None:
        self._outcome = result
        self.headline_label.setText(BLOCKED)
        lines = [BLOCKED_ADVICE, "", *(f"  {_hit_line(hit)}" for hit in result.leak_hits)]
        self.details.setPlainText("\n".join(lines))
        self._offer(copy=False, finder=False, close=False, back=True)
        self.finishedExport.emit()

    def _show_failed(self, message: str) -> None:
        self._outcome = None
        self.headline_label.setText(FAILED)
        self.details.setPlainText(f"{NOTHING_SAVED} {message}")
        self._offer(copy=False, finder=False, close=False, back=True)
        self.finishedExport.emit()

    def _offer(self, copy: bool, finder: bool, close: bool, back: bool) -> None:
        """Show the buttons that make sense now (and the progress bar only while it works)."""
        for button, shown in (
            (self.copy_button, copy),
            (self.finder_button, finder),
            (self.close_button, close),
            (self.back_button, back),
        ):
            button.setVisible(shown)
            button.setEnabled(shown)
        self.progress_bar.setVisible(not (copy or finder or close or back))

    def _saved_text(self, result: ExportResult) -> str:
        folder = result.outputs[0].parent if result.outputs else self._folder
        names = "\n".join(f"  {path.name}" for path in result.outputs)
        blocks = [f"Saved in {folder}:\n{names}" if folder is not None else names]
        if result.case is not None:
            blocks.append(
                f"The key that restores them is kept on this Mac as case {result.case.id},"
                f" for {_count(result.case.retention_days, 'day')}."
            )
        if result.unmarked:
            found = "\n".join(
                f"  {group.canonical} ({group.type.value})" for group in result.unmarked
            )
            blocks.append(f"{UNMARKED}\n{found}")
        if result.allowed_hits:
            shown = "\n".join(f"  {_hit_line(hit)}" for hit in result.allowed_hits)
            blocks.append(f"{LEFT_VISIBLE}\n{shown}")
        if result.unverifiable:
            blocks.append(f"{NOT_CHECKABLE} {', '.join(result.unverifiable)}")
        return "\n\n".join(blocks)

    # ---- the buttons -----------------------------------------------------------------------

    def _copy_instruction(self) -> None:
        QApplication.clipboard().setText(AI_INSTRUCTION)

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
