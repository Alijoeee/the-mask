"""The drop zone: Word and PDF files dropped on it, or chosen with its button.

What it does not read is not ignored: a drag of any file is taken, and the files that are not Word
or PDF go on as ``filesRefused``, so that the window can say why nothing happened to them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QMimeData, QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel

from themask.ui import theme
from themask.ui.art import Illustration
from themask.ui.drop_zone import FILE_FILTER, DropZone, ask_for_files, contract_paths

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
def test_a_drag_of_other_files_is_taken_so_that_the_drop_can_say_why_not(
    zone: DropZone, name: str
) -> None:
    assert drag_over(zone, urls(name))


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


def test_a_drop_of_other_files_gives_nothing_to_analyse_but_names_them(
    qtbot: QtBot, zone: DropZone
) -> None:
    with (
        qtbot.assertNotEmitted(zone.filesDropped),
        qtbot.waitSignal(zone.filesRefused, timeout=1000) as refused,
    ):
        drop_on(zone, urls("notes.txt"))
    assert refused.args == [[Path("/somewhere/notes.txt")]]


def test_a_mixed_drop_names_what_it_left_out_after_the_contracts(
    qtbot: QtBot, zone: DropZone
) -> None:
    order: list[str] = []
    zone.filesDropped.connect(lambda paths: order.append("dropped"))
    zone.filesRefused.connect(lambda paths: order.append("refused"))
    with qtbot.waitSignal(zone.filesRefused, timeout=1000) as refused:
        drop_on(zone, urls("a.docx", "notes.txt", "old.doc", "b.pdf"))
    assert refused.args == [[Path("/somewhere/notes.txt"), Path("/somewhere/old.doc")]]
    assert order == ["dropped", "refused"]  # the analysis starts before the notice is made


def test_a_drop_of_contracts_alone_refuses_nothing(qtbot: QtBot, zone: DropZone) -> None:
    with (
        qtbot.assertNotEmitted(zone.filesRefused),
        qtbot.waitSignal(zone.filesDropped, timeout=1000),
    ):
        drop_on(zone, urls("a.docx", "SCAN.PDF"))


def test_a_disabled_zone_takes_nothing(qtbot: QtBot, zone: DropZone) -> None:
    zone.setEnabled(False)
    assert not drag_over(zone, urls("a.docx")) and not drag_over(zone, urls("notes.txt"))
    with qtbot.assertNotEmitted(zone.filesDropped), qtbot.assertNotEmitted(zone.filesRefused):
        drop_on(zone, urls("a.docx", "notes.txt"))


def test_the_button_opens_the_file_dialog_and_gives_the_chosen_files(
    qtbot: QtBot, zone: DropZone, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[object, ...]] = []

    def choose(*args: object, **kwargs: object) -> tuple[list[str], str]:
        asked.append(args)
        return ["/somewhere/a.docx", "/somewhere/b.pdf", "/somewhere/notes.txt"], FILE_FILTER

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(choose))
    assert zone.choose_button.text() == "Choose file…"
    refused: list[list[Path]] = []
    zone.filesRefused.connect(refused.append)
    with qtbot.waitSignal(zone.filesDropped, timeout=1000) as chosen:
        qtbot.mouseClick(zone.choose_button, Qt.MouseButton.LeftButton)
    assert FILE_FILTER == "Contracts (*.docx *.pdf)" and FILE_FILTER in asked[0]
    assert chosen.args == [[Path("/somewhere/a.docx"), Path("/somewhere/b.pdf")]]
    assert refused == [[Path("/somewhere/notes.txt")]]  # a file the dialog let through is named


def test_a_cancelled_dialog_gives_nothing(
    qtbot: QtBot, zone: DropZone, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))
    with qtbot.assertNotEmitted(zone.filesDropped):
        qtbot.mouseClick(zone.choose_button, Qt.MouseButton.LeftButton)


def test_it_tells_what_it_takes(zone: DropZone) -> None:
    assert "Word" in zone.hint_label.text() and "PDF" in zone.hint_label.text()


def test_the_button_goes_with_the_zone(zone: DropZone) -> None:
    zone.setEnabled(False)
    assert not zone.choose_button.isEnabled()


def test_ask_for_files_gives_every_file_chosen_whatever_its_kind(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: (["/x/a.docx", "/x/old.doc"], FILE_FILTER)),
    )
    assert ask_for_files(None) == [Path("/x/a.docx"), Path("/x/old.doc")]


# ---- a zone for other files than the contracts ----------------------------------------------------


@pytest.fixture
def word_zone(qtbot: QtBot) -> DropZone:
    """A zone for the AI's Word file alone, as the restore screen has it."""
    z = DropZone(
        suffixes=frozenset({".docx"}),
        title="Drop the AI's Word file here",
        hint="The .docx the AI gave back.",
        dialog_title="Choose the AI's Word file",
        file_filter="Word files (*.docx)",
    )
    qtbot.addWidget(z)
    z.show()
    return z


def test_a_zone_for_one_kind_of_file_refuses_the_others_even_a_pdf(
    qtbot: QtBot, word_zone: DropZone
) -> None:
    with (
        qtbot.waitSignal(word_zone.filesDropped, timeout=1000) as dropped,
        qtbot.waitSignal(word_zone.filesRefused, timeout=1000) as refused,
    ):
        drop_on(word_zone, urls("a.docx", "b.pdf", "C.DOCX"))
    assert dropped.args == [[Path("/somewhere/a.docx"), Path("/somewhere/C.DOCX")]]
    assert refused.args == [[Path("/somewhere/b.pdf")]]


