"""The main window: the shell around the screens, and the way from the files the owner chose to the
review.

The window is a tool bar on top (the sidebar toggle, the title of the screen and its primary
action), the sidebar on the left (Mask, Restore, Cases, and a note that goes with the screen) and,
filling the rest, the screens in a stack, each under a name: "home", "review", "restore" and
"cases". The Settings are not a screen: they are a window of their own (``SettingsWindow``),
opened by the Settings action of the application menu (Cmd+,). The export is a dialog over the
review, not a screen of its own (``show_export``).

What the screens can wire into (the shell's surface, kept stable):
- ``show_screen(name)`` shows a screen by its name, made up to date as its own ``show_...`` is;
- ``set_title(title, caption)`` sets the two lines of the tool bar for the screen that shows (or,
  with ``screen=``, for one that does not, until it does);
- ``primary_action`` is the action at the right of the tool bar: its words, what it does and
  whether it is on follow the screen (``set_primary`` says them for a screen, and ``refresh_chrome``
  checks again whether it is on, for a screen whose state changed);
- ``add_toolbar_widget(screen, widget)`` puts a widget in the tool bar, before the primary action,
  for as long as that screen shows.

``open_files`` is the one way in, and shows the home screen, where the progress is. It asks
whether to make a before-and-after pair when a file has tracked changes, loads the case a file is
added to, and hands the analysis to a thread (``AnalysisWorker``), so that the window stays alive;
its result becomes the review screen. The detection engine takes seconds to load and is loaded in
a thread too: until it is there the home screen says "Loading…", and a request made meanwhile
waits for it. One request at a time: a second one, while a file is analysed or waits for the
engine, is refused. While a file is analysed the sidebar, the Settings and the primary action are
off, so that nothing the analysis reads (the owner's lists, the case) changes under it.

What the next steps need from the analysis stays on the window: ``sources`` (the files as loaded),
``redline_split`` (whether some file was loaded as a before-and-after pair) and ``pending_case``
(the case a file is added to, or None for a new one), which the export reads.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QEvent, QObject, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFocusEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME
from themask.detect.lists import CaseLists
from themask.docx.package import DocxPackage
from themask.docx.reader import has_revisions
from themask.errors import KeyStoreError, MaskError
from themask.export import UNSUPPORTED_MESSAGE, ExportOptions, SourceDoc, combined_text
from themask.model import Analysis, Case
from themask.review import ReviewState, asks_about
from themask.ui import icons, theme
from themask.ui.cases_screen import NOT_READ, CasesScreen
from themask.ui.export_dialog import ExportDialog
from themask.ui.home_screen import HomeScreen
from themask.ui.restore_screen import RestoreScreen
from themask.ui.review_screen import ReviewScreen
from themask.ui.settings_screen import SettingsWindow
from themask.ui.sidebar import SECTION_OF_SCREEN, Sidebar
from themask.ui.widgets import ElidedLabel, is_keyboard_focus
from themask.ui.workers import AnalysisWorker, EngineWorker

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.ui.app import AppContext

_LOG = logging.getLogger(__name__)

# The crossfade between two screens: on, and how long (ms). The tests switch it off
# (tests/ui/conftest.py), as there is no one to look at it.
ANIMATIONS = True
FADE_MS = 120

REDLINE_QUESTION = "This file contains tracked changes. Make a before-and-after pair?"
BUSY_MESSAGE = "The MASK is still analysing a file. Wait until it is done, then try again."
CASE_GONE = "That case no longer exists. It may have been deleted, or it has expired."
PURGE_FAILED = "Old cases could not be cleaned up."
REVIEW_FAILED = "Something went wrong while preparing the review."

# The two lines of the tool bar for each screen until the screen says better: the title and the
# caption (the review's are the file names and what was found, set when a review is shown).
DEFAULT_TITLES = {
    "home": (APP_NAME, ""),
    "review": ("Review", ""),
    "restore": ("Restore", "Put the real values back into the file an AI tool returned"),
    "cases": ("Cases", "The keys that put real values back · kept on this Mac, encrypted"),
}


def show_error(parent: QWidget | None, message: str) -> None:
    """Tell the owner what went wrong, in the words of the error: never a stack trace."""
    QMessageBox.critical(parent, APP_NAME, message)


def ask_redline(parent: QWidget | None) -> bool:
    """Ask whether to make a before-and-after pair of a file with tracked changes."""
    answer = QMessageBox.question(parent, APP_NAME, REDLINE_QUESTION)
    return answer == QMessageBox.StandardButton.Yes


def ask_discard_review(parent: QWidget | None) -> bool:
    """Ask whether to throw away the review that is open, for a new file. True for "Discard"."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(APP_NAME)
    box.setText("Discard this review?")
    box.setInformativeText(
        "Choosing another file starts a new review. What you decided in this one is lost."
    )
    discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Keep reviewing", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.exec()
    return box.clickedButton() is discard


