"""The drop zone: where the owner drops Word and PDF files, or chooses them with a button."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

FILE_FILTER = "Contracts (*.docx *.pdf)"
# A file is read as one of these by its extension, in any case (themask.export.load_sources).
SUFFIXES = frozenset({".docx", ".pdf"})


def contract_paths(paths: Iterable[Path]) -> list[Path]:
    """The files among ``paths`` that The MASK reads (Word and PDF), in their order."""
    return [path for path in paths if path.suffix.casefold() in SUFFIXES]


def _dropped_contracts(mime: QMimeData) -> list[Path]:
    """The Word and PDF files a drag carries; none for anything that is not a list of files."""
    if not mime.hasUrls():
        return []
    return contract_paths(Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile())


class DropZone(QFrame):
    """A frame that takes Word and PDF files dropped on it and says so with ``filesDropped``.

    Anything else dropped on it is ignored; of a mixed drop only the contracts are passed on. The
    "Choose files…" button does the same through the system's file dialog. A disabled zone takes
    nothing.
    """

    filesDropped = Signal(list)  # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragOver", False)
        self.title_label = QLabel("Drop your contracts here")
        self.title_label.setObjectName("dropTitle")
        self.hint_label = QLabel(
            "Word (.docx) or PDF files with selectable text. Files dropped together share one key."
        )
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
        """Ask for files with the system's dialog, and pass the Word and PDF files on."""
        chosen, _ = QFileDialog.getOpenFileNames(
            self, "Choose contracts", str(Path.home()), FILE_FILTER
        )
        self._pass_on(contract_paths(Path(name) for name in chosen))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._take_or_refuse(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._take_or_refuse(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._mark_drag_over(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._mark_drag_over(False)
        paths = _dropped_contracts(event.mimeData()) if self.isEnabled() else []
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._pass_on(paths)

    def _take_or_refuse(self, event: QDragEnterEvent | QDragMoveEvent) -> None:
        if self.isEnabled() and _dropped_contracts(event.mimeData()):
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
        if paths:
            self.filesDropped.emit(paths)
