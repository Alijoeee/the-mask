"""The drop zone: where the owner drops Word and PDF files, or chooses them with a button.

The files The MASK reads go on as ``filesDropped``. The others are not ignored: they go on as
``filesRefused``, so that the owner is told why nothing happened to them (an old .doc can be saved
as .docx in Word) and not left with a drop that did nothing.

The zone is a card: an illustration, a title, a caption, the button and, when it is told one, a
hint at the shortcut. A drag over it takes the accent's border and background (the stylesheet
reads the ``dragOver`` property). The screens that need more in the card put it under the caption
(``status_layout``).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from themask.ui.art import Illustration

FILE_FILTER = "Contracts (*.docx *.pdf)"
# A file is read as one of these by its extension, in any case (themask.export.load_sources).
SUFFIXES = frozenset({".docx", ".pdf"})
CHOOSE_TITLE = "Choose contracts"
TITLE = "Drop a contract here"
HINT = (
    "Word or PDF. Confidential values are swapped for placeholders before anything leaves this Mac."
)
CHOOSE_TEXT = "Choose file…"


def contract_paths(paths: Iterable[Path], suffixes: frozenset[str] = SUFFIXES) -> list[Path]:
    """The files among ``paths`` that The MASK reads (Word and PDF, or the ``suffixes`` asked for,
    each written in lower case with its dot), in their order.
    """
    return [path for path in paths if path.suffix.casefold() in suffixes]


def ask_for_files(
    parent: QWidget | None, title: str = CHOOSE_TITLE, file_filter: str = FILE_FILTER
) -> list[Path]:
    """Ask for files with the system's dialog: every file chosen, whatever its kind."""
    chosen, _ = QFileDialog.getOpenFileNames(parent, title, str(Path.home()), file_filter)
    return [Path(name) for name in chosen]


def _dropped_files(mime: QMimeData) -> list[Path]:
    """The local files a drag carries; none for anything that is not a list of files."""
    if not mime.hasUrls():
        return []
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


class DropZone(QFrame):
    """A frame that takes files dropped on it: the Word and PDF files go on with
    ``filesDropped``, the other files of the same drop with ``filesRefused`` (after it).

    The button (``choose_button``, "Choose file…") does the same through the system's file
    dialog. Something that is not a list of files is not taken, and a disabled zone takes nothing.
    A zone for other files than the contracts is told which (``suffixes``), what it says
    (``title`` and ``hint``) and what its file dialog is called and shows (``dialog_title`` and
    ``file_filter``). ``art`` names the illustration over the title ("mask" or "check", none by
    default), ``choose_text`` is the words of the button and ``shortcut_hint`` the little text
    beside it that says which key does the same.
    """

    filesDropped = Signal(list)  # list[Path]
    filesRefused = Signal(list)  # list[Path]: what the zone does not take

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        suffixes: frozenset[str] = SUFFIXES,
        title: str = TITLE,
        hint: str = HINT,
        dialog_title: str = CHOOSE_TITLE,
        file_filter: str = FILE_FILTER,
        art: str | None = None,
        choose_text: str = CHOOSE_TEXT,
        shortcut_hint: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._suffixes = suffixes
        self._dialog_title = dialog_title
        self._file_filter = file_filter
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragOver", False)
        self.setAccessibleName(title)
        self.setAccessibleDescription(hint)
        self.illustration = Illustration(art) if art is not None else None
        self.title_label = QLabel(title)
        self.title_label.setObjectName("dropTitle")
        self.title_label.setWordWrap(True)
        title_font = self.title_label.font()
        title_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, -0.2
        )  # as the mockup's title
        self.title_label.setFont(title_font)
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("dropHint")
        self.hint_label.setWordWrap(True)
        self.status_layout = QVBoxLayout()  # what a screen adds under the caption
        self.status_layout.setSpacing(8)
        self.choose_button = QPushButton(choose_text)
        self.choose_button.setObjectName("chooseButton")
        self.choose_button.clicked.connect(self.choose_files)
        self.shortcut_label = QLabel(shortcut_hint or "")
        self.shortcut_label.setObjectName("dropShortcut")
        self.shortcut_label.setVisible(bool(shortcut_hint))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 44, 32, 36)
        layout.setSpacing(12)
        if self.illustration is not None:
            layout.addWidget(self.illustration, alignment=Qt.AlignmentFlag.AlignHCenter)
            layout.addSpacing(8)
        for widget in (self.title_label, self.hint_label):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(widget)
        layout.addLayout(self.status_layout)
        layout.addSpacing(12)
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addStretch(1)
        buttons.addWidget(self.choose_button)
        buttons.addWidget(self.shortcut_label)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def choose_files(self) -> None:
        """Ask for files with the system's dialog, and pass them on."""
        self._pass_on(ask_for_files(self, self._dialog_title, self._file_filter))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._take_or_refuse(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._take_or_refuse(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._mark_drag_over(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._mark_drag_over(False)
        paths = _dropped_files(event.mimeData()) if self.isEnabled() else []
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._pass_on(paths)

    def _take_or_refuse(self, event: QDragEnterEvent | QDragMoveEvent) -> None:
        if self.isEnabled() and _dropped_files(event.mimeData()):
            event.acceptProposedAction()
            self._mark_drag_over(True)
        else:
            event.ignore()
            self._mark_drag_over(False)

    def _mark_drag_over(self, over: bool) -> None:
        """Show that a drop would be taken (the stylesheet reads the property)."""
        if self.property("dragOver") != over:
            self.setProperty("dragOver", over)
            self.style().unpolish(self)
            self.style().polish(self)

    def _pass_on(self, paths: list[Path]) -> None:
        contracts = contract_paths(paths, self._suffixes)
        refused = [path for path in paths if path not in contracts]
        if contracts:
            self.filesDropped.emit(contracts)
        if refused:
            self.filesRefused.emit(refused)