def ask_unanswered(parent: QWidget | None, count: int) -> bool:
    """Ask whether to export although ``count`` guesses under "Not sure — hide?" were not
    answered: they stay visible in the masked files. True for "Export anyway".
    """
    guesses = "1 guess" if count == 1 else f"{count} guesses"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(APP_NAME)
    box.setText(
        f"{guesses} under \u201cNot sure \u2014 hide?\u201d {'was' if count == 1 else 'were'} not"
        " answered and will stay visible."
    )
    anyway = box.addButton("Export anyway", QMessageBox.ButtonRole.AcceptRole)
    back = box.addButton("Back to review", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(back)
    box.exec()
    return box.clickedButton() is anyway


class SidebarToggle(QToolButton):
    """The button of the tool bar that hides the sidebar and shows it again: the icon of a window
    with its sidebar, 30 by 26 points, no text. Its name says what a press does.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(30, 26)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._ring = False  # the focus ring shows when the keyboard brought the focus
        self.set_sidebar_shown(True)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self._ring = is_keyboard_focus(event.reason())
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._ring = False
        super().focusOutEvent(event)

    def set_sidebar_shown(self, shown: bool) -> None:
        """Name the button for what it does now: hide the sidebar that shows, or show it."""
        name = "Hide sidebar" if shown else "Show sidebar"
        self.setAccessibleName(name)
        self.setToolTip(name)

    def paintEvent(self, event: QPaintEvent) -> None:
        t = theme.tokens_of(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isEnabled() and self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.hairline))
            painter.drawRoundedRect(QRectF(self.rect()), 6, 6)
        ink = QColor(t.secondary if self.isEnabled() else t.tertiary)
        icons.draw(painter, "sidebar", QRectF((30 - 16) / 2, (26 - 16) / 2, 16, 16), ink)
        if self.hasFocus() and self._ring:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.accent), 1.5))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)


class TitleBlock(QWidget):
    """The middle of the tool bar: two centred lines, the title of the screen over a caption."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBlock")
        self.title_label = ElidedLabel()
        self.title_label.setObjectName("toolbarTitle")
        self.caption_label = ElidedLabel()
        self.caption_label.setObjectName("toolbarCaption")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for label in (self.title_label, self.caption_label):
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(label)
        self.caption_label.hide()

    def set_texts(self, title: str, caption: str = "") -> None:
        """Say ``title`` and, under it, ``caption`` (the line is not there when it is empty)."""
        self.title_label.setText(title)
        self.caption_label.setText(caption)
        self.caption_label.setVisible(bool(caption))


class _EnabledWatcher(QObject):
    """Calls ``callback`` whenever the widget it watches is switched on or off."""

    def __init__(self, widget: QWidget, callback: Callable[[], None]) -> None:
        super().__init__(widget)
        self._callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.EnabledChange:
            self._callback()
        return False