def test_a_zone_says_what_it_is_told_to(word_zone: DropZone) -> None:
    assert word_zone.title_label.text() == "Drop the AI's Word file here"
    assert word_zone.hint_label.text() == "The .docx the AI gave back."


def test_a_zone_s_file_dialog_has_the_title_and_filter_it_is_told(
    qtbot: QtBot, word_zone: DropZone, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[object, ...]] = []

    def choose(*args: object, **kwargs: object) -> tuple[list[str], str]:
        asked.append(args)
        return ["/somewhere/a.docx", "/somewhere/b.pdf"], ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(choose))
    with (
        qtbot.waitSignal(word_zone.filesDropped, timeout=1000) as chosen,
        qtbot.waitSignal(word_zone.filesRefused, timeout=1000) as refused,
    ):
        qtbot.mouseClick(word_zone.choose_button, Qt.MouseButton.LeftButton)
    assert "Choose the AI's Word file" in asked[0] and "Word files (*.docx)" in asked[0]
    assert chosen.args == [[Path("/somewhere/a.docx")]]
    assert refused.args == [[Path("/somewhere/b.pdf")]]


def test_the_zone_for_contracts_keeps_its_own_words_and_dialog(
    qtbot: QtBot, zone: DropZone, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: (asked.append(a), ([], ""))[1]),
    )
    qtbot.mouseClick(zone.choose_button, Qt.MouseButton.LeftButton)
    assert "Choose contracts" in asked[0] and FILE_FILTER in asked[0]
    assert zone.title_label.text() == "Drop a contract here"


def test_contract_paths_goes_by_the_suffixes_it_is_given() -> None:
    paths = [Path("/x/a.docx"), Path("/x/b.PDF"), Path("/x/c.txt")]
    assert contract_paths(paths) == [Path("/x/a.docx"), Path("/x/b.PDF")]
    assert contract_paths(paths, frozenset({".txt"})) == [Path("/x/c.txt")]


# ---- the card ------------------------------------------------------------------------------------


def test_the_zone_for_contracts_says_what_the_mockup_says(zone: DropZone) -> None:
    assert zone.title_label.text() == "Drop a contract here"
    assert zone.hint_label.text() == (
        "Word or PDF. Confidential values are swapped for placeholders before anything leaves"
        " this Mac."
    )
    assert zone.choose_button.text() == "Choose file…"
    assert zone.illustration is None and zone.shortcut_label.isHidden()  # the screen adds its own


def test_a_zone_can_have_an_illustration_its_own_button_words_and_a_hint_at_a_shortcut(
    qtbot: QtBot,
) -> None:
    z = DropZone(art="mask", choose_text="Choose another file…", shortcut_hint="or press ⌘O")
    qtbot.addWidget(z)
    z.show()
    assert isinstance(z.illustration, Illustration) and z.illustration.size() == QSize(112, 88)
    assert z.choose_button.text() == "Choose another file…"
    assert z.shortcut_label.text() == "or press ⌘O" and not z.shortcut_label.isHidden()
    assert z.shortcut_label.objectName() == "dropShortcut"
    check = DropZone(art="check")
    qtbot.addWidget(check)
    assert check.illustration is not None and check.illustration.size() == QSize(64, 64)


def test_the_title_is_set_a_little_tight_like_the_mockups(qtbot: QtBot, zone: DropZone) -> None:
    assert zone.title_label.font().letterSpacing() == pytest.approx(-0.2, abs=0.02)
    zone.setStyleSheet(theme.stylesheet("light"))  # the stylesheet sets its size and weight
    zone.show()
    qtbot.wait(20)
    assert zone.title_label.font().pixelSize() == 22
    assert zone.title_label.font().letterSpacing() == pytest.approx(-0.2, abs=0.02)


def test_the_zone_is_named_for_a_screen_reader(zone: DropZone) -> None:
    assert zone.accessibleName() == "Drop a contract here"
    assert zone.accessibleDescription() == zone.hint_label.text()


def test_the_card_has_the_padding_of_the_mockup(zone: DropZone) -> None:
    margins = zone.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (32, 44, 32, 36)


def test_a_screen_can_put_its_status_under_the_caption_and_above_the_button(
    qtbot: QtBot,
) -> None:
    z = DropZone(art="mask")
    qtbot.addWidget(z)
    status = QLabel("Analysing…")
    z.status_layout.addWidget(status)
    z.show()
    assert z.title_label.y() < z.hint_label.y() < status.y() < z.choose_button.y()
    assert z.isAncestorOf(status)


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_the_card_is_a_panel_with_a_border_and_a_drag_over_it_takes_the_accent(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    z = DropZone()
    qtbot.addWidget(z)
    z.setPalette(theme.palette(appearance))
    z.setStyleSheet(theme.stylesheet(appearance))
    z.resize(400, 260)
    z.show()

    def look() -> tuple[QColor, QColor]:
        image = z.grab().toImage()
        return image.pixelColor(200, 3), image.pixelColor(0, 130)  # inside, and the left edge

    inside, edge = look()
    assert inside == QColor(t.panel) and edge == QColor(t.border)
    assert drag_over(z, urls("a.docx"))
    inside, edge = look()
    assert inside == QColor(t.accent_soft) and edge == QColor(t.accent)
    z.dragLeaveEvent(QDragLeaveEvent())
    inside, edge = look()
    assert inside == QColor(t.panel) and edge == QColor(t.border)
