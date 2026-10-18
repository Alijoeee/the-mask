"""The drop zone: Word and PDF files dropped on it, or chosen with its button."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog

from themask.ui.drop_zone import FILE_FILTER, DropZone

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


def urls(*names: str) -> QMimeData:
    """Drag data that holds local files with these names (they need not exist)."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(f"/somewhere/{name}") for name in names])
    return mime


def drag_over(zone: DropZone, mime: QMimeData) -> bool:
    """Whether the zone accepts a drag of ``mime`` entering it."""
    event = QDragEnterEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(zone, event)
    return event.isAccepted()


def drop_on(zone: DropZone, mime: QMimeData) -> None:
    """Drop ``mime`` on the zone the way a drag does: it enters first, and Qt delivers the drop
    only to the widget that accepted it.
    """
    drag_over(zone, mime)
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(zone, event)


@pytest.fixture
def zone(qtbot: QtBot) -> DropZone:
    z = DropZone()
    qtbot.addWidget(z)
    z.show()
    return z


def test_a_drag_of_word_and_pdf_files_is_accepted(zone: DropZone) -> None:
    assert drag_over(zone, urls("Supply Agreement.docx"))
    assert drag_over(zone, urls("scan.pdf"))
    assert drag_over(zone, urls("a.docx", "b.pdf"))


def test_the_extension_counts_in_any_case(zone: DropZone) -> None:
    assert drag_over(zone, urls("SUPPLY.DOCX")) and drag_over(zone, urls("Scan.Pdf"))


@pytest.mark.parametrize(
    "name", ["notes.txt", "old.doc", "sheet.xlsx", "slides.pptx", "archive.zip", "no-extension"]
)
def test_a_drag_of_other_files_is_ignored(zone: DropZone, name: str) -> None:
    assert not drag_over(zone, urls(name))


def test_a_drag_of_something_that_is_not_a_file_is_ignored(zone: DropZone) -> None:
    text = QMimeData()
    text.setText("Supply Agreement.docx")
    assert not drag_over(zone, text)


def test_a_drop_gives_the_files_in_the_order_they_came(qtbot: QtBot, zone: DropZone) -> None:
    with qtbot.waitSignal(zone.filesDropped, timeout=1000) as dropped:
        drop_on(zone, urls("b.pdf", "a.docx", "C.DOCX"))
    assert dropped.args == [
        [Path("/somewhere/b.pdf"), Path("/somewhere/a.docx"), Path("/somewhere/C.DOCX")]
    ]


def test_a_mixed_drop_gives_only_the_contracts(qtbot: QtBot, zone: DropZone) -> None:
    mime = urls("a.docx", "notes.txt", "old.doc", "b.pdf")
    assert drag_over(zone, mime)
    with qtbot.waitSignal(zone.filesDropped, timeout=1000) as dropped:
        drop_on(zone, mime)
    assert dropped.args == [[Path("/somewhere/a.docx"), Path("/somewhere/b.pdf")]]


def test_a_drop_of_other_files_gives_nothing(qtbot: QtBot, zone: DropZone) -> None:
    with qtbot.assertNotEmitted(zone.filesDropped):
        drop_on(zone, urls("notes.txt"))


def test_a_disabled_zone_takes_nothing(qtbot: QtBot, zone: DropZone) -> None:
    zone.setEnabled(False)
    assert not drag_over(zone, urls("a.docx"))
    with qtbot.assertNotEmitted(zone.filesDropped):
        drop_on(zone, urls("a.docx"))


def test_the_button_opens_the_file_dialog_and_gives_the_chosen_files(
    qtbot: QtBot, zone: DropZone, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[object, ...]] = []

    def choose(*args: object, **kwargs: object) -> tuple[list[str], str]:
        asked.append(args)
        return ["/somewhere/a.docx", "/somewhere/b.pdf", "/somewhere/notes.txt"], FILE_FILTER

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(choose))
    assert zone.choose_button.text() == "Choose files…"
    with qtbot.waitSignal(zone.filesDropped, timeout=1000) as chosen:
        qtbot.mouseClick(zone.choose_button, Qt.MouseButton.LeftButton)
    assert FILE_FILTER == "Contracts (*.docx *.pdf)" and FILE_FILTER in asked[0]
    assert chosen.args == [[Path("/somewhere/a.docx"), Path("/somewhere/b.pdf")]]


def test_a_cancelled_dialog_gives_nothing(
    qtbot: QtBot, zone: DropZone, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))
    with qtbot.assertNotEmitted(zone.filesDropped):
        qtbot.mouseClick(zone.choose_button, Qt.MouseButton.LeftButton)


def test_it_tells_what_it_takes(zone: DropZone) -> None:
    assert ".docx" in zone.hint_label.text() and "PDF" in zone.hint_label.text()


def test_the_button_goes_with_the_zone(zone: DropZone) -> None:
    zone.setEnabled(False)
    assert not zone.choose_button.isEnabled()
