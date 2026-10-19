"""The main window: the screens of the app, and the way from the files the owner chose to the review.

The screens are in a stack, each under a name: "home", "review", "restore", "cases" and "settings".
The export is a dialog over the review, not a screen of its own (``show_export``).
``open_files`` is the one way in. It asks whether to make a before-and-after pair when
a file has tracked changes, loads the case a file is added to, and hands the analysis to a thread
(``AnalysisWorker``), so that the window stays alive; its result becomes the review screen. The
detection engine takes seconds to load and is loaded in a thread too: until it is there the home
screen says "Loading…", and a request made meanwhile waits for it.

What the next steps need from the analysis stays on the window: ``sources`` (the files as loaded),
``redline_split`` (whether some file was loaded as a before-and-after pair) and ``pending_case``
(the case a file is added to, or None for a new one), which the export reads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME
from themask.detect.lists import CaseLists
from themask.docx.package import DocxPackage
from themask.docx.reader import has_revisions
from themask.errors import MaskError
from themask.export import ExportOptions, SourceDoc, combined_text
from themask.model import Analysis, Case
from themask.review import ReviewState
from themask.ui.drop_zone import DropZone
from themask.ui.export_dialog import ExportDialog
from themask.ui.review_screen import ReviewScreen
from themask.ui.workers import AnalysisWorker, EngineWorker

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.ui.app import AppContext

REDLINE_QUESTION = "This file contains tracked changes. Make a before-and-after pair?"
BUSY_MESSAGE = "The MASK is still analysing a file. Wait until it is done, then try again."
CASE_GONE = "That case no longer exists. It may have been deleted, or it has expired."
PURGE_FAILED = "Old cases could not be cleaned up."
CASES_UNREADABLE = "The saved cases could not be read:"

# What the home screen says for each step of an analysis (the names are the worker's).
STEP_TEXT = {
    "loading": "Opening the files…",
    "reading": "Reading the text…",
    "finding": "Finding the confidential values…",
    "grouping": "Putting the values in groups…",
    "done": "Done",
}


def show_error(parent: QWidget | None, message: str) -> None:
    """Tell the owner what went wrong, in the words of the error: never a stack trace."""
    QMessageBox.critical(parent, APP_NAME, message)


def ask_redline(parent: QWidget | None) -> bool:
    """Ask whether to make a before-and-after pair of a file with tracked changes."""
    answer = QMessageBox.question(parent, APP_NAME, REDLINE_QUESTION)
    return answer == QMessageBox.StandardButton.Yes


class HomeScreen(QWidget):
    """The first screen: the drop zone, what the app is doing, and the progress of an analysis."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        tagline = QLabel(
            "Hide the confidential values in a contract before an AI tool reads it."
            " Everything stays on this Mac."
        )
        tagline.setObjectName("tagline")
        tagline.setWordWrap(True)
        self.drop_zone = DropZone()
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.step_label = QLabel()
        self.notice_label = QLabel()
        self.notice_label.setObjectName("notice")
        self.notice_label.setWordWrap(True)
        self._notices: list[str] = []

        for label in (title, tagline, self.status_label, self.step_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column = QVBoxLayout()
        column.setSpacing(14)
        column.addWidget(title)
        column.addWidget(tagline)
        column.addSpacing(10)
        column.addWidget(self.drop_zone)
        column.addWidget(self.status_label)
        column.addWidget(self.progress_bar)
        column.addWidget(self.step_label)
        column.addWidget(self.notice_label)
        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(680)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addWidget(holder, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)
        self.show_ready()
        self._show_notices()

    def show_loading(self) -> None:
        """The engine is loading: nothing can be dropped yet."""
        self._rest("Loading…", dropping=False)

    def show_ready(self) -> None:
        """Nothing is running: files can be dropped."""
        self._rest("Ready", dropping=True)

    def show_busy(self) -> None:
        """An analysis is running: its progress is shown, and nothing more can be dropped."""
        self.status_label.setText("Analysing…")
        self.drop_zone.setEnabled(False)
        self.show_progress(0, "loading")

    def show_engine_problem(self, message: str) -> None:
        """The engine could not be loaded: say so, and keep the drop zone off."""
        self._rest("The detection engine could not be loaded.", dropping=False)
        self.add_notice(message)

    def show_progress(self, percent: int, step: str) -> None:
        """Show how far an analysis has come, and in which step."""
        self.progress_bar.setValue(percent)
        self.step_label.setText(STEP_TEXT.get(step, step))
        self.progress_bar.show()
        self.step_label.show()

    def add_notice(self, text: str) -> None:
        """Add a line to the notices under the drop zone (a problem that does not stop the app)."""
        self._notices.append(text)
        self._show_notices()

    def _rest(self, status: str, dropping: bool) -> None:
        self.status_label.setText(status)
        self.drop_zone.setEnabled(dropping)
        self.progress_bar.hide()
        self.step_label.hide()

    def _show_notices(self) -> None:
        self.notice_label.setText("\n".join(self._notices))
        self.notice_label.setVisible(bool(self._notices))


@dataclass
class _Request:
    """Files to analyse, as asked: whether to make a before-and-after pair of the ones with
    tracked changes, and the case they are added to (None for a new one).
    """

    paths: list[Path]
    redline_split: bool
    case_id: str | None


@dataclass
class _Run:
    """What an analysis in progress was started with and the review made from it needs."""

    case: Case | None
    case_lists: CaseLists


class MainWindow(QMainWindow):
    """The window of The MASK. ``ctx`` is what the screens share (see ``themask.ui.app``).

    ``load_engine`` makes the engine when ``ctx.engine`` is None; without it the default engine is
    loaded. Signals: ``analysisProgress(percent, step)`` for each step of an analysis (it ends
    with 100 and "done"), ``analysisFinished`` once the review screen is showing, and
    ``analysisFailed(message)`` after the message was shown to the owner. ``export_dialog`` is the
    export while it is open, else None.
    """

    analysisProgress = Signal(int, str)
    analysisFinished = Signal()
    analysisFailed = Signal(str)

    def __init__(self, ctx: AppContext, load_engine: Callable[[], Engine] | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        self.sources: list[SourceDoc] = []
        self.redline_split = False
        self.pending_case: Case | None = None
        self.export_dialog: ExportDialog | None = None
        self._run: _Run | None = None
        self._queued: _Request | None = None
        self._analysis: AnalysisWorker | None = None
        self._engine_loader: EngineWorker | None = None
        self._engine_problem: str | None = None
        self._closing = False

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 780)
        self.home = HomeScreen()
        self.review_screen = ReviewScreen()
        self._stack = QStackedWidget()
        self._screens: dict[str, QWidget] = {
            "home": self.home,
            "review": self.review_screen,
            "restore": _placeholder("Restoring is the next step of the build."),
            "cases": _placeholder("The list of cases is the next step of the build."),
            "settings": _placeholder("The settings are the next step of the build."),
        }
        for screen in self._screens.values():
            self._stack.addWidget(screen)
        self.setCentralWidget(self._stack)
        self._review_action = self._build_navigation()

        self.home.drop_zone.filesDropped.connect(self._files_dropped)
        self.review_screen.exportRequested.connect(self.show_export)
        self.analysisProgress.connect(self.home.show_progress)
        self._purge_expired_cases()
        if ctx.engine is None:
            self._load_engine(load_engine)

    # ---- the screens -----------------------------------------------------------------------

    def screen_names(self) -> list[str]:
        """The names of the screens in the stack."""
        return list(self._screens)

    def current_screen_name(self) -> str:
        """The name of the screen that is showing."""
        current = self._stack.currentWidget()
        return next(name for name, screen in self._screens.items() if screen is current)

    def show_home(self) -> None:
        self._show("home")

    def show_review(self, sources: list[SourceDoc], analysis: Analysis) -> None:
        """Show the review of an analysis of ``sources``.

        The review is made here, from the lists of the case the analysis belonged to (the same
        ones it filled in) and the placeholders of the case's key when a file is added to a case.
        """
        run = self._run
        case = run.case if run is not None else None
        case_lists = run.case_lists if run is not None else CaseLists([], [], set())
        reserved = [entry.placeholder for entry in case.entries] if case is not None else []
        review = ReviewState.from_analysis(analysis, self.ctx.user_lists, case_lists, reserved)
        self.sources = sources
        self.redline_split = any(source.pkg_before is not None for source in sources)
        self.pending_case = case
        self.review_screen.load(review, combined_text(sources))
        self._review_action.setEnabled(True)
        self._show("review")

    def show_export(self) -> None:
        """Open the export dialog over the review, for the files and the review as they are.

        The dialog gets the owner's settings (the folder, the days a case is kept), whether the
        files were loaded as before-and-after pairs, the case a file is added to, and the codes
        of the cases the store holds, so that a new case never takes one. A request made while
        the dialog is open is ignored. A case store that cannot be read is said in words.
        """
        if self.export_dialog is not None:
            return
        try:
            codes = self._case_codes()
        except MaskError as error:
            show_error(self, error.user_message)
            return
        except OSError as error:
            show_error(self, f"{CASES_UNREADABLE} {error.strerror or error}")
            return
        settings = self.ctx.settings
        options = ExportOptions(
            out_dir=settings.out_dir,
            redline_split=self.redline_split,
            retention_days=settings.retention_days,
            existing_case=self.pending_case,
            existing_codes=codes,
        )
        dialog = ExportDialog(self)
        dialog.finished.connect(self._export_closed)
        self.export_dialog = dialog
        dialog.open()
        dialog.run(self.sources, self.review_screen.review, options, self.ctx)

    def _case_codes(self) -> list[str]:
        """The codes of the cases in the store: those that open, and the names of the files that
        do not (ruling R74).
        """
        store = self.ctx.case_store
        codes = [summary.id for summary in store.list()]  # also finds the files that do not open
        return codes + [path.stem for path in store.unreadable]

    def _export_closed(self) -> None:
        dialog, self.export_dialog = self.export_dialog, None
        if dialog is not None:
            dialog.deleteLater()

    def show_restore(self) -> None:
        self._show("restore")

    def show_cases(self) -> None:
        self._show("cases")

    def show_settings(self) -> None:
        self._show("settings")

    def _show(self, name: str) -> None:
        self._stack.setCurrentWidget(self._screens[name])

    def _build_navigation(self) -> QAction:
        """The tool bar that moves between the screens; returns the action for the review, which
        has nothing to show until a file was analysed.
        """
        bar = QToolBar("Screens")
        bar.setMovable(False)
        self.addToolBar(bar)
        bar.addAction("Home").triggered.connect(self.show_home)
        review_action = bar.addAction("Review")
        review_action.setEnabled(False)
        review_action.triggered.connect(lambda: self._show("review"))
        bar.addAction("Restore").triggered.connect(self.show_restore)
        bar.addAction("Cases").triggered.connect(self.show_cases)
        bar.addAction("Settings").triggered.connect(self.show_settings)
        return review_action

    # ---- opening files ---------------------------------------------------------------------

    def open_files(
        self, paths: list[Path], redline_split: bool | None, case_id: str | None = None
    ) -> None:
        """Analyse the files at ``paths`` and show the review.

        ``redline_split`` says whether a file with tracked changes is made into a before-and-after
        pair; None asks the owner, once, when any of the Word files has tracked changes. With
        ``case_id`` the files are added to that case: the analysis is seeded with its key and
        the review keeps its placeholders. Nothing is done while another analysis is running.
        Whatever goes wrong is shown to the owner, and ``analysisFailed`` is sent.
        """
        if not paths:
            return
        if self._analysis is not None:
            show_error(self, BUSY_MESSAGE)
            return
        if redline_split is None:
            redline_split = self._asks_for_redline(paths)
        request = _Request(list(paths), redline_split, case_id)
        if self.ctx.engine is not None:
            self._start(request)
        elif self._engine_problem is not None:
            self._fail(self._engine_problem)
        else:
            self._queued = request  # runs when the engine has loaded

    def _files_dropped(self, paths: list[Path]) -> None:
        self.open_files(paths, None)

    def _asks_for_redline(self, paths: list[Path]) -> bool:
        """Ask whether to make a before-and-after pair, if any of the files has tracked changes."""
        if any(_has_tracked_changes(path) for path in paths):
            return ask_redline(self)
        return False

    def _start(self, request: _Request) -> None:
        """Load the case the files are added to, if any, and hand the analysis to a thread."""
        engine = self.ctx.engine
        assert engine is not None, "the engine is there before an analysis starts"
        case: Case | None = None
        if request.case_id is not None:
            try:
                case = self.ctx.case_store.load(request.case_id)
            except (FileNotFoundError, ValueError):  # ValueError: not the id of any case
                self._fail(CASE_GONE)
                return
            except MaskError as error:
                self._fail(error.user_message)
                return
            except OSError as error:
                self._fail(f"The case could not be read: {error.strerror or error}")
                return
        case_lists = CaseLists([], [], set())  # the analysis fills in the terms the files define
        worker = AnalysisWorker(
            request.paths,
            request.redline_split,
            engine,
            self.ctx.user_lists,
            case_lists,
            case.entries if case is not None else None,
        )
        worker.progress.connect(self.analysisProgress)
        worker.finished.connect(self._analysis_finished)
        worker.failed.connect(self._analysis_failed)
        self._run = _Run(case, case_lists)
        self._analysis = worker
        self.home.show_busy()
        worker.start()

    def is_analysing(self) -> bool:
        """Whether an analysis was started and its result is not shown yet."""
        return self._analysis is not None

    def _analysis_finished(self, result: object) -> None:
        self._release_analysis()
        if self._closing:
            return
        sources, analysis = cast("tuple[list[SourceDoc], Analysis]", result)
        try:
            self.show_review(sources, analysis)
        finally:
            self._run = None
            self.home.show_ready()
        self.analysisFinished.emit()

    def _analysis_failed(self, message: str) -> None:
        self._release_analysis()
        self._run = None
        if self._closing:
            return
        self.home.show_ready()
        self._fail(message)

    def _fail(self, message: str) -> None:
        show_error(self, message)
        self.analysisFailed.emit(message)

    def _release_analysis(self) -> None:
        worker, self._analysis = self._analysis, None
        if worker is not None:
            worker.wait()  # it has sent its last signal; this is the end of its run()
            worker.deleteLater()

    # ---- the engine ------------------------------------------------------------------------

    def _load_engine(self, factory: Callable[[], Engine] | None) -> None:
        self.home.show_loading()
        loader = EngineWorker(factory)
        loader.loaded.connect(self._engine_loaded)
        loader.failed.connect(self._engine_failed)
        self._engine_loader = loader
        loader.start()

    def _engine_loaded(self, engine: object) -> None:
        self._release_engine_loader()
        if self._closing:
            return
        self.ctx.engine = cast("Engine", engine)
        self.home.show_ready()
        queued, self._queued = self._queued, None
        if queued is not None:
            self._start(queued)

    def _engine_failed(self, message: str) -> None:
        self._release_engine_loader()
        if self._closing:
            return
        self._engine_problem = message
        self.home.show_engine_problem(message)
        show_error(self, message)
        queued, self._queued = self._queued, None
        if queued is not None:
            self.analysisFailed.emit(message)

    def _release_engine_loader(self) -> None:
        loader, self._engine_loader = self._engine_loader, None
        if loader is not None:
            loader.wait()
            loader.deleteLater()

    # ---- the cases -------------------------------------------------------------------------

    def _purge_expired_cases(self) -> None:
        """Delete the cases that are due. The app opens whatever happens here: a problem is said
        on the home screen and nowhere else.
        """
        try:
            self.ctx.case_store.purge_expired()
        except MaskError as error:
            self.home.add_notice(f"{PURGE_FAILED} {error.user_message}")
        except OSError as error:
            self.home.add_notice(f"{PURGE_FAILED} {error.strerror or error}")

    # ---- closing ---------------------------------------------------------------------------

    def wait_for_workers(self) -> None:
        """Wait until no thread of the window is running, and let go of them.

        A thread must not be destroyed while it runs, and an analysis cannot be interrupted, so
        closing the window during one waits for it to end; its result is dropped.
        """
        for worker in (self._analysis, self._engine_loader):
            if worker is not None:
                worker.wait()
                worker.deleteLater()
        self._analysis = None
        self._engine_loader = None
        if self.export_dialog is not None:
            self.export_dialog.wait_for_worker()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self.hide()  # the owner sees the window go, however long a thread takes to end
        self.wait_for_workers()
        super().closeEvent(event)


def _has_tracked_changes(path: Path) -> bool:
    """Whether the Word file at ``path`` has tracked changes.

    The file is only looked at, quickly. A PDF has no tracked changes, and a file that cannot be
    read has none that matter: the analysis opens it again and reports what is wrong with it.
    """
    if path.suffix.casefold() != ".docx":
        return False
    try:
        return has_revisions(DocxPackage.open(path))
    except Exception:  # noqa: BLE001 - whatever is wrong, the analysis reports it
        return False


def _placeholder(text: str) -> QWidget:
    """A screen that only says what it is waiting for, until the step that builds it."""
    page = QWidget()
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout = QVBoxLayout(page)
    layout.addWidget(label)
    return page
