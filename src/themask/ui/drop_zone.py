"""The drop zone: where the owner drops Word and PDF files, or chooses them with a button.

The files The MASK reads go on as ``filesDropped``. The others are not ignored: they go on as
``filesRefused``, so that the owner is told why nothing happened to them (an old .doc can be saved
as .docx in Word) and not left with a drop that did nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

FILE_FILTER = "Contracts (*.docx *.pdf)"
# A file is read as one of these by its extension, in any case (themask.export.load_sources).
SUFFIXES = frozenset({".docx", ".pdf"})
CHOOSE_TITLE = "Choose contracts"
TITLE = "Drop your contracts here"
HINT = "Word (.docx) or PDF files with selectable text. Files dropped together share one key."


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

    The "Choose files…" button does the same through the system's file dialog. Something that is
    not a list of files is not taken, and a disabled zone takes nothing. A zone for other files
    than the contracts is told which (``suffixes``), what it says (``title`` and ``hint``) and what
    its file dialog is called and shows (``dialog_title`` and ``file_filter``).
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
    ) -> None:
        super().__init__(parent)
        self._suffixes = suffixes
        self._dialog_title = dialog_title
        self._file_filter = file_filter
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragOver", False)
        # Room for the title, the hint on two lines and the button: a label that wraps cannot say
        # how tall it needs to be for the width it gets, so the layout would squeeze them.
        self.setMinimumHeight(220)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("dropTitle")
        self.hint_label = QLabel(hint)
        self.hint_label.setWordWrap(True)
        self.choose_button = QPushButton("Choose files…")
        self.choose_button.clicked.connect(self.choose_files)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(12)
        for widget in (self.title_label, self.hint_label):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(widget)
        layout.addWidget(self.choose_button, alignment=Qt.AlignmentFlag.AlignCenter)

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