@dataclass
class _Primary:
    """The primary action on one screen: its words, what it does and when it is on."""

    text: str
    run: Callable[[], None]
    enabled: Callable[[], bool]


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

    The parts of the shell: ``toolbar`` with ``sidebar_toggle``, ``title_block`` and
    ``primary_action``, ``sidebar``, the screens (``home``, ``review_screen``, ``restore_screen``
    and ``cases_screen``), and ``settings_window`` holding ``settings_screen``. ``choose_action``
    (Cmd+O) and ``settings_action`` (Cmd+,, the application menu's Settings) are in the menu.
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
        self._review_ready = False
        self._review_exported = False  # the open review was saved as masked files
        self._closing = False
        self._fade: tuple[QPropertyAnimation, QLabel] | None = None
        self._titles = dict(DEFAULT_TITLES)
        self._primary: dict[str, _Primary] = {}
        self._toolbar_extras: dict[str, list[QAction]] = {}

        self.setUnifiedTitleAndToolBarOnMac(True)
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 780)
        self.home = HomeScreen(ctx)
        self.review_screen = ReviewScreen()
        self.restore_screen = RestoreScreen(ctx)
        self.cases_screen = CasesScreen(ctx)
        self.settings_window = SettingsWindow(ctx, self)
        self.settings_screen = self.settings_window.settings_screen
        self.sidebar = Sidebar()
        self._stack = QStackedWidget()
        self._stack.setObjectName("screenStack")
        self._screens: dict[str, QWidget] = {
            "home": self.home,
            "review": self.review_screen,
            "restore": self.restore_screen,
            "cases": self.cases_screen,
        }
        for screen in self._screens.values():
            self._stack.addWidget(screen)
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.sidebar)
        row.addWidget(self._stack, 1)
        self.setCentralWidget(body)
        self._build_toolbar()
        self._build_menu()
        self._build_primary()
        self._wire()
        self._apply_chrome("home")
        self._purge_expired_cases()
        self.home.refresh_recent()
        if ctx.engine is None:
            self._load_engine(load_engine)

    def _wire(self) -> None:
        """Connect the screens, the sidebar and the actions to the window."""
        self.sidebar.sectionRequested.connect(self._section_requested)
        self.sidebar_toggle.clicked.connect(self._toggle_sidebar)
        self.home.drop_zone.filesDropped.connect(self._files_dropped)
        self.home.drop_zone.filesRefused.connect(self._files_refused)
        self.home.restoreRequested.connect(self.show_restore)
        self.home.casesRequested.connect(lambda: self.show_screen("cases"))
        self.home.engineStateChanged.connect(self.sidebar.set_engine_state)
        self.cases_screen.addFilesRequested.connect(self._add_files_to_case)
        self.cases_screen.restoreRequested.connect(self.show_restore)
        self.review_screen.exportRequested.connect(self.show_export)
        self.cases_screen.newCaseRequested.connect(self.show_home)
        # Each screen says its own two lines of the tool bar, and keeps them up to date.
        self.review_screen.titleChanged.connect(self._review_title_changed)
        for name, screen in (
            ("restore", self.restore_screen),
            ("cases", self.cases_screen),
        ):
            self._follow_title(name, screen)
        # The window has the Restore button: the screen's own goes, and the tool bar's follows
        # what the screen can do.
        self.restore_screen.set_primary_in_toolbar(True)
        self.restore_screen.primaryEnabledChanged.connect(lambda _on: self.refresh_chrome())
        self.analysisProgress.connect(self.home.show_progress)
        # The primary action and the file chooser follow what the screens switch on and off.
        _EnabledWatcher(self.home.drop_zone, self.refresh_chrome)

    def _review_title_changed(self, screen_title: str, caption: str) -> None:
        """The review's two lines: the caption is the screen's, live; the first line names every
        file, comma-joined (the screen's own wording shortens a long list).
        """
        names = ", ".join(source.path.name for source in self.sources)
        self.set_title(names or screen_title, caption, screen="review")

    def _follow_title(self, name: str, screen: RestoreScreen | CasesScreen) -> None:
        """Show the title and caption ``screen`` says in the tool bar while it shows, and again
        whenever it changes them.
        """
        self.set_title(*screen.title(), screen=name)
        screen.titleChanged.connect(
            lambda title, caption: self.set_title(title, caption, screen=name)
        )

    # ---- the shell -------------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        """The tool bar: the sidebar toggle, the title block in the middle, the primary action."""
        bar = QToolBar("Window")
        bar.setObjectName("mainToolBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        bar.setMinimumHeight(52)
        self.toolbar = bar
        self.sidebar_toggle = SidebarToggle()
        self.title_block = TitleBlock()
        self.title_block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.primary_action = QAction("Review", self)
        self.primary_action.triggered.connect(self._primary_triggered)
        bar.addWidget(self.sidebar_toggle)
        bar.addWidget(self.title_block)
        bar.addAction(self.primary_action)
        button = bar.widgetForAction(self.primary_action)
        assert isinstance(button, QToolButton)
        button.setObjectName("primaryAction")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        # The way through the window with Tab: the toggle, the primary action, the sections.
        previous: QWidget = self.sidebar_toggle
        for following in (button, *self.sidebar.items.values()):
            QWidget.setTabOrder(previous, following)
            previous = following

    def _build_menu(self) -> None:
        """The menu bar: Choose file… (Cmd+O) and the Settings, which the Mac moves into the
        application menu and shows under The MASK as Cmd+, (the role says so).
        """
        self.choose_action = QAction("Choose file…", self)
        self.choose_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        self.choose_action.triggered.connect(self._choose_triggered)
        self.settings_action = QAction("Settings…", self)
        self.settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        preferences = QKeySequence(QKeySequence.StandardKey.Preferences)
        # Where the system has no key for the preferences (Windows, Linux), it is Ctrl+, as well.
        self.settings_action.setShortcut(preferences if not preferences.isEmpty() else "Ctrl+,")
        self.settings_action.triggered.connect(self._settings_triggered)
        menu = self.menuBar().addMenu("File")
        menu.addAction(self.choose_action)
        menu.addSeparator()
        menu.addAction(self.settings_action)

    def _build_primary(self) -> None:
        """What the primary action does on each screen, and when it is on."""
        restore = self.restore_screen
        self.set_primary("home", "Review", lambda: self._show("review"), lambda: self._review_ready)
        self.set_primary("review", "Export…", self.show_export, lambda: self._review_ready)
        self.set_primary("restore", "Restore", restore.primary, restore.primary_enabled)
        self.set_primary("cases", "New case", self.show_home)

    def set_primary(
        self,
        screen: str,
        text: str,
        run: Callable[[], None],
        enabled: Callable[[], bool] | None = None,
    ) -> None:
        """Say what the primary action of ``screen`` is called (``text``), what it does (``run``)
        and when it is on (always, unless ``enabled`` says). It is off while a file is analysed,
        whatever the screen says.
        """
        if screen not in self._screens:
            raise KeyError(screen)
        self._primary[screen] = _Primary(text, run, enabled or (lambda: True))
        self.refresh_chrome()

    def refresh_chrome(self) -> None:
        """Check again whether the primary action and the file chooser are on, for what the screen
        that shows can do now. A screen whose state changes calls this.
        """
        entry = self._primary.get(self.current_screen_name())
        if entry is not None:
            self.primary_action.setText(entry.text)
            # A tool button shows the icon text, which Qt makes of the text without its "…".
            self.primary_action.setIconText(entry.text)
            self.primary_action.setEnabled(not self.is_analysing() and entry.enabled())
        self.choose_action.setEnabled(not self.is_analysing() and self.home.drop_zone.isEnabled())

    def set_title(self, title: str, caption: str = "", *, screen: str | None = None) -> None:
        """Set the two lines of the tool bar: ``title`` and, under it, ``caption``. They are those
        of the screen that shows, or of ``screen``, a screen that does not show yet: they are kept
        for when it does.
        """
        name = screen if screen is not None else self.current_screen_name()
        if name not in self._screens:
            raise KeyError(name)
        self._titles[name] = (title, caption)
        if name == self.current_screen_name():
            self._show_title(title, caption)

    def _show_title(self, title: str, caption: str) -> None:
        """Say the two lines in the tool bar. On the Mac the unified title bar already says the
        window's title; a toolbar line that only repeats it (the home screen's) is left out.
        """
        self.title_block.set_texts(title, caption)
        doubled = sys.platform == "darwin" and title == self.windowTitle() and not caption
        self.title_block.title_label.setVisible(not doubled)

    def add_toolbar_widget(self, screen: str, widget: QWidget) -> None:
        """Put ``widget`` in the tool bar, before the primary action, for as long as ``screen``
        shows (the review's check box for a before-and-after pair).
        """
        if screen not in self._screens:
            raise KeyError(screen)
        action = self.toolbar.insertWidget(self.primary_action, widget)
        self._toolbar_extras.setdefault(screen, []).append(action)
        action.setVisible(screen == self.current_screen_name())

    def _apply_chrome(self, name: str) -> None:
        """Make the tool bar, the sidebar and its note those of the screen ``name``."""
        self._show_title(*self._titles[name])
        self.sidebar.set_current(SECTION_OF_SCREEN[name])
        self.sidebar.set_context(name)
        if name == "cases":
            self.sidebar.set_retention_days(self.ctx.settings.retention_days)
        for screen, actions in self._toolbar_extras.items():
            for action in actions:
                action.setVisible(screen == name)
        self.refresh_chrome()

    def _toggle_sidebar(self) -> None:
        shown = not self.sidebar.isVisibleTo(self)
        self.sidebar.setVisible(shown)
        self.sidebar_toggle.set_sidebar_shown(shown)

    def _section_requested(self, section: str) -> None:
        """A section of the sidebar was chosen: Mask is the home screen."""
        {"mask": self.show_home, "restore": self.show_restore, "cases": self.show_cases}[section]()

    def _primary_triggered(self) -> None:
        if self.primary_action.isEnabled():  # QAction.trigger does not ask
            self._primary[self.current_screen_name()].run()

    def _choose_triggered(self) -> None:
        """Choose file…: on Restore it is the AI's returned file; on the review it is a new file
        to mask, which replaces the review, so the owner is asked first unless it was exported.
        """
        if not self.choose_action.isEnabled():
            return
        screen = self.current_screen_name()
        if screen == "restore":
            self.restore_screen.drop_zone.choose_files()
        elif screen == "review" and self._review_ready and not self._review_exported:
            if ask_discard_review(self):
                self.home.drop_zone.choose_files()
        else:
            self.home.drop_zone.choose_files()

    def _settings_triggered(self) -> None:
        if self.settings_action.isEnabled():
            self.show_settings()

    # ---- the screens -----------------------------------------------------------------------

    def screen_names(self) -> list[str]:
        """The names of the screens in the stack."""
        return list(self._screens)

    def current_screen_name(self) -> str:
        """The name of the screen that is showing."""
        current = self._stack.currentWidget()
        return next(name for name, screen in self._screens.items() if screen is current)

    def show_home(self) -> None:
        """Show the home screen, with the recent cases as the store holds them now."""
        if not self.is_analysing():
            self.home.refresh_recent()
        self._show("home")

    def show_screen(self, name: str) -> None:
        """Show the screen called ``name`` ("home", "review", "restore" or "cases"), made up to
        date as its own ``show_...`` makes it. The review is there only once a file was analysed:
        before that this does nothing. Raises KeyError for a name that is none of the screens
        (the Settings are a window, ``show_settings``).
        """
        if name == "home":
            self.show_home()
        elif name == "restore":
            self.show_restore()
        elif name == "cases":
            self.show_cases()
        elif name == "review":
            if self._review_ready:
                self._show("review")
        else:
            raise KeyError(name)

    def show_review(self, sources: list[SourceDoc], analysis: Analysis) -> None:
        """Show the review of an analysis of ``sources``.

        The review is made here, from the lists of the case the analysis belonged to (the same
        ones it filled in) and the placeholders of the case's key when a file is added to a case.
        The tool bar says the names of the files and what was found.
        """
        run = self._run
        case = run.case if run is not None else None
        case_lists = run.case_lists if run is not None else CaseLists([], [], set())
        reserved = [entry.placeholder for entry in case.entries] if case is not None else []
        reserved_labels = (
            {e.placeholder: e.label for e in case.entries if e.label is not None}
            if case is not None
            else {}
        )
        review = ReviewState.from_analysis(
            analysis, self.ctx.user_lists, case_lists, reserved, reserved_labels
        )
        # The screen first: when it cannot show the review, nothing of the window has changed.
        self.review_screen.load(review, combined_text(sources))
        self.sources = sources
        self.redline_split = any(source.pkg_before is not None for source in sources)
        self.pending_case = case
        self._review_ready = True
        self._review_exported = False
        self._review_title_changed(*self.review_screen.title())
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
        # A name typed in the review and not yet committed is given first, and one the review
        # refuses, or a name that clashes with a value, stops the export here, in words.
        if not self.review_screen.commit_pending_name():
            return
        problems = self.review_screen.review.label_problems()
        if problems:
            more = (
                f" ({len(problems) - 1} more are listed in the review.)"
                if len(problems) > 1
                else ""
            )
            show_error(self, problems[0] + more)
            return
        review = self.review_screen.review
        unanswered = sum(asks_about(g, review.answered) for g in review.groups)
        if unanswered and not ask_unanswered(self, unanswered):
            return
        try:
            codes = self._case_codes()
        except MaskError as error:
            show_error(self, error.user_message)
            return
        except OSError as error:
            show_error(self, f"{NOT_READ} {error.strerror or error}")
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
        dialog.finishedExport.connect(self._export_finished)
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

    def _export_finished(self) -> None:
        outcome = self.export_dialog.result if self.export_dialog is not None else None
        if outcome is not None and not outcome.blocked:
            self._review_exported = True

    def _export_closed(self) -> None:
        dialog, self.export_dialog = self.export_dialog, None
        if dialog is not None:
            dialog.deleteLater()

    def show_restore(self, case_id: str | None = None) -> None:
        """Show the restore screen with the cases the store holds now; ``case_id`` is the case the
        owner asked for in the Cases screen, selected when it is there.
        """
        self.restore_screen.refresh_cases(case_id)
        self._show("restore")

    def show_cases(self) -> None:
        """Show the saved cases as the store holds them now."""
        self.cases_screen.refresh()
        self._show("cases")

    def show_settings(self) -> None:
        """Open the Settings window, which shows what is kept now (the review may have changed
        the lists), or bring it to the front when it is open.
        """
        window = self.settings_window
        window.show()
        window.raise_()
        window.activateWindow()

    def _show(self, name: str) -> None:
        """Put the screen ``name`` in front. The old screen fades out over the new one when the
        window is showing (``ANIMATIONS``): the new screen is the current one at once.
        """
        target = self._screens[name]
        previous = self._screens[self.current_screen_name()]
        self._end_fade()
        snapshot = None
        if ANIMATIONS and self.isVisible() and previous is not target:
            snapshot = previous.grab()
        self._stack.setCurrentWidget(target)
        self._apply_chrome(name)
        if snapshot is not None:
            self._fade_out(snapshot)

    def _fade_out(self, snapshot: QPixmap) -> None:
        """A picture of the screen that was left, over the new one, fading out (``FADE_MS``)."""
        overlay = QLabel(self._stack)
        overlay.setObjectName("crossfade")
        overlay.setPixmap(snapshot)
        overlay.setGeometry(self._stack.rect())
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        overlay.show()
        overlay.raise_()
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(FADE_MS)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.finished.connect(self._end_fade)
        self._fade = (animation, overlay)
        animation.start()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """The picture of the old screen follows the stack while it fades."""
        super().resizeEvent(event)
        if self._fade is not None:
            self._fade[1].setGeometry(self._stack.rect())

    def _end_fade(self) -> None:
        """Take the picture of the old screen away, at the end of the fade or when another begins."""
        fade, self._fade = self._fade, None
        if fade is not None:
            animation, overlay = fade
            animation.stop()
            animation.deleteLater()
            overlay.hide()
            overlay.deleteLater()

    def _set_navigation(self, enabled: bool) -> None:
        """Switch the sections of the sidebar, the Settings and the primary action on or off: they
        are off while a file is analysed, so that nothing the analysis reads (the owner's lists,
        the case) changes under it.
        """
        self.sidebar.set_navigation_enabled(enabled)
        self.settings_action.setEnabled(enabled)
        self.settings_window.setEnabled(enabled)
        self.refresh_chrome()

    # ---- opening files ---------------------------------------------------------------------

    def open_files(
        self, paths: list[Path], redline_split: bool | None, case_id: str | None = None
    ) -> None:
        """Analyse the files at ``paths`` and show the review.

        ``redline_split`` says whether a file with tracked changes is made into a before-and-after
        pair; None asks the owner, once, when any of the Word files has tracked changes. With
        ``case_id`` the files are added to that case: the analysis is seeded with its key and
        the review keeps its placeholders. A request made while another analysis is running, or
        waits for the engine, is refused: one at a time. Whatever goes wrong is shown to the
        owner, and ``analysisFailed`` is sent.
        """
        if not paths:
            return
        if self._analysis is not None or self._queued is not None:
            show_error(self, BUSY_MESSAGE)
            return
        self.show_home()  # the progress of the analysis, or "Loading…" while the engine is
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
        self.home.clear_refused()  # what an earlier drop left out is no news now
        self.open_files(paths, None)

    def _files_refused(self, paths: list[Path]) -> None:
        self.home.show_refused(_refused_notice(paths))
        self.show_home()  # where the notice is: the files may have been chosen on another screen

    def _add_files_to_case(self, paths: list[Path], case_id: str) -> None:
        self.open_files(paths, None, case_id)

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
        self._set_navigation(False)
        self.show_home()  # the progress is there, wherever the owner went while the engine loaded
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
        failed = False
        try:
            self.show_review(sources, analysis)
        except Exception as error:  # noqa: BLE001 - the owner is told, the app goes on
            # Only the kind of error is logged: its text may quote the document.
            _LOG.error("review failed error=%s", type(error).__name__)
            failed = True
        self._run = None
        self.home.show_ready()
        if failed:
            self._fail(REVIEW_FAILED)
        else:
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
            self._set_navigation(True)

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
        except KeyStoreError as error:
            self.home.keychain_refused = True  # asked once: the recent cases do not ask again
            self.home.add_notice(f"{PURGE_FAILED} {error.user_message}")
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
        self.settings_window.close()
        self.wait_for_workers()
        super().closeEvent(event)


def _refused_notice(paths: list[Path]) -> str:
    """What the home screen says of files that were not opened: their names, what The MASK reads,
    and what to do about an old .doc.
    """
    names = ", ".join(path.name for path in paths)
    notice = f"Not opened: {names}. {UNSUPPORTED_MESSAGE}"
    if any(path.suffix.casefold() == ".doc" for path in paths):
        notice += " An old .doc can be opened in Word and saved as .docx."
    return notice


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
